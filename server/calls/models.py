from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone as djtz

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
        Recording.from_report(call.room, report.get("recording"))
        # Score the call once the report is saved; an audit failure never touches ingest (it never raises).
        from audits.run import queue_after_report

        transaction.on_commit(lambda call_id=call.pk: queue_after_report(call_id))
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


def _ns(value) -> datetime | None:
    """A LiveKit nanosecond epoch as an aware datetime; None for 0/missing/bad values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1e9, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def recording_relpath(filename: str) -> str:
    """A recording's path relative to RECORDINGS_DIR, from the egress file name (an absolute path inside
    the egress container). "" when it isn't a plain path under the recordings directory."""
    filename = str(filename or "").strip()
    for root in (settings.EGRESS_RECORDINGS_DIR, str(settings.RECORDINGS_DIR)):
        prefix = root.rstrip("/") + "/"
        if filename.startswith(prefix):
            filename = filename[len(prefix):]
            break
    else:
        if filename.startswith("/"):
            return ""
    parts = PurePosixPath(filename).parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        return ""
    return str(PurePosixPath(*parts))


class Recording(models.Model):
    """A call's audio recording (LiveKit Egress), tracked from egress webhooks and the agent's report."""

    STARTING, RECORDING, COMPLETE, FAILED, PURGED = "starting", "recording", "complete", "failed", "purged"
    STATUSES = [(s, s) for s in (STARTING, RECORDING, COMPLETE, FAILED, PURGED)]
    FINAL = {COMPLETE, FAILED, PURGED}
    # Recording started but no egress_ended arrived this long after the call ended: settle from the file.
    RECONCILE_AFTER = timedelta(minutes=10)

    call = models.OneToOneField(Call, on_delete=models.CASCADE, related_name="recording")
    egress_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUSES, default=STARTING, db_index=True)
    path = models.CharField(max_length=512, blank=True)  # relative to settings.RECORDINGS_DIR
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"recording of {self.call.room} ({self.status})"

    def file(self) -> Path | None:
        """The recording file on disk, if this recording has one and it exists inside RECORDINGS_DIR."""
        rel = recording_relpath(self.path)
        if not rel:
            return None
        root = Path(settings.RECORDINGS_DIR).resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
        return path

    @classmethod
    @transaction.atomic
    def _for(cls, room: str, egress_id: str) -> "Recording":
        call = Call.record_first(room)
        rec = cls.objects.select_for_update().filter(call=call).first()
        if rec is None and egress_id:
            rec = cls.objects.select_for_update().filter(egress_id=egress_id).first()
        if rec is None:
            rec = cls(call=call)
        if egress_id and not rec.egress_id:
            rec.egress_id = egress_id
        return rec

    @classmethod
    def from_egress(cls, info) -> "Recording | None":
        """Apply an egress webhook (EgressInfo). Idempotent; a final status is never moved back by a late
        or repeated event. None when the event names no room."""
        from livekit.protocol.egress import EgressStatus

        room = strip_nul(info.room_name or "")
        if not room:
            return None
        with transaction.atomic():
            rec = cls._for(room, strip_nul(info.egress_id or ""))
            status = info.status
            if status in (EgressStatus.EGRESS_STARTING, EgressStatus.EGRESS_ACTIVE, EgressStatus.EGRESS_ENDING):
                if rec.status not in cls.FINAL:
                    rec.status = cls.RECORDING if status != EgressStatus.EGRESS_STARTING else rec.status
                rec.started_at = rec.started_at or _ns(info.started_at)
            elif status == EgressStatus.EGRESS_COMPLETE or status == EgressStatus.EGRESS_LIMIT_REACHED:
                if rec.status != cls.PURGED:
                    files = list(info.file_results)
                    f = files[0] if files else None
                    if f is not None and recording_relpath(f.filename):
                        rec.status = cls.COMPLETE
                        rec.path = recording_relpath(f.filename)
                        rec.size_bytes = max(0, int(f.size)) or None
                        rec.duration_ms = max(0, int(f.duration) // 1_000_000) or None
                        # The file's own start lines transcript times up best; else when the egress started.
                        rec.started_at = _ns(f.started_at) or rec.started_at or _ns(info.started_at)
                        rec.error = ""
                    else:
                        rec.status = cls.FAILED
                        rec.error = strip_nul(info.error) or "egress ended without a file"
                    rec.ended_at = _ns(info.ended_at) or djtz.now()
            elif status in (EgressStatus.EGRESS_FAILED, EgressStatus.EGRESS_ABORTED):
                if rec.status not in (cls.COMPLETE, cls.PURGED):
                    rec.status = cls.FAILED
                    rec.error = strip_nul(info.error) or EgressStatus.Name(status).lower()
                    rec.ended_at = _ns(info.ended_at) or djtz.now()
            rec.save()
        return rec

    @classmethod
    def from_report(cls, room: str, data) -> "Recording | None":
        """The agent's report["recording"]: {"egress_id", "started_at" (epoch s), "filepath", "error"}.
        Links the egress to the call even when webhooks come late or never; never overrides webhook data."""
        if not isinstance(data, dict):
            return None
        egress_id = data.get("egress_id") if isinstance(data.get("egress_id"), str) else ""
        error = data.get("error") if isinstance(data.get("error"), str) else ""
        if not egress_id and not error:
            return None
        with transaction.atomic():
            rec = cls._for(room, egress_id[:64])
            if not egress_id and rec.status not in cls.FINAL:
                rec.status = cls.FAILED
            if error and not rec.error and rec.status == cls.FAILED:
                rec.error = error[:2000]
            started = data.get("started_at")
            if rec.started_at is None and isinstance(started, (int, float)) and not isinstance(started, bool):
                rec.started_at = _ns(started * 1e9)
            filepath = data.get("filepath")
            if not rec.path and rec.status != cls.PURGED and isinstance(filepath, str):
                rec.path = recording_relpath(filepath)
            rec.save()
        return rec

    def reconcile(self) -> None:
        """A recording stuck in starting/recording long after its call ended (egress_ended lost): settle it
        from the file on disk, else mark it failed."""
        if self.status in self.FINAL:
            return
        ended = self.call.ended_at
        if ended is None or djtz.now() - ended < self.RECONCILE_AFTER:
            return
        path = self.file()
        if path is not None:
            self.status, self.size_bytes = self.COMPLETE, path.stat().st_size
        else:
            self.status, self.error = self.FAILED, self.error or "no egress result after the call ended"
        self.ended_at = self.ended_at or ended
        self.save(update_fields=["status", "size_bytes", "error", "ended_at", "updated_at"])
