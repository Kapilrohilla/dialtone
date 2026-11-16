from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from calls.numbers import strip_nul
from voiceagents.serializers import display_name
from workspaces.permissions import CanEdit, IsMember, workspace_for

from .lists import NAME_MAX, clean_items
from .models import DispositionList


class WriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=NAME_MAX, required=False, allow_blank=True)
    items = serializers.JSONField(required=False)
    fallback_code = serializers.CharField(max_length=32, required=False, allow_blank=True)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A list name is required.")
        return value

    def validate_items(self, value):
        items, errors = clean_items(strip_nul(value))
        if errors:
            raise serializers.ValidationError(errors)
        return items


def _used_by(lst) -> list[dict]:
    return [{"id": a.id, "name": a.name} for a in lst.agents.exclude(status="archived").order_by("name", "id")]


def row(lst) -> dict:
    return {"id": lst.id, "name": lst.name, "items": lst.items, "fallback_code": lst.fallback_code,
            "used_by": _used_by(lst), "updated_at": lst.updated_at}


def detail(lst) -> dict:
    codes = lst.system_codes
    return {**row(lst), "not_reached_code": codes["not_reached"], "dropped_code": codes["dropped"],
            "updated_by": display_name(lst.updated_by)}


def _apply(lst, data, user, partial: bool):
    """Set validated fields on `lst`; checks the fallback is one of the (new or current) items."""
    if not partial:
        for key, message in (("name", "A list name is required."), ("items", "Add at least one disposition.")):
            if key not in data:
                raise serializers.ValidationError({key: [message]})
    if "name" in data:
        lst.name = data["name"]
    if "items" in data:
        lst.items = data["items"]
    fallback = data.get("fallback_code", lst.fallback_code if partial else "")
    fallback = str(fallback or "").strip().upper()
    if not fallback and not partial:
        # A new list without a fallback falls back to its last item.
        fallback = lst.items[-1]["code"]
    if fallback not in {i["code"] for i in lst.items}:
        raise serializers.ValidationError(
            {"fallback_code": ["Choose the fallback from this list's codes; it is used when the AI's pick "
                               "isn't in the list or the outcome is unclear."]}
        )
    lst.fallback_code = fallback
    lst.updated_by = user


class _Base(APIView):
    def get_permissions(self):
        return [CanEdit()] if self.request.method not in ("GET", "HEAD", "OPTIONS") else [IsMember()]

    def lst(self, pk):
        return get_object_or_404(
            DispositionList.objects.select_related("updated_by"), pk=pk, workspace=workspace_for(self.request)
        )


class DispositionListsView(_Base):
    def get(self, request):
        qs = DispositionList.objects.filter(workspace=workspace_for(request)).prefetch_related("agents")
        return Response([row(lst) for lst in qs])

    def post(self, request):
        s = WriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        lst = DispositionList(workspace=workspace_for(request))
        _apply(lst, s.validated_data, request.user, partial=False)
        lst.save()
        return Response(detail(lst), status=status.HTTP_201_CREATED)


class DispositionListView(_Base):
    def get(self, request, pk):
        return Response(detail(self.lst(pk)))

    def patch(self, request, pk):
        s = WriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            lst = DispositionList.objects.select_for_update().get(pk=self.lst(pk).pk)
            _apply(lst, s.validated_data, request.user, partial=True)
            lst.save()
        return Response(detail(self.lst(pk)))

    def delete(self, request, pk):
        """Refused while an agent (other than an archived one) uses the list. Published versions keep
        their own copy of the list, so deleting never changes a live call."""
        lst = self.lst(pk)
        used = _used_by(lst)
        if used:
            names = ", ".join(a["name"] for a in used)
            return Response({"detail": f"Detach this list from {names} first."}, status=status.HTTP_409_CONFLICT)
        lst.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DispositionListDuplicateView(_Base):
    def post(self, request, pk):
        src = self.lst(pk)
        copy_ = DispositionList.objects.create(
            workspace=src.workspace, name=f"Copy of {src.name}"[:NAME_MAX], items=src.items,
            fallback_code=src.fallback_code, updated_by=request.user,
        )
        return Response(detail(copy_), status=status.HTTP_201_CREATED)
