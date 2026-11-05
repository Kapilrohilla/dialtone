import copy
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from knowledge.models import KnowledgeDocument
from workflows.models import Workflow
from workspaces.permissions import CanEdit, IsMember, workspace_for

from . import publish as pub
from . import voices
from .models import Agent
from .serializers import (
    AgentDetailSerializer,
    AgentListItemSerializer,
    AgentVersionSerializer,
    AgentWriteSerializer,
    merge_settings,
)
from .tokens import BUILTIN_EXPRESSIONS

PLAIN_FIELDS = ["name", "description", "phone_number", "language", "persona_name", "voice_id", "script",
                "custom_expressions"]


class _Base(APIView):
    def get_permissions(self):
        return [CanEdit()] if self.request.method not in ("GET", "HEAD", "OPTIONS") else [IsMember()]

    def agent(self, pk):
        return get_object_or_404(
            Agent.objects.select_related("updated_by", "published_version", "workflow"),
            pk=pk, workspace=workspace_for(self.request),
        )


def _detail(agent):
    return AgentDetailSerializer(agent).data


def _resolve_links(data, workspace):
    """Turn knowledge/workflow ids into objects of this workspace; 400 for anything else."""
    links = {}
    if "knowledge" in data:
        ids = set(data["knowledge"])
        docs = list(KnowledgeDocument.objects.filter(workspace=workspace, archived=False, id__in=ids))
        if len(docs) != len(ids):
            raise serializers.ValidationError({"knowledge": ["Choose knowledge documents from this workspace."]})
        links["knowledge"] = docs
    if "workflow" in data:
        wf = None
        if data["workflow"] is not None:
            wf = Workflow.objects.filter(workspace=workspace, archived=False, pk=data["workflow"]).first()
            if wf is None:
                raise serializers.ValidationError({"workflow": ["Choose a workflow from this workspace."]})
        links["workflow"] = wf
    return links


def _save(agent, data, links, user):
    """Apply validated fields to `agent` (locked or new) and save. Caller holds a transaction."""
    fields = []
    for f in PLAIN_FIELDS:
        if f in data:
            setattr(agent, f, data[f])
            fields.append(f)
    if "settings" in data:
        agent.settings = merge_settings(agent.settings, data["settings"])
        fields.append("settings")
    if "workflow" in links:
        agent.workflow = links["workflow"]
        fields.append("workflow")
    agent.updated_by = user
    if agent.pk is None:
        agent.save()
    else:
        # update_fields: never write status/published_version from a possibly stale copy.
        agent.save(update_fields=fields + ["updated_by", "updated_at"])
    if "knowledge" in links:
        agent.knowledge.set(links["knowledge"])


class AgentListView(_Base):
    def get(self, request):
        # calls_this_week: calls on any version of the agent with started_at in the last 7 days
        # (calls with no started_at are not counted).
        week_ago = timezone.now() - timedelta(days=7)
        qs = (
            Agent.objects.filter(workspace=workspace_for(request))
            .select_related("updated_by", "published_version", "workflow")
            .annotate(calls_this_week=Count(
                "versions__calls", filter=Q(versions__calls__started_at__gte=week_ago), distinct=True
            ))
        )
        return Response(AgentListItemSerializer(qs, many=True).data)

    def post(self, request):
        workspace = workspace_for(request)
        s = AgentWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if not s.validated_data.get("name"):
            return Response({"name": ["A name is required."]}, status=400)
        links = _resolve_links(s.validated_data, workspace)
        with transaction.atomic():
            agent = Agent(workspace=workspace)
            _save(agent, s.validated_data, links, request.user)
        return Response(_detail(agent), status=status.HTTP_201_CREATED)


class AgentDetailView(_Base):
    def get(self, request, pk):
        return Response(_detail(self.agent(pk)))

    def patch(self, request, pk):
        agent = self.agent(pk)
        s = AgentWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        links = _resolve_links(s.validated_data, agent.workspace)
        with transaction.atomic():
            locked = Agent.objects.select_for_update().get(pk=agent.pk)
            _save(locked, s.validated_data, links, request.user)
        return Response(_detail(self.agent(pk)))


class AgentPublishView(_Base):
    def post(self, request, pk):
        try:
            version = pub.publish(self.agent(pk), request.user)
        except pub.PublishError as e:
            return Response({"errors": e.errors}, status=400)
        return Response({"version": version.number})


class _StateView(_Base):
    action = None

    def post(self, request, pk):
        try:
            self.action(self.agent(pk))
        except pub.StateError as e:
            return Response({"detail": e.detail}, status=400)
        return Response(_detail(self.agent(pk)))


class AgentUnpublishView(_StateView):
    action = staticmethod(pub.unpublish)


class AgentArchiveView(_StateView):
    action = staticmethod(pub.archive)


class AgentRestoreView(_StateView):
    action = staticmethod(pub.restore)


class AgentDuplicateView(_Base):
    def post(self, request, pk):
        src = self.agent(pk)
        with transaction.atomic():
            copy_ = Agent.objects.create(
                workspace=src.workspace,
                name=f"Copy of {src.name}"[:200],
                description=src.description,
                status=Agent.DRAFT,
                phone_number=src.phone_number,
                language=src.language,
                persona_name=src.persona_name,
                voice_id=src.voice_id,
                settings=copy.deepcopy(src.settings),
                script=copy.deepcopy(src.script),
                custom_expressions=copy.deepcopy(src.custom_expressions),
                workflow=src.workflow,
                updated_by=request.user,
            )
            copy_.knowledge.set(src.knowledge.all())
        return Response(_detail(copy_), status=status.HTTP_201_CREATED)


class AgentVersionsView(_Base):
    def get(self, request, pk):
        agent = self.agent(pk)
        return Response(AgentVersionSerializer(agent.versions.select_related("published_by"), many=True).data)


class ExpressionsView(_Base):
    def get(self, request):
        return Response([{"name": n, "hint": h, "builtin": True} for n, h in BUILTIN_EXPRESSIONS.items()])


class VoicesView(_Base):
    def get(self, request):
        return Response({"pipeline": settings.AGENT_PIPELINE, "voices": voices.for_pipeline(settings.AGENT_PIPELINE)})
