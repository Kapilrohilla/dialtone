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


class AuditFixRun(models.Model):
    """One "Suggest fixes" run (KAP-37): Gemini turns the problems of one or more audits into draft changes.

    Workflow fixes are ``WorkflowSuggestion`` rows in this run's ``workflow_set`` (source "audit"); agent fixes are
    ``AgentSuggestion`` rows. Nothing here touches the agent or workflow until a fix is accepted."""

    CALL, BATCH = "call", "batch"
    SCOPES = [(CALL, "One call"), (BATCH, "Recent calls")]
    RUNNING, READY, EMPTY, ERROR = "running", "ready", "empty", "error"
    STATUSES = [(RUNNING, "Running"), (READY, "Ready"), (EMPTY, "Empty"), (ERROR, "Error")]

    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="audit_fix_runs")
    agent = models.ForeignKey("voiceagents.Agent", on_delete=models.CASCADE, related_name="audit_fix_runs")
    agent_version = models.ForeignKey(
        "voiceagents.AgentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # the version whose audits were read
    workflow_revision = models.ForeignKey(
        "workflows.WorkflowRevision", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # the revision those calls ran on
    call = models.ForeignKey("calls.Call", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    scope = models.CharField(max_length=10, choices=SCOPES)
    audit_ids = models.JSONField(default=list)  # the input pool
    status = models.CharField(max_length=10, choices=STATUSES, default=RUNNING)
    error = models.TextField(blank=True, default="")  # user-safe; details go to the logs
    dropped = models.PositiveIntegerField(default=0)  # fixes Gemini proposed that failed validation
    auto_applied = models.PositiveIntegerField(default=0)
    model = models.CharField(max_length=80, blank=True, default="")
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class AgentSuggestion(models.Model):
    """One draft change to an agent from an audit-fix run: a script section rewritten, a knowledge snippet added,
    or settings changed. Accepting writes to the agent (the draft); publishing stays a separate step."""

    SCRIPT, KNOWLEDGE, SETTINGS = "script", "knowledge", "settings"
    KINDS = [(SCRIPT, "Script section"), (KNOWLEDGE, "Knowledge snippet"), (SETTINGS, "Settings")]
    PENDING, ACCEPTED, DISMISSED = "pending", "accepted", "dismissed"
    STATUSES = [(PENDING, "Pending"), (ACCEPTED, "Accepted"), (DISMISSED, "Dismissed")]

    run = models.ForeignKey(AuditFixRun, on_delete=models.CASCADE, related_name="agent_items")
    agent = models.ForeignKey("voiceagents.Agent", on_delete=models.CASCADE, related_name="suggestions")
    kind = models.CharField(max_length=10, choices=KINDS)
    payload = models.JSONField()  # as produced by Gemini, after validation
    edited_payload = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    invalid_reason = models.TextField(blank=True, default="")  # last computed; recomputed on every read
    audit = models.JSONField(default=dict, blank=True)  # same shape as WorkflowSuggestion.audit
    auto_applied = models.BooleanField(default=False)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    included_in = models.ForeignKey(
        "voiceagents.AgentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # the first version published with it

    class Meta:
        ordering = ["id"]

    @property
    def effective_payload(self):
        return self.edited_payload or self.payload
