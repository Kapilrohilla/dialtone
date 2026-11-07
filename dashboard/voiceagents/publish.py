"""Publishing: the only way an agent's configuration reaches callers.

Every status change (publish, unpublish, archive, restore) runs in one transaction that locks the
Workspace row first and then the Agent row(s). The workspace lock serialises publishes so that at
most one agent per workspace is ever published; the partial unique constraint on Agent is a backstop.
"""
import copy
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Max

from knowledge.models import KnowledgeDocument, KnowledgeRevision
from workflows.graph import validate
from workflows.models import Workflow, WorkflowRevision
from workspaces.models import Workspace

from .models import Agent, AgentVersion
from .tokens import long_pause_errors, render_hints, unknown_expressions, variables

EMPTY_GRAPH = {"steps": [], "paths": []}


class PublishError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = list(errors)


class StateError(Exception):
    """A status change that is not allowed from the agent's current status."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def _custom(agent) -> dict:
    return agent.custom_expressions if isinstance(agent.custom_expressions, dict) else {}


def _sections(agent) -> list[tuple[str, str]]:
    """(title, body) for each well-formed script section, in order."""
    out = []
    for s in agent.script if isinstance(agent.script, list) else []:
        if isinstance(s, dict):
            title = s.get("title") if isinstance(s.get("title"), str) else ""
            body = s.get("body") if isinstance(s.get("body"), str) else ""
            out.append((title, body))
    return out


def _rendered_script(agent) -> list[dict]:
    custom = _custom(agent)
    return [{"title": t, "body_rendered": render_hints(b, custom)} for t, b in _sections(agent)]


def _linked_docs(agent):
    return agent.knowledge.filter(workspace_id=agent.workspace_id).order_by("id")


def _workflow(agent):
    wf = agent.workflow if agent.workflow_id else None
    if wf is None or wf.workspace_id != agent.workspace_id:
        return None
    return wf


@dataclass
class Resolved:
    """The workflow revision and knowledge revisions a publish uses, read exactly once."""

    workflow: Workflow | None  # linked, in this workspace, not archived
    workflow_revision: WorkflowRevision | None
    graph: dict
    knowledge: list[tuple[KnowledgeDocument, KnowledgeRevision | None]] = field(default_factory=list)


def _step_knowledge_ids(graph) -> set[int]:
    steps = graph.get("steps") if isinstance(graph, dict) else None
    ids = set()
    for st in steps if isinstance(steps, list) else []:
        if isinstance(st, dict) and st.get("type") == "knowledge":
            kid = st.get("knowledge_id")
            if isinstance(kid, int) and not isinstance(kid, bool):
                ids.add(kid)
    return ids


def resolve(agent, lock: bool = False) -> Resolved:
    """Read the agent's workflow revision and its knowledge (linked docs plus docs the workflow's
    knowledge steps use) once. With `lock`, the Workflow row is locked so no save can land mid-publish."""
    wf = _workflow(agent)
    if wf is not None and lock:
        wf = Workflow.objects.select_for_update().get(pk=wf.pk)
    rev = None
    if wf is not None and wf.archived:
        wf = None
    if wf is not None:
        rev = wf.revisions.order_by("-number").first()
    graph = rev.graph if rev else EMPTY_GRAPH
    linked = set(_linked_docs(agent).values_list("id", flat=True))
    docs = KnowledgeDocument.objects.filter(
        workspace_id=agent.workspace_id, archived=False, id__in=linked | _step_knowledge_ids(graph)
    ).order_by("id")
    knowledge = [(doc, doc.revisions.order_by("-number").first()) for doc in docs]
    return Resolved(workflow=wf, workflow_revision=rev, graph=graph, knowledge=knowledge)


def validation_errors(agent, resolved: Resolved | None = None) -> list[str]:
    resolved = resolved or resolve(agent)
    errors: list[str] = []
    custom = _custom(agent)
    sections = _sections(agent)
    if not any(body.strip() for _, body in sections):
        errors.append("Write at least one script section before publishing.")
    for title, body in sections:
        for expr in unknown_expressions(body, custom):
            errors.append(f'Section "{title.strip() or "Untitled"}" uses an unknown expression "{expr}".')
        for msg in long_pause_errors(body):
            errors.append(f'Section "{title.strip() or "Untitled"}": {msg}')
    for doc in _linked_docs(agent).filter(archived=True):
        errors.append(f'Knowledge document "{doc.title}" is archived. Remove it from this agent or restore it.')
    wf = _workflow(agent)
    if agent.workflow_id and wf is None:
        errors.append("The linked workflow does not exist. Choose another workflow or remove it.")
    elif wf is not None and resolved.workflow is None:
        errors.append(f'The workflow "{wf.name}" is archived. Choose another workflow or remove it.')
    elif resolved.workflow is not None:
        ids = set(
            KnowledgeDocument.objects.filter(workspace_id=agent.workspace_id, archived=False)
            .values_list("id", flat=True)
        )
        errors.extend(validate(resolved.graph, ids, custom))
    return errors


def build_snapshot(agent, number: int, resolved: Resolved | None = None) -> dict:
    resolved = resolved or resolve(agent)
    custom = _custom(agent)
    found: list[str] = []

    def collect(text):
        for v in variables(text):
            if v not in found:
                found.append(v)

    for _, body in _sections(agent):
        collect(body)

    knowledge = [
        {"id": doc.id, "title": doc.title, "revision": rev.number if rev else 0, "body_md": rev.body_md if rev else "",
         "body_rendered": render_hints(rev.body_md, custom) if rev else ""}
        for doc, rev in resolved.knowledge
    ]

    workflow = None
    if resolved.workflow is not None:
        rev = resolved.workflow_revision
        graph = copy.deepcopy(resolved.graph)
        for st in graph.get("steps") or [] if isinstance(graph, dict) else []:
            if isinstance(st, dict) and isinstance(st.get("prompt"), str):
                collect(st["prompt"])
                st["prompt"] = render_hints(st["prompt"], custom)
        workflow = {"id": resolved.workflow.id, "revision": rev.number if rev else 0, "graph": graph,
                    "dead_air_enabled": resolved.workflow.dead_air_enabled}

    return {
        "agent_id": agent.id,
        "version": number,
        "name": agent.name,
        "persona_name": agent.persona_name,
        "language": agent.language,
        "voice_id": agent.voice_id,
        "phone_number": agent.phone_number,
        "settings": copy.deepcopy(agent.settings),
        "custom_expressions": dict(custom),
        "script": _rendered_script(agent),
        "variables": found,
        "knowledge": knowledge,
        "workflow": workflow,
    }


def _lock(agent) -> Agent:
    """Inside a transaction: lock the workspace row, then the agent row; return the fresh agent."""
    Workspace.objects.select_for_update().get(pk=agent.workspace_id)
    return Agent.objects.select_for_update().get(pk=agent.pk)


def _sync(target, source):
    target.status = source.status
    target.published_version = source.published_version


def publish(agent: Agent, user) -> AgentVersion:
    with transaction.atomic():
        locked = _lock(agent)
        if locked.status == Agent.ARCHIVED:
            raise PublishError(["Restore this agent before publishing it."])
        resolved = resolve(locked, lock=True)
        errors = validation_errors(locked, resolved)
        if errors:
            raise PublishError(errors)
        others = Agent.objects.select_for_update().filter(
            workspace_id=locked.workspace_id, status=Agent.PUBLISHED
        ).exclude(pk=locked.pk)
        for other in others:
            other.status, other.published_version = Agent.DRAFT, None
            other.save(update_fields=["status", "published_version"])
        last = locked.versions.aggregate(n=Max("number"))["n"] or 0
        version = AgentVersion.objects.create(
            agent=locked, number=last + 1, snapshot=build_snapshot(locked, last + 1, resolved), published_by=user
        )
        locked.status, locked.published_version = Agent.PUBLISHED, version
        locked.save(update_fields=["status", "published_version"])
    _sync(agent, locked)
    return version


def unpublish(agent: Agent) -> Agent:
    with transaction.atomic():
        locked = _lock(agent)
        if locked.status != Agent.PUBLISHED:
            raise StateError("This agent is not published.")
        locked.status, locked.published_version = Agent.DRAFT, None
        locked.save(update_fields=["status", "published_version"])
    _sync(agent, locked)
    return locked


def archive(agent: Agent) -> Agent:
    with transaction.atomic():
        locked = _lock(agent)
        if locked.status == Agent.PUBLISHED:
            raise StateError("Unpublish it first.")
        if locked.status != Agent.ARCHIVED:
            locked.status = Agent.ARCHIVED
            locked.save(update_fields=["status"])
    _sync(agent, locked)
    return locked


def restore(agent: Agent) -> Agent:
    with transaction.atomic():
        locked = _lock(agent)
        if locked.status != Agent.ARCHIVED:
            raise StateError("This agent is not archived.")
        locked.status = Agent.DRAFT
        locked.save(update_fields=["status"])
    _sync(agent, locked)
    return locked


def _fingerprint(agent) -> dict:
    """What callers would hear if `agent` were published now (names of linked items excluded)."""
    resolved = resolve(agent)
    knowledge = [[doc.id, rev.number if rev else 0] for doc, rev in resolved.knowledge]
    workflow = None
    if resolved.workflow is not None:
        rev = resolved.workflow_revision
        workflow = [resolved.workflow.id, rev.number if rev else 0, resolved.workflow.dead_air_enabled]
    return {
        "script": _rendered_script(agent),
        "settings": agent.settings,
        "persona_name": agent.persona_name,
        "language": agent.language,
        "voice_id": agent.voice_id,
        "phone_number": agent.phone_number,
        "custom_expressions": _custom(agent),
        "knowledge": knowledge,
        "workflow": workflow,
    }


def _snapshot_fingerprint(s: dict) -> dict:
    wf = s.get("workflow")
    return {
        "script": s.get("script"),
        "settings": s.get("settings"),
        "persona_name": s.get("persona_name"),
        "language": s.get("language"),
        "voice_id": s.get("voice_id"),
        "phone_number": s.get("phone_number"),
        "custom_expressions": s.get("custom_expressions", {}),
        "knowledge": sorted([k["id"], k["revision"]] for k in s.get("knowledge") or []),
        # Snapshots from before the workflow switch existed had it on.
        "workflow": [wf["id"], wf["revision"], wf.get("dead_air_enabled", True)] if wf else None,
    }


def is_outdated(agent: Agent) -> bool:
    """True when the published agent's current config differs from what callers get."""
    if not agent.published_version_id:
        return False
    return _fingerprint(agent) != _snapshot_fingerprint(agent.published_version.snapshot)
