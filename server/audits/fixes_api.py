"""Console API for audit fixes (KAP-37): start a "Suggest fixes" run from one call or from an agent's recent calls,
read it, and accept, edit or dismiss its fixes. Reads need membership, writes need an editor.

Accepting writes to the draft only (``apply.py``): callers keep the published version until someone publishes.
"""
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from calls.api import calls_of
from voiceagents.models import Agent
from voiceagents.serializers import display_name
from voiceagents.webcall import web_room_agent_id
from voiceagents.suggestions import validate_agent_item
from workflows.models import WorkflowSuggestion, WorkflowSuggestionSet
from workflows.suggest import custom_expressions_for
from workflows.suggestions import Invalid, validate_item
from workspaces.permissions import CanEdit, IsMember, workspace_for

from . import fixes as gen
from .api import current_audit
from .apply import ApplyError, apply_agent_item, apply_workflow_item
from .models import AgentSuggestion, AuditFixRun, CallAudit
from .rubric import LABELS
from .run import _workflow_revision

Run = AuditFixRun
NOT_USED = "The agent no longer uses this workflow."


class _Base(APIView):
    def get_permissions(self):
        return [CanEdit()] if self.request.method not in ("GET", "HEAD", "OPTIONS") else [IsMember()]

    def run(self, run_id) -> Run:
        return get_object_or_404(Run.objects.select_related("agent", "call", "created_by", "agent_version"),
                                 pk=run_id, workspace=workspace_for(self.request))


class BatchSerializer(serializers.Serializer):
    by = serializers.ChoiceField(choices=["version", "workflow_revision"], default="version")
    limit = serializers.IntegerField(min_value=1, max_value=gen.MAX_POOL, default=gen.DEFAULT_POOL)


class PatchSerializer(serializers.Serializer):
    edited_payload = serializers.DictField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=["pending", "dismissed"], required=False)


# -- reading -----------------------------------------------------------------------------------------

def _check(item, workflow_graph, workflow_custom, agent) -> str:
    """Why a pending fix can't be accepted against the current draft, or ""."""
    try:
        if isinstance(item, AgentSuggestion):
            validate_agent_item(item.kind, item.effective_payload, agent)
        elif workflow_graph is None:
            return "The workflow was removed or archived."
        elif agent.workflow_id != item.suggestion_set.workflow_id:
            return NOT_USED
        else:
            validate_item(item.kind, item.effective_payload, workflow_graph, item.step_id, workflow_custom)
    except Invalid as e:
        return e.reason
    return ""


def _step_names(graph) -> dict[str, str]:
    steps = graph.get("steps") if isinstance(graph, dict) else None
    return {s["id"]: s.get("name") or s["id"] for s in steps or []
            if isinstance(s, dict) and isinstance(s.get("id"), str)}


def serialize_run(run: Run) -> dict:
    """The run with its fixes ranked, each re-checked against the current draft (``invalid_reason``)."""
    run = gen.expire_if_stuck(run)
    agent = Agent.objects.get(pk=run.agent_id)
    wset = WorkflowSuggestionSet.objects.filter(audit_run=run).select_related("workflow").first()
    wf = wset.workflow if wset is not None else None
    cur = wf.current if wf is not None and not wf.archived else None
    graph = cur.graph if cur is not None else None
    custom = custom_expressions_for(wf) if wf is not None else {}
    names = _step_names(graph or (wset.base_revision.graph if wset is not None else {}))
    items = gen.ranked_items(run)
    audit_ids = {e.get("audit_id") for i in items for e in (i.audit or {}).get("evidence", [])}
    purged = set(CallAudit.objects.filter(pk__in=audit_ids, quotes_purged=True).values_list("pk", flat=True))
    out, changed = [], {WorkflowSuggestion: [], AgentSuggestion: []}
    for item in items:
        reason = ""
        if item.status == item.PENDING:
            reason = _check(item, graph, custom, agent)
            if reason != item.invalid_reason:
                item.invalid_reason = reason
                changed[type(item)].append(item)
        meta = item.audit or {}
        is_wf = isinstance(item, WorkflowSuggestion)
        out.append({
            "id": item.id,
            "target": "workflow" if is_wf else "agent",
            "kind": item.kind,
            "step_id": item.step_id if is_wf else "",
            "step_name": names.get(item.step_id, "") if is_wf else "",
            "payload": item.effective_payload,
            "edited": item.edited_payload is not None,
            "status": item.status,
            "invalid_reason": reason,
            "auto_applied": item.auto_applied,
            "applied_revision": item.applied_revision.number if is_wf and item.applied_revision_id else None,
            "title": meta.get("title", ""),
            "area": meta.get("area", ""),
            "area_label": LABELS.get(meta.get("area"), ""),
            "calls": meta.get("calls", 0),
            "pool": meta.get("pool", 0),
            "score_cost": meta.get("score_cost", 0),
            "rank_score": meta.get("rank_score", 0),
            "confidence": meta.get("confidence", 0),
            # Quotes purged after the run was made stay hidden.
            "evidence": [{**e, "quote": ""} if e.get("audit_id") in purged else e for e in meta.get("evidence", [])],
        })
    for model, rows in changed.items():
        if rows:
            model.objects.bulk_update(rows, ["invalid_reason"])
    return {
        "id": run.id,
        "status": run.status,
        "scope": run.scope,
        "error": run.error,
        "call": run.call.room if run.call_id else None,
        "agent": {"id": agent.id, "name": agent.name},
        "agent_version": run.agent_version.number if run.agent_version_id else None,
        "workflow": {"id": wf.id, "name": wf.name} if wf is not None else None,
        "calls": len(run.audit_ids),
        "dropped": run.dropped,
        "auto_applied": run.auto_applied,
        "created_by": {"id": run.created_by_id, "name": display_name(run.created_by)} if run.created_by else None,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "items": out,
    }


