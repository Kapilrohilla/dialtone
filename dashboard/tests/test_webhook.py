from datetime import datetime, timezone

import pytest
from livekit import api
from livekit.protocol.models import ParticipantInfo

from calls import views
from calls.models import Call

pytestmark = pytest.mark.django_db

T0 = 1_762_300_000


def post(client, auth="Bearer token"):
    return client.post("/webhook", data="{}", content_type="application/webhook+json", HTTP_AUTHORIZATION=auth)


def feed(monkeypatch, client, *events):
    """Deliver each event through the view, bypassing signature checks."""
    queue = list(events)
    monkeypatch.setattr(views.receiver, "receive", lambda body, auth: queue.pop(0))
    for _ in events:
        assert post(client).status_code == 200


def sip_joined(room, phone, ts):
    return api.WebhookEvent(
        event="participant_joined",
        room=api.Room(name=room),
        participant=api.ParticipantInfo(
            identity=f"sip_{phone}",
            kind=ParticipantInfo.Kind.SIP,
            attributes={"sip.phoneNumber": phone, "sip.trunkPhoneNumber": "+918000000000", "sip.callID": "SCL_1"},
        ),
        created_at=ts,
    )


def test_bad_signature_401(client):
    assert post(client, auth="junk").status_code == 401
    assert not Call.objects.exists()


def test_sip_join_records_caller_first_wins(monkeypatch, client):
    feed(monkeypatch, client, sip_joined("r1", "+919111111111", T0), sip_joined("r1", "+919222222222", T0 + 5))
    call = Call.objects.get(room="r1")
    assert call.caller == "+919111111111"
    assert call.called == "+918000000000"
    assert call.sip_call_id == "SCL_1"
    assert call.started_at == datetime.fromtimestamp(T0, timezone.utc)
    assert call.answered_at == datetime.fromtimestamp(T0, timezone.utc)


def test_agent_join_sets_agent_joined_at(monkeypatch, client):
    event = api.WebhookEvent(
        event="participant_joined",
        room=api.Room(name="r2"),
        participant=api.ParticipantInfo(identity="agent-1", kind=ParticipantInfo.Kind.AGENT),
        created_at=T0 + 2,
    )
    feed(monkeypatch, client, event)
    call = Call.objects.get(room="r2")
    assert call.agent_joined_at == datetime.fromtimestamp(T0 + 2, timezone.utc)
    assert call.started_at == datetime.fromtimestamp(T0 + 2, timezone.utc)


def test_room_finished_sets_end_reason(monkeypatch, client):
    event = api.WebhookEvent(
        event="room_finished",
        room=api.Room(name="r3"),
        created_at=T0 + 60,
        room_end_reason=api.RoomEndReason.ROOM_END_IDLE_TIMEOUT,
    )
    feed(monkeypatch, client, sip_joined("r3", "+919111111111", T0), event)
    call = Call.objects.get(room="r3")
    assert call.end_reason == "idle_timeout"
    assert call.ended_at == datetime.fromtimestamp(T0 + 60, timezone.utc)
    assert call.as_dict()["ended_at"] == T0 + 60
