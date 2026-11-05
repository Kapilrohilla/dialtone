from datetime import datetime

from django.db import models, transaction

from .evaluation import EMOTIONS, UNCLEAR, align_predictions
from .numbers import same_number, strip_nul

DATETIME_FIELDS = ("started_at", "answered_at", "ended_at", "agent_joined_at")
TEXT_FIELDS = ("caller", "called", "sip_call_id", "end_reason")
REPORT_FIELDS = ("disposition", "final_mood", "worst_mood", "avg_sentiment", "dead_air_nudges", "llm_ttft_p50_ms")

LABEL_CHOICES = [(e, e) for e in EMOTIONS] + [(UNCLEAR, UNCLEAR)]


def resolve_workspace(called):
    """The workspace a call belongs to: the one whose agent (any status) has the `called` number, if that
    is unambiguous; otherwise the only workspace, if there is exactly one; otherwise None."""
    from voiceagents.models import Agent
    from workspaces.models import Workspace

    if str(called or "").strip():
        agents = Agent.objects.exclude(phone_number="").values_list("workspace_id", "phone_number")
        matched = {ws for ws, number in agents if same_number(number, called)}
        if len(matched) == 1:
            return Workspace.objects.get(pk=matched.pop())
    only = list(Workspace.objects.all()[:2])
    return only[0] if len(only) == 1 else None


def assign_unassigned_calls() -> int:
    """Give every call without a workspace the one `resolve_workspace` picks for its `called` number
    (used after bulk copies/imports, which bypass `record_first`). Returns how many were assigned."""
    assigned = 0
    called_numbers = Call.objects.filter(workspace__isnull=True).values_list("called", flat=True).distinct()
    for called in list(called_numbers):
        workspace = resolve_workspace(called)
        if workspace is not None:
            assigned += Call.objects.filter(workspace__isnull=True, called=called).update(workspace=workspace)
    return assigned


class Call(models.Model):
    """One LiveKit room, recorded from webhooks."""

    room = models.CharField(max_length=255, unique=True)
    started_at = models.DateTimeField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    agent_joined_at = models.DateTimeField(null=True, blank=True)
    caller = models.CharField(max_length=64, blank=True)
    called = models.CharField(max_length=64, blank=True)
    sip_call_id = models.CharField(max_length=255, blank=True)
    end_reason = models.CharField(max_length=64, blank=True)
    # Null until the agent asks for its config (or for calls recorded before workspaces existed).
    workspace = models.ForeignKey(
        "workspaces.Workspace", null=True, blank=True, on_delete=models.CASCADE, related_name="calls"
    )
    # The version the call started with; never moved by a later publish.
    agent_version = models.ForeignKey(
        "voiceagents.AgentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="calls"
    )
    needs_person = models.BooleanField(default=False)
    needs_person_handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return self.room

    @classmethod
    def record_first(cls, room: str, **fields) -> "Call":
        """Create the row if missing; set each given field only while it is still empty (first value wins)."""
        call, _ = cls.objects.get_or_create(room=room)
        changed = [k for k, v in fields.items() if v not in (None, "") and getattr(call, k) in (None, "")]
        for k in changed:
            setattr(call, k, fields[k])
        changed += call._fill_workspace()
        if changed:
            call.save(update_fields=changed)
        return call

    def _fill_workspace(self) -> list[str]:
        """Set the workspace while it is still empty (never overwrite); returns the changed field names."""
        if self.workspace_id is not None:
            return []
        workspace = resolve_workspace(self.called)
        if workspace is None:
            return []
        self.workspace = workspace
        return ["workspace"]

    @classmethod
    def mark_ended(cls, room: str, ended_at: datetime, reason: str) -> "Call":
        call, _ = cls.objects.get_or_create(room=room)
        call.ended_at = ended_at
        call.end_reason = reason or ""
        call.save(update_fields=["ended_at", "end_reason", *call._fill_workspace()])
        return call

    def as_dict(self) -> dict:
        """Same keys as the old `calls` table row; datetimes as epoch seconds."""
        row = {"room": self.room}
        for k in DATETIME_FIELDS:
            v = getattr(self, k)
            row[k] = int(v.timestamp()) if v else None
        for k in TEXT_FIELDS:
            row[k] = getattr(self, k) or None
        try:
            report = self.report
        except CallReport.DoesNotExist:
            report = None
        for k in REPORT_FIELDS:
            v = getattr(report, k) if report else None
            row[k] = None if v == "" else v
        return row


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


NEEDS_PERSON_MOODS = {"angry", "frustrated"}


