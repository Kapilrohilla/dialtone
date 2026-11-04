from datetime import datetime

from django.db import models

DATETIME_FIELDS = ("started_at", "answered_at", "ended_at", "agent_joined_at")
TEXT_FIELDS = ("caller", "called", "sip_call_id", "end_reason")
REPORT_FIELDS = ("disposition", "final_mood", "worst_mood", "avg_sentiment", "dead_air_nudges", "llm_ttft_p50_ms")

# Copied from agent/mood.py (Emotion); the dashboard must not import the agent.
EMOTIONS = ("neutral", "interested", "confused", "frustrated", "rushed", "suspicious", "angry", "disengaged")


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
        if changed:
            call.save(update_fields=changed)
        return call

    @classmethod
    def mark_ended(cls, room: str, ended_at: datetime, reason: str) -> "Call":
        call, _ = cls.objects.get_or_create(room=room)
        call.ended_at = ended_at
        call.end_reason = reason or ""
        call.save(update_fields=["ended_at", "end_reason"])
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
    def store(cls, report: dict) -> "CallReport":
        """Save a report; it may arrive before the room's webhooks, and a later report replaces an earlier one."""
        call = Call.record_first(report["room"])
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
        return obj
