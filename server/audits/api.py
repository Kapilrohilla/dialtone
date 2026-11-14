"""Console API for call audits: read a call's current audit, and run (or re-run) one."""
from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from calls.api import _Base, calls_of
from workspaces.permissions import workspace_for

from . import run as runner
from .models import CallAudit
from .rubric import AREAS, weights_for

SKIP_LABELS = dict(CallAudit.SKIP_REASONS)


def current_audit(call) -> CallAudit | None:
    return CallAudit.objects.filter(call=call, is_current=True).first()


def audit_payload(audit: CallAudit | None, workspace) -> dict:
    if audit is None:
        return {"status": "none", "enabled": workspace.audit_enabled}
    weights = audit.weights or weights_for(workspace)
    scores = audit.scores if isinstance(audit.scores, dict) else {}
    areas = []
    for key, label, *_ in AREAS:
        s = scores.get(key) if isinstance(scores.get(key), dict) else {}
        areas.append({"key": key, "label": label, "weight": weights.get(key, 0), "score": s.get("score"),
                      "summary": s.get("summary") or "", "evidence": s.get("evidence") or []})
    return {
        "id": audit.id,
        "status": audit.status,
        "enabled": workspace.audit_enabled,
        "error": audit.error,
        "skipped_reason": audit.skipped_reason,
        "skipped_label": SKIP_LABELS.get(audit.skipped_reason, ""),
        "overall_score": audit.overall_score,
        "summary": audit.summary,
        "areas": areas if audit.status == CallAudit.READY else [],
        "moments": audit.moments if audit.status == CallAudit.READY else [],
        "rubric_version": audit.rubric_version,
        "model": audit.model,
        "used_audio": audit.used_audio,
        "quotes_purged": audit.quotes_purged,
        "automatic": audit.created_by_id is None,
        "created_at": audit.created_at,
        "finished_at": audit.finished_at,
    }


class CallAuditView(_Base):
    """GET: the call's current audit, or {"status": "none"}. POST (editors): audit the call now, or re-audit."""

    def get(self, request, room):
        call = get_object_or_404(calls_of(request), room=room)
        audit = current_audit(call)
        if audit is not None and audit.status in CallAudit.ACTIVE and runner.revive(audit):
            audit.refresh_from_db()
        return Response(audit_payload(audit, workspace_for(request)))

    def post(self, request, room):
        call = get_object_or_404(calls_of(request), room=room)
        try:
            audit = runner.create(call, request.user)
        except runner.Busy:
            return Response({"detail": "This call is being audited. Wait for it to finish."}, status=409)
        runner.start(audit.pk)
        audit.refresh_from_db()
        return Response(audit_payload(audit, workspace_for(request)), status=202)
