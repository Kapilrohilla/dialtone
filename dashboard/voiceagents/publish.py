"""Publishing: the only way an agent's configuration reaches callers.

Every status change (publish, unpublish, archive, restore) runs in one transaction that locks the
Workspace row first and then the Agent row(s). The workspace lock serialises publishes so that at
most one agent per workspace is ever published; the partial unique constraint on Agent is a backstop.
"""
import copy

from django.db import transaction
from django.db.models import Max

from knowledge.models import KnowledgeDocument
from workflows.graph import validate
from workspaces.models import Workspace

from .models import Agent, AgentVersion
from .tokens import render_hints, unknown_expressions, variables

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


def validation_errors(agent) -> list[str]:
    errors: list[str] = []
    custom = _custom(agent)
    sections = _sections(agent)
    if not any(body.strip() for _, body in sections):
        errors.append("Write at least one script section before publishing.")
    for title, body in sections:
        for expr in unknown_expressions(body, custom):
            errors.append(f'Section "{title.strip() or "Untitled"}" uses an unknown expression "{expr}".')
    for doc in _linked_docs(agent).filter(archived=True):
        errors.append(f'Knowledge document "{doc.title}" is archived. Remove it from this agent or restore it.')
    if agent.workflow_id and _workflow(agent) is None:
        errors.append("The linked workflow does not exist. Choose another workflow or remove it.")
    wf = _workflow(agent)
    if wf is not None:
        if wf.archived:
            errors.append(f'The workflow "{wf.name}" is archived. Choose another workflow or remove it.')
        else:
            cur = wf.current
            ids = set(
                KnowledgeDocument.objects.filter(workspace_id=agent.workspace_id, archived=False)
                .values_list("id", flat=True)
            )
            errors.extend(validate(cur.graph if cur else EMPTY_GRAPH, ids, custom))
    return errors


def build_snapshot(agent, number: int) -> dict:
    custom = _custom(agent)
    found: list[str] = []

    def collect(text):
        for v in variables(text):
            if v not in found:
                found.append(v)

    for _, body in _sections(agent):
        collect(body)

    knowledge = []
    for doc in _linked_docs(agent).filter(archived=False):
        cur = doc.current
        knowledge.append({
            "id": doc.id, "title": doc.title,
            "revision": cur.number if cur else 0, "body_md": cur.body_md if cur else "",
        })

    workflow = None
    wf = _workflow(agent)
    if wf is not None and not wf.archived:
        cur = wf.current
        graph = copy.deepcopy(cur.graph if cur else EMPTY_GRAPH)
        for st in graph.get("steps") or []:
            if isinstance(st, dict) and isinstance(st.get("prompt"), str):
                collect(st["prompt"])
                st["prompt"] = render_hints(st["prompt"], custom)
        workflow = {"id": wf.id, "revision": cur.number if cur else 0, "graph": graph}

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
        errors = validation_errors(locked)
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
            agent=locked, number=last + 1, snapshot=build_snapshot(locked, last + 1), published_by=user
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
    knowledge = [
        [pk, rev or 0]
        for pk, rev in _linked_docs(agent).filter(archived=False)
        .annotate(rev=Max("revisions__number")).values_list("id", "rev")
    ]
    wf = _workflow(agent)
    workflow = None
    if wf is not None and not wf.archived:
        cur = wf.current
        workflow = [wf.id, cur.number if cur else 0]
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
        "workflow": [wf["id"], wf["revision"]] if wf else None,
    }


def is_outdated(agent: Agent) -> bool:
    """True when the published agent's current config differs from what callers get."""
    if not agent.published_version_id:
        return False
    return _fingerprint(agent) != _snapshot_fingerprint(agent.published_version.snapshot)
