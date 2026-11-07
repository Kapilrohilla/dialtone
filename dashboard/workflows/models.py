from django.conf import settings
from django.db import models


class Workflow(models.Model):
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="workflows")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived = models.BooleanField(default=False)
    # Off: agents using this workflow don't check in on silent callers (published with the workflow).
    dead_air_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    @property
    def current(self):
        return self.revisions.order_by("-number").first()

    def __str__(self):
        return self.name


class WorkflowRevision(models.Model):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    graph = models.JSONField(default=dict)
    saved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["workflow", "number"], name="uniq_workflow_revision")]
