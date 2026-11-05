from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from calls import livekit_state
from calls.models import Call

pytestmark = pytest.mark.django_db

LEGACY_KEYS = {
    "room", "started_at", "answered_at", "ended_at", "caller", "called",
    "sip_call_id", "agent_joined_at", "end_reason",
}
# Added by the per-call report (Task 11); None when a call has no report.
REPORT_KEYS = {"disposition", "final_mood", "worst_mood", "avg_sentiment", "dead_air_nudges", "llm_ttft_p50_ms"}


@pytest.fixture
def staff_client(client):
    client.force_login(User.objects.create_user("ops", password="x"))
    return client


class _DownRoomService:
    async def list_rooms(self, *_a, **_kw):
        raise RuntimeError("livekit is down")


class _DownLiveKitAPI:
    def __init__(self, *_a, **_kw):
        self.room = _DownRoomService()

    async def aclose(self):
        pass


def test_state_requires_login(client):
    res = client.get("/api/state")
    assert res.status_code == 302
    assert res["Location"].startswith("/admin/login/")


def test_state_shape_when_livekit_down(monkeypatch, staff_client):
    monkeypatch.setattr(livekit_state.api, "LiveKitAPI", _DownLiveKitAPI)

    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    Call.objects.create(room="yesterday", started_at=midnight - timedelta(minutes=1), caller="+911")
    Call.objects.create(
        room="early",
        started_at=midnight + timedelta(seconds=10),
        answered_at=midnight + timedelta(seconds=12),
        ended_at=midnight + timedelta(seconds=72),
        agent_joined_at=midnight + timedelta(seconds=13),
        caller="+912",
    )
    Call.objects.create(room="late", started_at=midnight + timedelta(seconds=20), caller="+913")

    res = staff_client.get("/api/state")
    assert res.status_code == 200
    data = res.json()

    assert set(data) == {"now", "server", "live", "trunks", "rules", "recent", "today"}
    assert data["server"]["ok"] is False
    assert "livekit is down" in data["server"]["error"]
    assert data["live"] == [] and data["trunks"] == [] and data["rules"] == []

    assert [c["room"] for c in data["recent"]] == ["late", "early", "yesterday"]
    assert set(data["recent"][0]) == LEGACY_KEYS | REPORT_KEYS
    assert data["recent"][1]["started_at"] == int((midnight + timedelta(seconds=10)).timestamp())

    assert data["today"]["total"] == 2
    assert data["today"]["answered"] == 1
    assert data["today"]["avg_duration"] == 60


def test_index_redirects_to_console(client, settings):
    settings.CONSOLE_URL = "http://localhost:3000/"
    res = client.get("/")
    assert res.status_code == 302 and res["Location"] == "http://localhost:3000/"
