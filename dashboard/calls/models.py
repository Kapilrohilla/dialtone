from datetime import datetime

from django.db import models

DATETIME_FIELDS = ("started_at", "answered_at", "ended_at", "agent_joined_at")
TEXT_FIELDS = ("caller", "called", "sip_call_id", "end_reason")


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
        return row
