"""/api/workflows/<id>/suggestions: start a "Suggest with AI" run, read the open draft, edit, dismiss or discard it.

Accepting happens in the browser (on the unsaved graph); Save sends ``accepted_suggestions`` with the graph
(``api.WorkflowDetailView``). Reads need membership, writes need an editor.
"""
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response

from voiceagents.serializers import display_name

from . import suggest
from .api import _Base
from .models import Workflow, WorkflowSuggestion, WorkflowSuggestionSet
from .suggestions import Invalid, fingerprint, validate_item

Set, Item = WorkflowSuggestionSet, WorkflowSuggestion
EMPTY_GRAPH = {"steps": [], "paths": []}


class StartSerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=[Set.STEP, Set.WORKFLOW])
    step_id = serializers.CharField(required=False, allow_blank=True, max_length=200)
    kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=["answers", "expressions"]), min_length=1, max_length=2)


class PatchSerializer(serializers.Serializer):
    edited_payload = serializers.DictField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=[Item.PENDING, Item.DISMISSED], required=False)


def open_set(workflow):
    return workflow.suggestion_sets.filter(source=Set.AI).exclude(status=Set.CLOSED) \
        .select_related("created_by", "base_revision").first()


def _taken_labels(items, item) -> list[str]:
    """Labels of the other pending answers from the same step: two drafts can't share a name either."""
    return [
        o.effective_payload.get("label", "") for o in items
        if o.pk != item.pk and o.kind == Item.ANSWER and o.status == Item.PENDING and o.step_id == item.step_id
        and isinstance(o.effective_payload, dict)
    ]


def serialize_set(s: Set, workflow) -> dict:
    """The set with each item checked against the current revision: ``invalid_reason`` and ``stale``."""
    cur = workflow.current
    graph = cur.graph if cur else EMPTY_GRAPH
    custom = suggest.custom_expressions_for(workflow)
    items = list(s.items.all())
    prints: dict[str, str] = {}
    changed = []
    out = []
    for item in items:
        if item.step_id not in prints:
            prints[item.step_id] = fingerprint(graph, item.step_id)
        stale = s.step_fingerprints.get(item.step_id) != prints[item.step_id]
        reason = ""
        if item.status == Item.PENDING:
            try:
                validate_item(item.kind, item.effective_payload, graph, item.step_id, custom, _taken_labels(items, item))
            except Invalid as e:
                reason = e.reason
            if reason != item.invalid_reason:
                item.invalid_reason = reason
                changed.append(item)
        out.append({
            "id": item.id,
            "kind": item.kind,
            "step_id": item.step_id,
            "payload": item.effective_payload,
            "edited": item.edited_payload is not None,
            "status": item.status,
            "invalid_reason": reason,
            "stale": stale,
        })
    if changed:
        Item.objects.bulk_update(changed, ["invalid_reason"])
    return {
        "id": s.id,
        "status": s.status,
        "scope": s.scope,
        "kinds": s.kinds,
        "step_ids": s.step_ids,
        "total_steps": s.total_steps,
        "failed_step_ids": s.failed_step_ids,
        "error": s.error,
        "base_revision": s.base_revision.number,
        "created_by": {"id": s.created_by_id, "name": display_name(s.created_by)} if s.created_by else None,
        "created_at": s.created_at,
        "finished_at": s.finished_at,
        "items": out,
    }


def runs_today(workspace) -> int:
    """Runs the workspace started today (TIME_ZONE); failed runs don't count, even once a newer run closed them."""
    return Set.objects.filter(
        workflow__workspace=workspace, source=Set.AI, created_at__date=timezone.localdate()
    ).exclude(status=Set.ERROR).exclude(error__gt="").count()


def close(s: Set, user) -> None:
    now = timezone.now()
    s.items.filter(status=Item.PENDING).update(status=Item.DISMISSED, decided_by=user, decided_at=now)
    Set.objects.filter(pk=s.pk).exclude(status=Set.CLOSED).update(status=Set.CLOSED, closed_at=now)


