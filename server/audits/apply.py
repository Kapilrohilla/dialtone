"""Accepting an audit fix (KAP-37): writes the change to the draft, never to what callers hear.

A workflow fix saves a new workflow revision (the editor's Save does the same); an agent fix changes the agent row.
Either way callers keep the published ``AgentVersion`` until someone publishes (``voiceagents/publish.py``). Every
fix is checked again against the current draft first, so an out-of-date fix is refused, not half-applied.
"""
import copy
import re

from django.db import transaction
from django.utils import timezone

from knowledge.models import KnowledgeDocument, KnowledgeRevision
from voiceagents.models import Agent
from voiceagents.suggestions import validate_agent_item
from workflows.models import Workflow, WorkflowRevision, WorkflowSuggestion
from workflows.suggest import custom_expressions_for
from workflows.suggestions import Invalid, validate_item

from .models import AgentSuggestion

NEW_STEP_GAP_Y = 220  # the console's addStep puts a new step this far below its anchor
NODE_GAP_X = 280


class ApplyError(Exception):
    """The fix can't be accepted; ``reason`` is user-facing, ``field`` names the payload field (edits only)."""

    def __init__(self, reason: str, field: str = "detail", status: int = 409):
        super().__init__(reason)
        self.reason, self.field, self.status = reason, field, status


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "step"


def _unique(base: str, taken: set[str]) -> str:
    n = 1
    while f"{base}-fix{n}" in taken:
        n += 1
    out = f"{base}-fix{n}"
    taken.add(out)
    return out


# -- workflow ----------------------------------------------------------------------------------------

def apply_to_graph(graph: dict, kind: str, step_id: str, payload: dict) -> dict:
    """A copy of ``graph`` with a validated fix applied."""
    g = copy.deepcopy(graph) if isinstance(graph, dict) else {"steps": [], "paths": []}
    steps = g.setdefault("steps", [])
    paths = g.setdefault("paths", [])
    if kind in (WorkflowSuggestion.EXPRESSION, WorkflowSuggestion.PROMPT):
        for s in steps:
            if isinstance(s, dict) and s.get("id") == step_id:
                s["prompt"] = payload["after"]
                break
        return g
    step_ids = {s.get("id") for s in steps if isinstance(s, dict)}
    path_ids = {p.get("id") for p in paths if isinstance(p, dict) and isinstance(p.get("id"), str)}
    target = payload["target"]
    if "step_id" in target:
        to = target["step_id"]
    else:
        new = target["new_step"]
        source = next((s for s in steps if isinstance(s, dict) and s.get("id") == step_id), {})
        at = source.get("position") if isinstance(source.get("position"), dict) else {"x": 0, "y": 0}
        y = (at.get("y") or 0) + NEW_STEP_GAP_Y
        siblings = sum(1 for s in steps if isinstance(s, dict) and isinstance(s.get("position"), dict)
                       and s["position"].get("y") == y)
        to = _unique(_slug(new["name"]), step_ids)
        step = {"id": to, "type": new["type"], "name": new["name"], "prompt": new.get("prompt") or "",
                "position": {"x": (at.get("x") or 0) + siblings * NODE_GAP_X, "y": y}}
        if new["type"] == "end":
            step["outcome"] = new["outcome"]
        steps.append(step)
        if new["type"] == "prompt":
            then = new["then"]
            paths.append({"id": _unique("path", path_ids), "from": to, "to": then["step_id"], "label": then["label"]})
    paths.append({"id": _unique("path", path_ids), "from": step_id, "to": to, "label": payload["label"],
                  "examples": payload["examples"]})
    return g


def apply_workflow_item(item: WorkflowSuggestion, user, auto: bool = False) -> WorkflowRevision:
    with transaction.atomic():
        item = WorkflowSuggestion.objects.select_for_update(of=("self",)).select_related(
            "suggestion_set__audit_run").get(pk=item.pk)
        # Lock the workflow so a concurrent Save can't take the same revision number.
        wf = Workflow.objects.select_for_update().get(pk=item.suggestion_set.workflow_id)
        if item.status != WorkflowSuggestion.PENDING:
            raise ApplyError("This fix was already decided.")
        if wf.archived:
            raise ApplyError("The workflow is archived.")
        run = item.suggestion_set.audit_run
        if run is not None and Agent.objects.filter(pk=run.agent_id, workflow_id=wf.id).count() == 0:
            # Workflows can be shared: never edit one the fixed agent has moved away from.
            raise ApplyError("The agent no longer uses this workflow.")
        cur = wf.current
        if cur is None:
            raise ApplyError("Save the workflow first.")
        try:
            payload = validate_item(item.kind, item.effective_payload, cur.graph, item.step_id,
                                    custom_expressions_for(wf))
        except Invalid as e:
            raise ApplyError(e.reason) from e
        graph = apply_to_graph(cur.graph, item.kind, item.step_id, payload)
        rev = WorkflowRevision.objects.create(workflow=wf, number=cur.number + 1, graph=graph, saved_by=user)
        wf.save()  # bumps updated_at
        item.status, item.decided_by, item.decided_at = WorkflowSuggestion.ACCEPTED, user, timezone.now()
        item.applied_revision, item.auto_applied = rev, auto
        item.save(update_fields=["status", "decided_by", "decided_at", "applied_revision", "auto_applied"])
    return rev


# -- agent -------------------------------------------------------------------------------------------

def apply_agent_item(item: AgentSuggestion, user, auto: bool = False) -> Agent:
    with transaction.atomic():
        item = AgentSuggestion.objects.select_for_update().get(pk=item.pk)
        agent = Agent.objects.select_for_update().get(pk=item.agent_id)
        if item.status != AgentSuggestion.PENDING:
            raise ApplyError("This fix was already decided.")
        if agent.status == Agent.ARCHIVED:
            raise ApplyError("The agent is archived. Restore it first.")
        try:
            payload = validate_agent_item(item.kind, item.effective_payload, agent)
        except Invalid as e:
            raise ApplyError(e.reason) from e
        fields = ["updated_by", "updated_at"]
        if item.kind == AgentSuggestion.SCRIPT:
            agent.script = [{**s, "body": payload["after"]} if isinstance(s, dict) and s.get("id") ==
                            payload["section_id"] else s for s in agent.script]
            fields.append("script")
        elif item.kind == AgentSuggestion.KNOWLEDGE:
            doc = KnowledgeDocument.objects.create(workspace_id=agent.workspace_id, title=payload["title"])
            KnowledgeRevision.objects.create(document=doc, number=1, body_md=payload["body"], edited_by=user)
            agent.knowledge.add(doc)
        else:
            settings = dict(agent.settings) if isinstance(agent.settings, dict) else {}
            for key, value in payload["changes"].items():
                if key in ("language", "persona_name"):
                    setattr(agent, key, value)
                    fields.append(key)
                elif key == "mood_adaptation":
                    settings[key] = value
                elif value:
                    settings[key] = value
                else:
                    settings.pop(key, None)
            agent.settings = settings
            fields.append("settings")
        agent.updated_by = user
        agent.save(update_fields=fields)
        item.status, item.decided_by, item.decided_at = AgentSuggestion.ACCEPTED, user, timezone.now()
        item.auto_applied = auto
        item.save(update_fields=["status", "decided_by", "decided_at", "auto_applied"])
    return agent
