"""Did the audit fixes help? (KAP-37)

``record_included`` runs inside publish: the accepted audit fixes not yet in any version are recorded as part of the
new one. ``versions_payload`` gives each version its fixes and its average audit scores, and compares them with the
version before once both have at least AUDIT_FIX_MIN_CALLS_FOR_SCORES audited calls.
"""
from collections import defaultdict

from django.conf import settings

from voiceagents.serializers import display_name
from workflows.models import WorkflowSuggestion

from .models import AgentSuggestion, CallAudit
from .rubric import AREA_KEYS


def record_included(agent, version, workflow_revision) -> None:
    """Called by ``publish`` in its transaction, after the new version exists."""
    AgentSuggestion.objects.filter(agent=agent, status=AgentSuggestion.ACCEPTED, included_in__isnull=True) \
        .update(included_in=version)
    if workflow_revision is not None:
        WorkflowSuggestion.objects.filter(
            suggestion_set__audit_run__agent=agent, status=WorkflowSuggestion.ACCEPTED, included_in__isnull=True,
            applied_revision__workflow_id=workflow_revision.workflow_id,
            applied_revision__number__lte=workflow_revision.number,
        ).update(included_in=version)


def fix_summary(item) -> dict:
    meta = item.audit or {}
    return {"id": item.id, "target": "agent" if isinstance(item, AgentSuggestion) else "workflow", "kind": item.kind,
            "title": meta.get("title", ""), "area": meta.get("area", ""), "auto_applied": item.auto_applied}


def _avg(values) -> float | None:
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 1) if values else None


def scores_by_version(agent) -> dict[int, dict]:
    """{version_id: {"calls", "overall", "areas": {area: average 1-5}}} over the current ready audits."""
    rows = CallAudit.objects.filter(agent_version__agent=agent, is_current=True, status=CallAudit.READY) \
        .values_list("agent_version_id", "overall_score", "scores")
    grouped: dict[int, list] = defaultdict(list)
    for vid, overall, scores in rows:
        grouped[vid].append((overall, scores if isinstance(scores, dict) else {}))
    out = {}
    for vid, items in grouped.items():
        out[vid] = {
            "calls": len(items),
            "overall": _avg(o for o, _ in items),
            "areas": {k: _avg((s.get(k) or {}).get("score") if isinstance(s.get(k), dict) else None
                              for _, s in items) for k in AREA_KEYS},
        }
    return out


def _delta(a, b):
    return round(a - b, 1) if a is not None and b is not None else None


def versions_payload(agent) -> list[dict]:
    """GET /api/agents/<id>/versions: every version, newest first, with its audit fixes and scores."""
    versions = list(agent.versions.select_related("published_by").order_by("-number"))
    scores = scores_by_version(agent)
    fixes: dict[int, list] = defaultdict(list)
    for item in AgentSuggestion.objects.filter(agent=agent, included_in__isnull=False):
        fixes[item.included_in_id].append(item)
    for item in WorkflowSuggestion.objects.filter(suggestion_set__audit_run__agent=agent, included_in__isnull=False):
        fixes[item.included_in_id].append(item)
    need = settings.AUDIT_FIX_MIN_CALLS_FOR_SCORES
    empty = {"calls": 0, "overall": None, "areas": {k: None for k in AREA_KEYS}}
    out = []
    for i, v in enumerate(versions):
        mine = scores.get(v.id, empty)
        prev = versions[i + 1] if i + 1 < len(versions) else None
        theirs = scores.get(prev.id, empty) if prev else None
        comparison = None
        if prev is not None:
            enough = mine["calls"] >= need and theirs["calls"] >= need
            comparison = {
                "version": prev.number,
                "enough": enough,
                "scores": theirs,
                "change": {
                    "overall": _delta(mine["overall"], theirs["overall"]),
                    "areas": {k: _delta(mine["areas"][k], theirs["areas"][k]) for k in AREA_KEYS},
                } if enough else None,
            }
        items = sorted(fixes.get(v.id, []), key=lambda x: -(x.audit or {}).get("rank_score", 0))
        out.append({
            "number": v.number,
            "published_by_name": display_name(v.published_by),
            "published_at": v.published_at,
            "audit_fixes": [fix_summary(x) for x in items],
            "audit_scores": mine,
            "compared_to": comparison,
            "min_calls": need,
        })
    return out