class SuggestionsView(_Base):
    """POST: start a run. Returns 202 with the running set; generation continues in the background."""

    def post(self, request, pk):
        wf = self.workflow(pk)
        s = StartSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        with transaction.atomic():
            wf = Workflow.objects.select_for_update().get(pk=wf.pk)
            cur = wf.current
            if cur is None:
                return Response({"detail": "Save the workflow before asking for suggestions."}, status=400)
            step_id = data.get("step_id") or None
            if data["scope"] == Set.STEP:
                ids = {st.get("id") for st in cur.graph.get("steps", []) if isinstance(st, dict)} \
                    if isinstance(cur.graph, dict) and isinstance(cur.graph.get("steps"), list) else set()
                if not step_id or step_id not in ids:
                    return Response({"step_id": ["Save the workflow with this step first."]}, status=400)
            if runs_today(wf.workspace) >= settings.SUGGEST_DAILY_LIMIT:
                return Response({"detail": "Daily limit reached"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            kinds = [k for k in ("answers", "expressions") if k in data["kinds"]]
            step_ids, total = suggest.steps_to_check(cur.graph, data["scope"], step_id, kinds)
            for old in wf.suggestion_sets.filter(source=Set.AI).exclude(status=Set.CLOSED):
                # One open set per workflow: its pending items stay pending in the closed set, out of sight.
                Set.objects.filter(pk=old.pk).update(status=Set.CLOSED, closed_at=timezone.now())
            run = Set.objects.create(
                workflow=wf, base_revision=cur, scope=data["scope"], kinds=kinds,
                step_ids=step_ids, total_steps=total,
                step_fingerprints={sid: fingerprint(cur.graph, sid) for sid in step_ids},
                model=settings.SUGGEST_LLM_MODEL, created_by=request.user,
            )
        transaction.on_commit(lambda: suggest.start(run.id))
        run = Set.objects.select_related("created_by", "base_revision").get(pk=run.pk)
        return Response(serialize_set(run, wf), status=status.HTTP_202_ACCEPTED)


class CurrentSuggestionsView(_Base):
    """GET: the open set with its items, or 204 when there is none."""

    def get(self, request, pk):
        wf = self.workflow(pk)
        s = open_set(wf)
        if s is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        s = suggest.expire_if_stuck(s)
        return Response(serialize_set(s, wf))


class SuggestionItemView(_Base):
    """PATCH: save an edit (``edited_payload``) or dismiss / restore an item of the open set."""

    def patch(self, request, pk, item_id):
        wf = self.workflow(pk)
        item = get_object_or_404(
            Item.objects.select_related("suggestion_set"), pk=item_id, suggestion_set__workflow=wf,
            suggestion_set__source=Set.AI)
        s = item.suggestion_set
        if s.status == Set.CLOSED:
            return Response({"detail": "These suggestions were discarded."}, status=409)
        ser = PatchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if item.status == Item.ACCEPTED:
            return Response({"detail": "This suggestion was already accepted."}, status=409)
        if "edited_payload" in data:
            edited = data["edited_payload"]
            if edited is not None:
                cur = wf.current
                graph = cur.graph if cur else EMPTY_GRAPH
                siblings = list(s.items.all())
                try:
                    edited = validate_item(item.kind, edited, graph, item.step_id,
                                           suggest.custom_expressions_for(wf), _taken_labels(siblings, item))
                except Invalid as e:
                    return Response({e.field: [e.reason]}, status=400)
            item.edited_payload = edited
        if "status" in data:
            item.status = data["status"]
            item.decided_by = request.user if data["status"] == Item.DISMISSED else None
            item.decided_at = timezone.now() if data["status"] == Item.DISMISSED else None
        item.save()
        s = Set.objects.select_related("created_by", "base_revision").get(pk=s.pk)
        return Response(serialize_set(s, wf))


class CloseSuggestionsView(_Base):
    """POST: "Discard all" / "Discard draft". Pending items are dismissed and the set is closed."""

    def post(self, request, pk, set_id):
        wf = self.workflow(pk)
        s = get_object_or_404(Set, pk=set_id, workflow=wf, source=Set.AI)
        close(s, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def accept_on_save(workflow, item_ids, user) -> None:
    """Called by Save inside its transaction: the listed pending items become accepted. A set left with no pending
    items is closed."""
    ids = [i for i in item_ids if isinstance(i, int)]
    if not ids:
        return
    now = timezone.now()
    items = Item.objects.filter(
        pk__in=ids, status=Item.PENDING, suggestion_set__workflow=workflow, suggestion_set__source=Set.AI
    ).exclude(suggestion_set__status=Set.CLOSED)
    set_ids = set(items.values_list("suggestion_set_id", flat=True))
    items.update(status=Item.ACCEPTED, decided_by=user, decided_at=now)
    for sid in set_ids:
        if not Item.objects.filter(suggestion_set_id=sid, status=Item.PENDING).exists():
            Set.objects.filter(pk=sid).exclude(status=Set.CLOSED).update(status=Set.CLOSED, closed_at=now)
