from django.conf import settings
from django.db import models
from django.db.models import Q


class CallAudit(models.Model):
    """Gemini's scorecard for the AI side of one call. A re-audit adds a new row and makes it current;
    older rows stay for history."""

    QUEUED, RUNNING, READY, SKIPPED, ERROR = "queued", "running", "ready", "skipped", "error"
    STATUSES = [(s, s.capitalize()) for s in (QUEUED, RUNNING, READY, SKIPPED, ERROR)]
    ACTIVE = (QUEUED, RUNNING)

    TOO_SHORT, NO_TRANSCRIPT = "too_short", "no_transcript"
    SKIP_REASONS = [(TOO_SHORT, "Too short to audit"), (NO_TRANSCRIPT, "No transcript to audit")]

    call = models.ForeignKey("calls.Call", on_delete=models.CASCADE, related_name="audits")
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="call_audits")
    agent_version = models.ForeignKey(
        "voiceagents.AgentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    workflow_revision = models.ForeignKey(
        "workflows.WorkflowRevision", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_current = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED, db_index=True)
    error = models.TextField(blank=True, default="")  # user-safe; details go to the logs
    skipped_reason = models.CharField(max_length=20, blank=True, default="", choices=SKIP_REASONS)
    overall_score = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)  # 0–100
    # {area: {"score": 1-5 | None, "summary": str, "evidence": [{"line", "at", "at_s", "quote", "step_id",
    #  "event", "kind", "note"}]}}
    scores = models.JSONField(default=dict, blank=True)
    weights = models.JSONField(default=dict, blank=True)  # the weights the overall score used
    summary = models.TextField(blank=True, default="")
    # [{"line", "at", "at_s", "kind": "good"|"problem", "area", "step_id", "quote", "note"}]
    moments = models.JSONField(default=list, blank=True)
    rubric_version = models.CharField(max_length=40, blank=True, default="")
    model = models.CharField(max_length=80, blank=True, default="")
    used_audio = models.BooleanField(default=False)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)  # runs started; the sweep gives up after a few
    quotes_purged = models.BooleanField(default=False)  # caller words removed by purge_old_call_data
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # null for automatic audits
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["call"], condition=Q(is_current=True), name="uniq_current_call_audit"),
        ]

    def __str__(self) -> str:
        return f"audit of {self.call.room} ({self.status})"