# -- starting ----------------------------------------------------------------------------------------

def _start(request, agent, version, audits, scope, call=None) -> Response:
    ws = workspace_for(request)
    with transaction.atomic():
        # Serialise starts per workspace so two clicks can't both slip under the daily cap.
        type(ws).objects.select_for_update().get(pk=ws.pk)
        if gen.runs_today(ws) >= settings.AUDIT_FIX_DAILY_LIMIT:
            return Response({"detail": "Daily limit reached"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        run = Run.objects.create(
            workspace=ws, agent=agent, agent_version=version, workflow_revision=_workflow_revision(version),
            call=call, scope=scope, audit_ids=[a.id for a in audits], model=settings.AUDIT_LLM_MODEL,
            created_by=request.user,
        )
    transaction.on_commit(lambda: gen.start(run.id))
    run = Run.objects.select_related("agent", "call", "created_by", "agent_version").get(pk=run.pk)
    return Response(serialize_run(run), status=status.HTTP_202_ACCEPTED)


def _older(version) -> str:
    latest = version.agent.versions.order_by("-number").first()
    if latest is not None and latest.number != version.number:
        return (f"This call ran on v{version.number}, but v{latest.number} is the latest version; its problems may "
                f"be fixed already. Suggest fixes from a call on v{latest.number}.")
    return ""


def _web_test_agent(call) -> Agent | None:
    """The agent whose draft a voice test call talked to, or None (not a voice test, or the agent is gone)."""
    agent_id = web_room_agent_id(call.room)
    if agent_id is None or call.workspace_id is None:
        return None
    return Agent.objects.exclude(status=Agent.ARCHIVED).filter(pk=agent_id, workspace_id=call.workspace_id).first()


class CallFixesView(_Base):
    """GET: the call's latest run, or 204. POST: "Suggest fixes" for this call's audit."""

    def get(self, request, room):
        call = get_object_or_404(calls_of(request), room=room)
        run = Run.objects.filter(workspace=workspace_for(request), call=call, scope=Run.CALL).first()
        if run is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(serialize_run(run))

    def post(self, request, room):
        call = get_object_or_404(calls_of(request).select_related("agent_version__agent"), room=room)
        audit = current_audit(call)
        if audit is None or audit.status != CallAudit.READY:
            return Response({"detail": "Audit this call first."}, status=409)
        version = call.agent_version
        if version is None:
            # A voice test (`web-…` room) talked to the agent's draft, which is what fixes change anyway.
            agent = _web_test_agent(call)
            if agent is None:
                return Response({"detail": "This call didn't run on a published agent."}, status=409)
        elif version.agent.workspace_id != call.workspace_id:
            return Response({"detail": "This call didn't run on a published agent."}, status=409)
        else:
            agent = version.agent
            older = _older(version)
            if older:
                return Response({"detail": older}, status=409)
        if not gen.problems_of([audit]):
            return Response({"detail": "This audit found no problems to fix."}, status=409)
        return _start(request, agent, version, [audit], Run.CALL, call)


class AgentFixesView(_Base):
    """GET: the agent's latest run over recent calls, or 204. POST: start one over the last N audited calls of the
    latest version (``by: "version"``) or of the workflow revision it uses (``by: "workflow_revision"``)."""

    def agent(self, pk) -> Agent:
        return get_object_or_404(Agent, pk=pk, workspace=workspace_for(self.request))

    def get(self, request, pk):
        agent = self.agent(pk)
        run = Run.objects.filter(agent=agent, scope=Run.BATCH).first()
        if run is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(serialize_run(run))

    def post(self, request, pk):
        agent = self.agent(pk)
        s = BatchSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        by, limit = s.validated_data["by"], s.validated_data["limit"]
        # Only the latest version's calls: older versions' problems may be fixed already.
        version = agent.versions.order_by("-number").first()
        if version is None:
            return Response({"detail": "Publish this agent first: fixes come from its audited calls."}, status=409)
        if by == "version":
            audits = gen.pool_for_version(version, limit)
            where = f"v{version.number}"
        else:
            rev = _workflow_revision(version)
            if rev is None:
                return Response({"detail": f"v{version.number} doesn't use a workflow."}, status=409)
            audits = gen.pool_for_revision(agent, rev, limit)
            where = f"workflow revision {rev.number}"
        if not audits:
            return Response({"detail": f"No audited calls on {where} yet."}, status=409)
        if not gen.problems_of(audits):
            return Response({"detail": f"The audits of the last {len(audits)} calls found no problems to fix."},
                            status=409)
        return _start(request, agent, version, audits, Run.BATCH)


class FixRunView(_Base):
    def get(self, request, run_id):
        return Response(serialize_run(self.run(run_id)))


def _item(run: Run, target: str, item_id: int):
    """``target`` is "agent" or "workflow" (the URL allows nothing else)."""
    if target == "agent":
        return get_object_or_404(AgentSuggestion, pk=item_id, run=run)
    return get_object_or_404(WorkflowSuggestion.objects.select_related("suggestion_set__workflow"), pk=item_id,
                             suggestion_set__audit_run=run)


class FixItemView(_Base):
    """PATCH: save an edit (``edited_payload``, validated like the original) or dismiss / restore a fix."""

    def patch(self, request, run_id, target, item_id):
        run = self.run(run_id)
        ser = PatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        with transaction.atomic():
            # Locked, and only the edited fields saved: an accept (or auto-apply, or a purge) landing meanwhile
            # must not be undone.
            item = _item(run, target, item_id)
            item = type(item).objects.select_for_update().get(pk=item.pk)
            if item.status == item.ACCEPTED:
                return Response({"detail": "This fix was already accepted."}, status=409)
            if "edited_payload" in data:
                edited = data["edited_payload"]
                if edited is not None:
                    try:
                        if isinstance(item, AgentSuggestion):
                            edited = validate_agent_item(item.kind, edited, Agent.objects.get(pk=item.agent_id))
                        else:
                            wf = item.suggestion_set.workflow
                            cur = wf.current
                            if cur is None or wf.archived:
                                return Response({"detail": "The workflow was removed or archived."}, status=409)
                            edited = validate_item(item.kind, edited, cur.graph, item.step_id,
                                                   custom_expressions_for(wf))
                    except Invalid as e:
                        return Response({e.field: [e.reason]}, status=400)
                item.edited_payload = edited
            if "status" in data:
                dismissed = data["status"] == "dismissed"
                item.status = data["status"]
                item.decided_by = request.user if dismissed else None
                item.decided_at = timezone.now() if dismissed else None
            item.save(update_fields=["edited_payload", "status", "decided_by", "decided_at"])
        return Response(serialize_run(self.run(run_id)))


class AcceptFixView(_Base):
    """POST: accept a fix. Writes to the draft (a new workflow revision, or the agent); never publishes."""

    def post(self, request, run_id, target, item_id):
        run = self.run(run_id)
        item = _item(run, target, item_id)
        try:
            if isinstance(item, AgentSuggestion):
                apply_agent_item(item, request.user)
            else:
                apply_workflow_item(item, request.user)
        except ApplyError as e:
            return Response({e.field: e.reason}, status=e.status)
        return Response(serialize_run(self.run(run_id)))
