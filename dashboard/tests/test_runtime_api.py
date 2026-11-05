import importlib
import json

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from calls.models import Call, CallEvent, CallReport
from tests.test_report import make_report, token
from voiceagents.models import Agent, AgentVersion

pytestmark = pytest.mark.django_db

RUNTIME = "agent-runtime"


def published_agent(workspace, phone_number="", name="Driver lead qualifier"):
    agent = Agent.objects.create(workspace=workspace, name=name, phone_number=phone_number)
    version = AgentVersion.objects.create(agent=agent, number=1, snapshot={"agent": {"name": name}, "version": 1})
    agent.status = Agent.PUBLISHED
    agent.published_version = version
    agent.save()
    return agent, version


def get_config(client, bearer=None, **params):
    return client.get(
        "/api/runtime/config",
        params,
        HTTP_AUTHORIZATION=f"Bearer {bearer if bearer is not None else token(RUNTIME)}",
    )


def post_events(client, body, bearer=None):
    data = body if isinstance(body, str) else json.dumps(body)
    return client.post(
        "/api/runtime/events",
        data=data,
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {bearer if bearer is not None else token(RUNTIME)}",
    )


def ev(seq, type="turn", at=1_762_300_000.0, payload=None):
    return {"seq": seq, "type": type, "at": at,
            "payload": payload if payload is not None else {"speaker": "caller", "text": f"t{seq}", "expressions": []}}


# --- auth -------------------------------------------------------------------------------------------


def test_config_requires_runtime_token(client, workspace):
    published_agent(workspace)
    assert get_config(client, bearer=token("agent-report")).status_code == 401
    assert get_config(client, bearer="junk").status_code == 401
    assert client.get("/api/runtime/config").status_code == 401
    assert get_config(client).status_code == 200


def test_events_require_runtime_token(client):
    body = {"room": "r1", "events": [ev(1)]}
    assert post_events(client, body, bearer=token("agent-report")).status_code == 401
    assert post_events(client, body, bearer="junk").status_code == 401
    assert not Call.objects.exists()


def test_report_rejects_runtime_token(client):
    res = client.post("/api/report", data=json.dumps(make_report()), content_type="application/json",
                      HTTP_AUTHORIZATION=f"Bearer {token(RUNTIME)}")
    assert res.status_code == 401


# --- config -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("number", ["+91 80 4718 2290", "918047182290", "08047182290", "8047182290"])
def test_config_by_number(client, workspace, other_workspace, number):
    _, version = published_agent(workspace, phone_number="918047182290")
    published_agent(other_workspace, phone_number="+91 99999 00000")
    res = get_config(client, number=number)
    assert res.status_code == 200
    assert res.json() == {"version_id": version.id, "workspace": "carrum", "snapshot": version.snapshot}


def test_config_unmatched_number_404s_when_numbers_set(client, workspace):
    published_agent(workspace, phone_number="918047182290")
    res = get_config(client, number="+91 11 1111 1111")
    assert res.status_code == 404
    assert res.json() == {"detail": "No published agent for this number."}


def test_config_single_published_fallback(client, workspace):
    _, version = published_agent(workspace)
    Agent.objects.create(workspace=workspace, name="draft one", phone_number="")
    res = get_config(client, number="+918047182290")
    assert res.status_code == 200
    assert res.json()["version_id"] == version.id
    assert get_config(client).json()["version_id"] == version.id


def test_config_no_fallback_across_workspaces(client, workspace, other_workspace):
    published_agent(workspace)
    published_agent(other_workspace)
    assert get_config(client, number="+918047182290").status_code == 404


def test_config_404_json_when_none(client, workspace):
    Agent.objects.create(workspace=workspace, name="draft", phone_number="918047182290")
    res = get_config(client, number="918047182290")
    assert res.status_code == 404
    assert res.json() == {"detail": "No published agent for this number."}


def test_config_sets_call_version(client, workspace):
    _, v1 = published_agent(workspace)
    assert get_config(client, room="room-1").status_code == 200
    call = Call.objects.get(room="room-1")
    assert call.agent_version == v1 and call.workspace == workspace

    # A later publish doesn't move a call that already started.
    agent = v1.agent
    v2 = AgentVersion.objects.create(agent=agent, number=2, snapshot={"version": 2})
    agent.published_version = v2
    agent.save()
    assert get_config(client, room="room-1").json()["version_id"] == v2.id
    assert Call.objects.get(room="room-1").agent_version == v1


# --- events -----------------------------------------------------------------------------------------


