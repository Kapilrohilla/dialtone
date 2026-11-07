from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from calls.numbers import strip_nul
from workflows.models import Workflow
from workspaces.permissions import CanEdit, IsMember, workspace_for

from .models import KnowledgeDocument, KnowledgeRevision
from .serializers import (
    KnowledgeDetailSerializer,
    KnowledgeListSerializer,
    KnowledgeWriteSerializer,
    RevisionDetailSerializer,
    RevisionSerializer,
)

MAX_UPLOAD_BYTES = 1024 * 1024


class _Base(APIView):
    def get_permissions(self):
        return [CanEdit()] if self.request.method not in ("GET", "HEAD", "OPTIONS") else [IsMember()]

    def doc(self, pk):
        return get_object_or_404(KnowledgeDocument, pk=pk, workspace=workspace_for(self.request), archived=False)


def _add_revision(doc, body, user):
    """Append a revision unless `body` equals the current one. Caller holds a transaction.

    The document row is locked first so concurrent saves number their revisions one after the other."""
    KnowledgeDocument.objects.select_for_update().only("pk").get(pk=doc.pk)
    cur = doc.revisions.order_by("-number").first()
    if cur is not None and cur.body_md == body:
        return
    KnowledgeRevision.objects.create(
        document=doc, number=(cur.number + 1) if cur else 1, body_md=body, edited_by=user
    )
    doc.save(update_fields=["updated_at"])


def _workflow_steps_using(doc) -> list[tuple[str, str]]:
    """(step, workflow) names of knowledge steps that answer from `doc`, in the current revision of each
    workflow still in use. Older revisions and archived workflows don't count."""
    uses = []
    for wf in Workflow.objects.filter(workspace_id=doc.workspace_id, archived=False).order_by("id"):
        cur = wf.current
        steps = cur.graph.get("steps") if cur is not None and isinstance(cur.graph, dict) else None
        for st in steps if isinstance(steps, list) else []:
            if not isinstance(st, dict) or st.get("type") != "knowledge":
                continue
            kid = st.get("knowledge_id")
            if isinstance(kid, int) and not isinstance(kid, bool) and kid == doc.id:
                name = st.get("name") if isinstance(st.get("name"), str) else ""
                uses.append((name.strip() or str(st.get("id", "")), wf.name))
    return uses


class KnowledgeListView(_Base):
    def get(self, request):
        qs = KnowledgeDocument.objects.filter(workspace=workspace_for(request), archived=False).annotate(
            used_by_count=Count("agents", filter=Q(agents__status__in=["draft", "published"]), distinct=True)
        )
        return Response(KnowledgeListSerializer(qs, many=True).data)

    def post(self, request):
        s = KnowledgeWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        title = (s.validated_data.get("title") or "").strip()
        if not title:
            return Response({"detail": "A title is required."}, status=400)
        with transaction.atomic():
            doc = KnowledgeDocument.objects.create(workspace=workspace_for(request), title=title)
            _add_revision(doc, s.validated_data.get("body_md", ""), request.user)
        return Response(KnowledgeDetailSerializer(doc).data, status=status.HTTP_201_CREATED)


class KnowledgeDetailView(_Base):
    def get(self, request, pk):
        return Response(KnowledgeDetailSerializer(self.doc(pk)).data)

    def patch(self, request, pk):
        doc = self.doc(pk)
        s = KnowledgeWriteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            if "title" in s.validated_data:
                title = s.validated_data["title"].strip()
                if not title:
                    return Response({"detail": "Title cannot be empty."}, status=400)
                doc.title = title
                doc.save(update_fields=["title", "updated_at"])
            if "body_md" in s.validated_data:
                _add_revision(doc, s.validated_data["body_md"], request.user)
        doc.refresh_from_db()
        return Response(KnowledgeDetailSerializer(doc).data)

    def delete(self, request, pk):
        """Remove a document from the console and from every agent that links it.

        Published agents keep quoting it until they are published again (their snapshot holds the text).
        A workflow step that answers from it would be left pointing at nothing, so that is refused. The row
        and its revisions stay in the database, archived."""
        doc = self.doc(pk)
        uses = _workflow_steps_using(doc)
        if uses:
            step, workflow = uses[0]
            more = len(uses) - 1
            also = f" and {more} other step{'s' if more > 1 else ''}" if more else ""
            verb = "use" if more else "uses"
            return Response(
                {"detail": f'The "{step}" step of the workflow "{workflow}"{also} {verb} this document. '
                           "Pick another document there first."},
                status=status.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            locked = KnowledgeDocument.objects.select_for_update().get(pk=doc.pk)
            locked.archived = True
            locked.save(update_fields=["archived", "updated_at"])
            locked.agents.clear()
        return Response(status=status.HTTP_204_NO_CONTENT)


class KnowledgeUploadView(_Base):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        f = request.FILES.get("file")
        if f is None:
            return Response({"detail": "Attach a .md file in the 'file' field."}, status=400)
        name = f.name or ""
        if not name.lower().endswith(".md"):
            return Response({"detail": "Only .md (Markdown) files are supported."}, status=400)
        if f.size > MAX_UPLOAD_BYTES:
            return Response({"detail": "File is too large; the limit is 1 MB."}, status=400)
        try:
            body = strip_nul(f.read().decode("utf-8"))  # Postgres text rejects NUL
        except UnicodeDecodeError:
            return Response({"detail": "File must be UTF-8 text."}, status=400)
        title = name[: -len(".md")].strip() or "Untitled"
        with transaction.atomic():
            doc = KnowledgeDocument.objects.create(workspace=workspace_for(request), title=title[:200])
            _add_revision(doc, body, request.user)
        return Response(KnowledgeDetailSerializer(doc).data, status=status.HTTP_201_CREATED)


class RevisionListView(_Base):
    def get(self, request, pk):
        doc = self.doc(pk)
        return Response(RevisionSerializer(doc.revisions.select_related("edited_by"), many=True).data)


class RevisionDetailView(_Base):
    def get(self, request, pk, number):
        doc = self.doc(pk)
        rev = get_object_or_404(doc.revisions.select_related("edited_by"), number=number)
        return Response(RevisionDetailSerializer(rev).data)
