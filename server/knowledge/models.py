from django.conf import settings
from django.db import models


class KnowledgeDocument(models.Model):
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="knowledge_documents")
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-updated_at", "-id"]

    @property
    def current(self):
        return self.revisions.order_by("-number").first()

    def __str__(self):
        return self.title


class KnowledgeRevision(models.Model):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    body_md = models.TextField(blank=True, default="")
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["document", "number"], name="uniq_knowledge_revision")]
