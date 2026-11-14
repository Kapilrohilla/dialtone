import json
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from livekit import api

from calls import livekit_state
from calls.models import Call, CallReport

pytestmark = pytest.mark.django_db


def token(identity="agent-report"):
    return api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).with_identity(identity).to_jwt()


def make_report(room="call-x", final="frustrated", worst="angry", dead_air=None, **extra):
    report = {
        "room": room,
        "disposition": "callback",
        "outcome": {"disposition": "callback"},
        "mood": {"final": final, "worst": worst, "avg_sentiment": -0.4, "changes": 2},
        "timeline": [
            {"at_s": 3.0, "emotion": "neutral", "confidence": 0.9, "source": "text"},
            {"at_s": 9.5, "emotion": final, "confidence": 0.8, "source": "text"},
        ],
        "dead_air": dead_air if dead_air is not None else [{"action": "nudge", "silence_s": 6.0}],
        "latency": {"llm_ttft": {"p50_ms": 420, "p95_ms": 900, "n": 5}},
        "behavior": {"interruptions": 1},
    }
    report.update(extra)
    return report


def post(client, body, bearer=None):
    data = body if isinstance(body, str) else json.dumps(body)
    return client.post(
        "/api/report",
        data=data,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {bearer if bearer is not None else token()}",
    )


@pytest.fixture
def staff_client(client):
    client.force_login(User.objects.create_user("ops", password="x"))
    return client


def test_report_rejects_bad_token(client):
    assert post(client, make_report(), bearer="junk").status_code == 401
    assert post(client, make_report(), bearer=token("someone-else")).status_code == 401
    assert not CallReport.objects.exists()


def test_report_rejects_missing_room(client):
    body = make_report()
    del body["room"]
    assert post(client, body).status_code == 400
    assert post(client, "{not json").status_code == 400


def test_report_before_webhook_creates_call(client, staff_client):
    body = make_report(room="call-x")
    assert post(client, body).status_code == 200
    assert Call.objects.get(room="call-x").report.final_mood == "frustrated"

    res = staff_client.get("/api/report/call-x")
    assert res.status_code == 200
    assert res.json() == body


def test_report_detail_requires_login_and_404s(client):
    CallReport.store(make_report(room="call-x"))
    assert client.get("/api/report/call-x").status_code == 302
    client.force_login(User.objects.create_user("ops", password="x"))
    assert client.get("/api/report/nope").status_code == 404


def test_report_replaces_previous(client):
    assert post(client, make_report(final="frustrated")).status_code == 200
    assert post(client, make_report(final="angry")).status_code == 200
    assert CallReport.objects.count() == 1
    assert CallReport.objects.get().final_mood == "angry"


def test_dead_air_nudges_excludes_hang_up(client):
    events = [
        {"action": "nudge", "silence_s": 6.0},
        {"action": "second_nudge", "silence_s": 10.0},
        {"action": "hang_up", "silence_s": 15.0},
    ]
    assert post(client, make_report(dead_air=events)).status_code == 200
    report = CallReport.objects.get()
    assert report.dead_air_nudges == 2
    assert report.llm_ttft_p50_ms == 420
    assert report.worst_mood == "angry"
    assert report.avg_sentiment == -0.4
    assert report.disposition == "callback"


class _DownLiveKitAPI:
    def __init__(self, *_a, **_kw):
        raise RuntimeError("livekit is down")


def test_state_rows_include_mood(monkeypatch, staff_client):
    monkeypatch.setattr(livekit_state.api, "LiveKitAPI", _DownLiveKitAPI)
    CallReport.store(make_report(room="call-y", final="confused"))
    Call.objects.filter(room="call-y").update(started_at=timezone.now())
    Call.objects.create(room="no-report", started_at=timezone.now() - timedelta(minutes=5))

    recent = staff_client.get("/api/state").json()["recent"]
    assert recent[0]["final_mood"] == "confused"
    rows = {r["room"]: r for r in recent}
    assert rows["call-y"]["dead_air_nudges"] == 1
    assert rows["no-report"]["final_mood"] is None
    assert rows["no-report"]["dead_air_nudges"] is None