def test_events_before_call_exists(client):
    res = post_events(client, {"room": "new-room", "events": [ev(1), ev(2, "mood", payload={"label": "happy", "confidence": 0.8})]})
    assert res.status_code == 200
    assert res.json() == {"stored": 2, "skipped": 0}
    call = Call.objects.get(room="new-room")
    assert [e.type for e in call.events.all()] == ["turn", "mood"]


def test_events_idempotent_by_seq(client):
    body = {"room": "r1", "events": [ev(1), ev(2)]}
    assert post_events(client, body).json() == {"stored": 2, "skipped": 0}
    assert post_events(client, body).json() == {"stored": 0, "skipped": 0}
    body["events"].append(ev(3, "step_entered", payload={"step_id": "s1", "step_name": "Opening"}))
    assert post_events(client, body).json() == {"stored": 1, "skipped": 0}
    assert CallEvent.objects.count() == 3


def test_events_ordered_by_seq_when_out_of_order(client):
    post_events(client, {"room": "r1", "events": [ev(5), ev(2)]})
    post_events(client, {"room": "r1", "events": [ev(3, "field_captured", payload={"field": "city", "value": "Pune"}), ev(1)]})
    assert [e.seq for e in Call.objects.get(room="r1").events.all()] == [1, 2, 3, 5]


def test_events_batch_limit_413(client):
    res = post_events(client, {"room": "r1", "events": [ev(i) for i in range(201)]})
    assert res.status_code == 413
    assert not CallEvent.objects.exists()
    assert post_events(client, {"room": "r1", "events": [ev(i) for i in range(200)]}).json()["stored"] == 200


def test_events_skips_invalid(client):
    events = [
        ev(1, "unknown"),
        {"seq": "2", "type": "turn", "payload": {}},
        {"seq": 3, "payload": {}},
        {"seq": 4, "type": "turn", "payload": "text"},
        {"seq": True, "type": "turn", "payload": {}},
        {"seq": -1, "type": "turn", "payload": {}},
        {"seq": 10**12, "type": "turn", "payload": {}},
        "not a dict",
        {"seq": 5, "type": "turn", "payload": {"speaker": "agent", "text": "hi", "expressions": []}},  # no `at`
        {"seq": 6, "type": "turn", "at": "bad", "payload": {}},
        {"seq": 7, "type": "turn", "at": 1e300, "payload": {}},
    ]
    res = post_events(client, {"room": "r1", "events": events})
    assert res.status_code == 200
    assert res.json() == {"stored": 3, "skipped": 8}
    assert [e.seq for e in CallEvent.objects.all()] == [5, 6, 7]
    assert all(e.at is not None for e in CallEvent.objects.all())


@pytest.mark.parametrize("body", ["{not json", "[]", json.dumps({"events": []}), json.dumps({"room": "", "events": []}),
                                  json.dumps({"room": "r1", "events": "x"}), json.dumps({"room": 5, "events": []})])
def test_events_bad_body_400(client, body):
    assert post_events(client, body).status_code == 400


# --- reports ----------------------------------------------------------------------------------------


def test_report_sets_needs_person_for_cbr(client):
    CallReport.store(make_report(room="a", disposition="CBR", final="neutral", worst="neutral"))
    CallReport.store(make_report(room="b", disposition="NI", final="neutral", worst="neutral"))
    CallReport.store(make_report(room="c", disposition="NI", final="neutral", worst="neutral",
                                 outcome={"telecaller_followup_agreed": True}))
    CallReport.store(make_report(room="d", disposition="NI", final="calm", worst="frustrated"))
    flags = {c.room: c.needs_person for c in Call.objects.all()}
    assert flags == {"a": True, "b": False, "c": True, "d": True}

    # A later, calmer report never clears the flag.
    CallReport.store(make_report(room="a", disposition="NI", final="neutral", worst="neutral"))
    assert Call.objects.get(room="a").needs_person is True


def test_report_sets_agent_version(client, workspace):
    _, version = published_agent(workspace)
    CallReport.store(make_report(room="a", agent_version_id=version.id, step_path=["s1", "s2"]))
    call = Call.objects.get(room="a")
    assert call.agent_version == version and call.workspace == workspace
    assert call.report.data["step_path"] == ["s1", "s2"]

    # Unknown or junk ids are ignored, not a 500.
    CallReport.store(make_report(room="b", agent_version_id=999999))
    CallReport.store(make_report(room="c", agent_version_id="abc"))
    assert Call.objects.get(room="b").agent_version is None
    assert Call.objects.get(room="c").agent_version is None


# --- migration --------------------------------------------------------------------------------------


