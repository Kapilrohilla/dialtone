from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from calls.numbers import strip_nul
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
