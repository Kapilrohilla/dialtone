import pytest

from calls import livekit_state
from tests.test_calls_api import agent_version, at, event, make_call

pytestmark = pytest.mark.django_db


def sip(identity="sip_caller", phone="+919876543210"):
    return {"identity": identity, "kind": "sip", "joined_at": 1, "phone": phone, "call_status": "active",
            "tracks": 1}


def agent_participant():
    return {"identity": "agent-1", "kind": "agent", "joined_at": 1, "phone": None, "call_status": None,
            "tracks": 1}


def state(*rooms, trunks=None):
    return {
        "server": {"ok": True, "error": None},
        "live": [{"room": r, "created_at": 1_762_300_000, "participants": [agent_participant(), sip()]}
                 for r in rooms],
        "trunks": trunks or [],
        "rules": [],
    }


@pytest.fixture
def livekit(monkeypatch):
    """Fake LiveKit: set `.state`; records transfer/end calls. Never reaches a real server."""

    class Fake:
        state = state()
        transfers = []
        ended = []

    async def fetch():
        return Fake.state

    async def transfer(room, participant_identity, to_uri):
        Fake.transfers.append((room, participant_identity, to_uri))

    async def end_call(room):
        Fake.ended.append(room)

    monkeypatch.setattr(livekit_state, "fetch_livekit_state", fetch)
    monkeypatch.setattr(livekit_state, "transfer", transfer)
    monkeypatch.setattr(livekit_state, "end_call", end_call)
    return Fake


def test_live_lists_rooms_with_tail(member, workspace, other_workspace, livekit):
    call = make_call(workspace, "live-1", started=at(hh=10))
    make_call(other_workspace, "theirs", started=at(hh=10))
    make_call(None, "orphan", started=at(hh=10))
    livekit.state = state("live-1", "theirs", "orphan", "unknown-room")
    for i in range(1, 56):
        event(call, i, "turn", {"speaker": "caller" if i % 2 else "agent", "text": f"t{i}"})
    event(call, 60, "step_entered", {"step_id": "s1", "step_name": "Greeting"})
    event(call, 61, "step_entered", {"step_id": "s2", "step_name": "Qualify"})
    event(call, 62, "mood", {"label": "happy", "confidence": 0.8})
    event(call, 63, "mood", {"label": "angry", "confidence": 0.6})
    event(call, 64, "field_captured", {"field": "city", "value": "Pune"})
    event(call, 65, "field_captured", {"field": "licence", "value": "yes"})
    event(call, 66, "mood", "garbage")
    event(call, 67, "step_entered", 42)
    r = member("viewer").get("/api/live")
    assert r.status_code == 200, r.content
    body = r.json()
    assert [x["room"] for x in body] == ["live-1"]
    row = body[0]
    assert row["caller"] == "+919876543210" and row["city"] == "Pune" and row["started_at"]
    assert row["current_step"] == "Qualify" and row["mood"] == "angry"
    assert len(row["transcript_tail"]) == 50
    assert row["transcript_tail"][0]["text"] == "t6" and row["transcript_tail"][-1]["text"] == "t55"
    assert set(row["transcript_tail"][0]) == {"speaker", "text", "expressions", "at"}
    assert call_count() == 3  # nothing created for the unknown room


def call_count():
    from calls.models import Call

    return Call.objects.count()


def test_live_empty_defaults(member, workspace, livekit):
    make_call(workspace, "live-1", started=None, caller="")
    livekit.state = state("live-1")
    row = member("viewer").get("/api/live").json()[0]
    assert row["current_step"] == "" and row["mood"] == "" and row["city"] == ""
    assert row["transcript_tail"] == [] and row["caller"] == "+919876543210"


def test_transfer_409_without_uri(member, workspace, livekit, settings):
    settings.HANDOFF_SIP_URI = ""
    make_call(workspace, "live-1", started=at(hh=10))
    livekit.state = state("live-1")
    r = member("editor").post("/api/live/live-1/transfer")
    assert r.status_code == 409 and r.json() == {"detail": "Live transfer isn't set up."}
    assert livekit.transfers == []


def test_transfer_moves_sip_participant(member, workspace, other_workspace, livekit, settings):
    settings.HANDOFF_SIP_URI = "sip:desk@example.com"
    make_call(workspace, "live-1", started=at(hh=10))
    make_call(workspace, "done", started=at(hh=9))
    make_call(other_workspace, "theirs", started=at(hh=10))
    livekit.state = state("live-1", "theirs")
    assert member("viewer").post("/api/live/live-1/transfer").status_code == 403
    c = member("editor")
    r = c.post("/api/live/live-1/transfer")
    assert r.status_code == 200, r.content
    assert livekit.transfers == [("live-1", "sip_caller", "sip:desk@example.com")]
    assert c.post("/api/live/theirs/transfer").status_code == 404
    assert c.post("/api/live/done/transfer").status_code == 404  # not live
    assert c.post("/api/live/nope/transfer").status_code == 404
    assert len(livekit.transfers) == 1


def test_end_calls_livekit(member, workspace, other_workspace, livekit):
    make_call(workspace, "live-1", started=at(hh=10))
    make_call(other_workspace, "theirs", started=at(hh=10))
    livekit.state = state("live-1", "theirs")
    assert member("viewer").post("/api/live/live-1/end").status_code == 403
    c = member("editor")
    assert c.post("/api/live/theirs/end").status_code == 404
    r = c.post("/api/live/live-1/end")
    assert r.status_code == 200, r.content
    assert livekit.ended == ["live-1"]


def test_livekit_errors_are_502(member, workspace, livekit, monkeypatch, settings):
    settings.HANDOFF_SIP_URI = "sip:desk@example.com"
    make_call(workspace, "live-1", started=at(hh=10))
    livekit.state = state("live-1")

    async def boom(*a, **k):
        raise RuntimeError("twirp error")

    monkeypatch.setattr(livekit_state, "end_call", boom)
    monkeypatch.setattr(livekit_state, "transfer", boom)
    c = member("editor")
    assert c.post("/api/live/live-1/end").status_code == 502
    assert c.post("/api/live/live-1/transfer").status_code == 502


def test_phone_numbers_from_trunks(member, workspace, other_workspace, livekit):
    agent_version(workspace, name="Driver lead qualifier", phone_number="+91 12345 67890")
    agent_version(other_workspace, name="Their agent", phone_number="+919999999999")
    livekit.state = state(trunks=[
        {"id": "t1", "name": "Exotel inbound", "numbers": ["911234567890", "+918888888888"], "allowed": []},
        {"id": "t2", "name": "Other trunk", "numbers": ["+919999999999"], "allowed": []},
    ])
    r = member("viewer").get("/api/phone-numbers")
    assert r.status_code == 200, r.content
    assert r.json() == [
        {"number": "911234567890", "trunk_name": "Exotel inbound", "agent_name": "Driver lead qualifier"},
        {"number": "+918888888888", "trunk_name": "Exotel inbound", "agent_name": None},
    ]
