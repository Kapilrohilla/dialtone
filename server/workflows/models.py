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


class WorkflowSuggestionSet(models.Model):
    """One "Suggest with AI" run: what Gemini was asked about and how it went. Its items are drafts."""

    STEP, WORKFLOW = "step", "workflow"
    SCOPES = [(STEP, "This step"), (WORKFLOW, "Whole workflow")]
    RUNNING, READY, EMPTY, ERROR, CLOSED = "running", "ready", "empty", "error", "closed"
    STATUSES = [(RUNNING, "Running"), (READY, "Ready"), (EMPTY, "Empty"), (ERROR, "Error"), (CLOSED, "Closed")]

    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="suggestion_sets")
    base_revision = models.ForeignKey(WorkflowRevision, on_delete=models.CASCADE, related_name="+")
    scope = models.CharField(max_length=10, choices=SCOPES)
    step_ids = models.JSONField(default=list)  # steps sent to Gemini
    total_steps = models.PositiveIntegerField(default=0)  # steps that could have been sent (whole workflow caps at 20)
    failed_step_ids = models.JSONField(default=list)  # steps whose batch failed ("Some steps couldn't be checked.")
    kinds = models.JSONField(default=list)  # subset of ["answers", "expressions"]
    status = models.CharField(max_length=10, choices=STATUSES, default=RUNNING)
    error = models.TextField(blank=True, default="")  # user-safe; details go to the logs
    step_fingerprints = models.JSONField(default=dict)  # {step_id: sha1} at base_revision; drives "out of date"
    model = models.CharField(max_length=80, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class WorkflowSuggestion(models.Model):
    """One draft change: a new answer (path) out of a step, or expressions added to a step's words."""

    ANSWER, EXPRESSION = "answer", "expression"
    KINDS = [(ANSWER, "Answer"), (EXPRESSION, "Expression")]
    PENDING, ACCEPTED, DISMISSED = "pending", "accepted", "dismissed"
    STATUSES = [(PENDING, "Pending"), (ACCEPTED, "Accepted"), (DISMISSED, "Dismissed")]

    suggestion_set = models.ForeignKey(WorkflowSuggestionSet, on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=10, choices=KINDS)
    step_id = models.CharField(max_length=200)
    payload = models.JSONField()  # as produced by Gemini, after validation
    edited_payload = models.JSONField(null=True, blank=True)  # the author's edit ("Save to draft")
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    invalid_reason = models.TextField(blank=True, default="")  # last computed; recomputed on every read
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    @property
    def effective_payload(self):
        return self.edited_payload or self.payload
