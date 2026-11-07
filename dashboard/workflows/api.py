from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from knowledge.models import KnowledgeDocument
from workspaces.permissions import CanEdit, IsMember, workspace_for

from .graph import validate
from .models import Workflow, WorkflowRevision
from .serializers import WorkflowListSerializer, WorkflowWriteSerializer

EMPTY_GRAPH = {"steps": [], "paths": []}


def validate_for(workflow, graph, custom_expressions=None):
    ids = set(
        KnowledgeDocument.objects.filter(workspace=workflow.workspace, archived=False).values_list("id", flat=True)
    )
    return validate(graph, ids, custom_expressions)


def detail(workflow):
    cur = workflow.current
    graph = cur.graph if cur else EMPTY_GRAPH
    return {
        "id": workflow.id,
        "name": workflow.name,
        "updated_at": workflow.updated_at,
        "current_revision": cur.number if cur else 0,
        "dead_air_enabled": workflow.dead_air_enabled,
        "graph": graph,
        "errors": validate_for(workflow, graph),
    }


class _Base(APIView):
    def get_permissions(self):
        return [CanEdit()] if self.request.method not in ("GET", "HEAD", "OPTIONS") else [IsMember()]

    def workflow(self, pk):
        return get_object_or_404(Workflow, pk=pk, workspace=workspace_for(self.request), archived=False)


class WorkflowListView(_Base):
    def get(self, request):
        qs = Workflow.objects.filter(workspace=workspace_for(request), archived=False)
        return Response(WorkflowListSerializer(qs, many=True).data)

    def post(self, request):
        s = WorkflowWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        name = (s.validated_data.get("name") or "").strip()
        if not name:
            return Response({"detail": "A name is required."}, status=400)
        wf = Workflow.objects.create(workspace=workspace_for(request), name=name)
        return Response(detail(wf), status=status.HTTP_201_CREATED)


class WorkflowDetailView(_Base):
    def get(self, request, pk):
        return Response(detail(self.workflow(pk)))

    def patch(self, request, pk):
        wf = self.workflow(pk)
        s = WorkflowWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        with transaction.atomic():
            # Lock the parent row so concurrent saves cannot pick the same revision number.
            wf = Workflow.objects.select_for_update().get(pk=wf.pk)
            if "name" in data:
                name = data["name"].strip()
                if not name:
                    return Response({"detail": "Name cannot be empty."}, status=400)
                wf.name = name
            if "dead_air_enabled" in data:
                # A setting, not a graph edit: no new revision. Agents using the workflow publish it.
                wf.dead_air_enabled = data["dead_air_enabled"]
            if "graph" in data:
                last = wf.revisions.order_by("-number").first()
                if last is None or last.graph != data["graph"]:
                    WorkflowRevision.objects.create(
                        workflow=wf, number=(last.number + 1) if last else 1,
                        graph=data["graph"], saved_by=request.user,
                    )
            if data.get("accepted_suggestions"):
                from .suggestions_api import accept_on_save

                accept_on_save(wf, data["accepted_suggestions"], request.user)
            wf.save()  # bumps updated_at
        return Response(detail(wf))


class WorkflowValidateView(_Base):
    def get(self, request, pk):
        return Response({"errors": detail(self.workflow(pk))["errors"]})