def test_existing_calls_assigned_to_carrum(workspace):
    """Run calls/0004's data step against the historical models."""
    migration = importlib.import_module("calls.migrations.0004_runtime")
    executor = MigrationExecutor(connection)
    apps = executor.loader.project_state(("calls", "0004_runtime")).apps
    Call.objects.create(room="old-1")
    Call.objects.create(room="old-2")
    migration.assign_existing_calls(apps, None)
    assert set(Call.objects.values_list("workspace__slug", flat=True)) == {"carrum"}


# --- fix round 1: every call gets a workspace (R18) ------------------------------------------------

from livekit import api as lkapi  # noqa: E402

from tests.test_webhook import T0, feed, sip_joined  # noqa: E402


def room_finished(room):
    return lkapi.WebhookEvent(event="room_finished", room=lkapi.Room(name=room), created_at=T0 + 60,
                              room_end_reason=lkapi.RoomEndReason.ROOM_END_IDLE_TIMEOUT)


def test_webhook_call_gets_workspace_from_called_number(monkeypatch, client, workspace, other_workspace):
    # Any status counts: a draft agent's number still names its workspace.
    Agent.objects.create(workspace=other_workspace, name="other", phone_number="08000000000")
    feed(monkeypatch, client, sip_joined("r1", "+919111111111", T0))
    assert Call.objects.get(room="r1").workspace == other_workspace


def test_webhook_call_gets_single_workspace_fallback(monkeypatch, client, workspace):
    feed(monkeypatch, client, room_finished("r-ended"))  # mark_ended path
    assert Call.objects.get(room="r-ended").workspace == workspace


def test_events_call_gets_workspace(client, workspace):
    assert post_events(client, {"room": "ev-room", "events": [ev(1)]}).status_code == 200
    assert Call.objects.get(room="ev-room").workspace == workspace


def test_two_workspaces_unmatched_stays_null(monkeypatch, client, workspace, other_workspace):
    Agent.objects.create(workspace=workspace, name="a", phone_number="+91 99999 11111")
    post_events(client, {"room": "ev-room", "events": [ev(1)]})
    assert Call.objects.get(room="ev-room").workspace is None
    CallReport.store(make_report(room="rep-room"))
    assert Call.objects.get(room="rep-room").workspace is None
    feed(monkeypatch, client, sip_joined("sip-room", "+919111111111", T0))
    assert Call.objects.get(room="sip-room").workspace is None


def test_called_arriving_later_fills_workspace(monkeypatch, client, workspace, other_workspace):
    Agent.objects.create(workspace=other_workspace, name="other", phone_number="+918000000000")
    post_events(client, {"room": "r1", "events": [ev(1)]})  # no `called` yet: two workspaces, no match
    assert Call.objects.get(room="r1").workspace is None
    feed(monkeypatch, client, sip_joined("r1", "+919111111111", T0))
    assert Call.objects.get(room="r1").workspace == other_workspace


def test_existing_workspace_never_overwritten(monkeypatch, client, workspace, other_workspace):
    Agent.objects.create(workspace=other_workspace, name="other", phone_number="+918000000000")
    Call.objects.create(room="r1", workspace=workspace)
    feed(monkeypatch, client, sip_joined("r1", "+919111111111", T0), room_finished("r1"))
    post_events(client, {"room": "r1", "events": [ev(1)]})
    CallReport.store(make_report(room="r1"))
    assert Call.objects.get(room="r1").workspace == workspace


# --- fix round 1: NUL bytes (R19) ------------------------------------------------------------------


def test_events_nul_in_text_stored_without_nul(client):
    payload = {"speaker": "caller", "text": "na\x00mas\x00te", "expressions": ["hap\x00py"], "k\x00": {"deep": ["\x00x"]}}
    res = post_events(client, {"room": "r\x00oom", "events": [ev(1, payload=payload)]})
    assert res.status_code == 200 and res.json()["stored"] == 1
    e = CallEvent.objects.get()
    assert e.call.room == "room"
    assert e.payload == {"speaker": "caller", "text": "namaste", "expressions": ["happy"], "k": {"deep": ["x"]}}


def test_report_nul_in_summary_ok(client):
    body = make_report(room="call-nul", summary="Caller\x00 wants a callback", outcome={"summary": "x\x00y"})
    res = client.post("/api/report", data=json.dumps(body), content_type="application/json",
                      HTTP_AUTHORIZATION=f"Bearer {token()}")
    assert res.status_code == 200
    data = CallReport.objects.get(call__room="call-nul").data
    assert data["summary"] == "Caller wants a callback" and data["outcome"]["summary"] == "xy"