def _needs_person(report: dict) -> bool:
    """A telecaller should follow up: callback asked for, follow-up agreed, or the caller ended up upset."""
    mood = _dict(report.get("mood"))
    return (
        str(report.get("disposition") or "").strip().upper() == "CBR"
        or bool(_dict(report.get("outcome")).get("telecaller_followup_agreed"))
        or str(mood.get("final") or "").lower() in NEEDS_PERSON_MOODS
        or str(mood.get("worst") or "").lower() in NEEDS_PERSON_MOODS
    )


def _agent_version(value):
    from voiceagents.models import AgentVersion

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return AgentVersion.objects.select_related("agent").filter(pk=value).first()


class CallReport(models.Model):
    """The per-call report the agent POSTs when a call ends (mood, dead air, latency)."""

    call = models.OneToOneField(Call, on_delete=models.CASCADE, related_name="report")
    disposition = models.CharField(max_length=64, blank=True)
    final_mood = models.CharField(max_length=32, blank=True)
    worst_mood = models.CharField(max_length=32, blank=True)
    avg_sentiment = models.FloatField(null=True, blank=True)
    dead_air_nudges = models.PositiveIntegerField(default=0)
    llm_ttft_p50_ms = models.PositiveIntegerField(null=True, blank=True)
    data = models.JSONField()
    received_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"report for {self.call.room}"

    @classmethod
    @transaction.atomic
    def store(cls, report: dict) -> "CallReport":
        """Save a report; it may arrive before the room's webhooks, and a later report replaces an earlier one."""
        report = strip_nul(report)
        version = _agent_version(report.get("agent_version_id"))
        fields = {"agent_version": version, "workspace_id": version.agent.workspace_id} if version else {}
        call = Call.record_first(report["room"], **fields)
        if not call.needs_person and _needs_person(report):
            # Only ever set here; a telecaller clears it by handling the call, never a re-sent report.
            call.needs_person = True
            call.save(update_fields=["needs_person"])
        # report["step_path"] stays in `data` with the rest of the report.
        mood = _dict(report.get("mood"))
        latency = _dict(report.get("latency"))
        dead_air = [e for e in report.get("dead_air") or [] if isinstance(e, dict)]
        obj, _ = cls.objects.update_or_create(
            call=call,
            defaults={
                "disposition": str(report.get("disposition") or ""),
                "final_mood": str(mood.get("final") or ""),
                "worst_mood": str(mood.get("worst") or ""),
                "avg_sentiment": mood.get("avg_sentiment"),
                "dead_air_nudges": sum(1 for e in dead_air if e.get("action") != "hang_up"),
                "llm_ttft_p50_ms": _dict(latency.get("llm_ttft")).get("p50_ms"),
                "data": report,
            },
        )
        turns = report.get("turns")
        if isinstance(turns, list):
            timeline = [r for r in report.get("timeline") or [] if isinstance(r, dict)]
            for row in align_predictions([t for t in turns if isinstance(t, dict)], timeline):
                # update_or_create leaves `label` alone, so telecaller labels survive a re-store.
                TurnLabel.objects.update_or_create(
                    report=obj,
                    at_s=row["at_s"],
                    defaults={"caller_text": row["caller_text"], "predicted": row["predicted"]},
                )
        return obj


class TurnLabel(models.Model):
    """One caller turn with the agent's mood reading, for a telecaller to label."""

    report = models.ForeignKey(CallReport, on_delete=models.CASCADE, related_name="turns")
    at_s = models.FloatField()
    caller_text = models.TextField()
    predicted = models.CharField(max_length=32)
    label = models.CharField(max_length=32, blank=True, choices=LABEL_CHOICES)

    class Meta:
        unique_together = ("report", "at_s")
        ordering = ["report", "at_s"]

    def __str__(self) -> str:
        return f"{self.report.call.room} @ {self.at_s:.1f}s"


class CallEvent(models.Model):
    """One live event the agent streams during a call; `seq` is the agent's per-call counter."""

    TURN, STEP_ENTERED, MOOD, FIELD_CAPTURED = "turn", "step_entered", "mood", "field_captured"
    TYPES = [(TURN, "Turn"), (STEP_ENTERED, "Step entered"), (MOOD, "Mood"), (FIELD_CAPTURED, "Field captured")]

    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="events")
    seq = models.PositiveIntegerField()
    type = models.CharField(max_length=20, choices=TYPES)
    payload = models.JSONField(default=dict)
    at = models.DateTimeField()

    class Meta:
        ordering = ["call", "seq"]
        constraints = [models.UniqueConstraint(fields=["call", "seq"], name="uniq_call_event_seq")]

    def __str__(self) -> str:
        return f"{self.call.room} #{self.seq} {self.type}"
