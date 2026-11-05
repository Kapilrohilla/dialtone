import csv
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from calls.models import Call, CallEvent, CallReport
from calls.outcomes import DISPLAY_OUTCOME, display_outcome
from tests.helpers import assert_isolated
from voiceagents.models import Agent, AgentVersion

pytestmark = pytest.mark.django_db

IST = ZoneInfo("Asia/Kolkata")


def at(day="2026-11-05", hh=10, mm=0, ss=0):
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


def agent_version(workspace, name="Driver lead qualifier", phone_number=""):
    agent = Agent.objects.create(workspace=workspace, name=name, phone_number=phone_number)
    version = AgentVersion.objects.create(agent=agent, number=1, snapshot={"name": name, "version": 1})
    return agent, version


def make_call(workspace, room, *, started=None, answered=None, ended=None, caller="+919876543210",
              disposition=None, outcome=None, mood="", version=None, data_extra=None, **fields):
    call = Call.objects.create(
        room=room, workspace=workspace, started_at=started, answered_at=answered, ended_at=ended,
        caller=caller, agent_version=version, **fields,
    )
    if disposition is not None:
        data = {"room": room, "disposition": disposition, "outcome": outcome or {}, **(data_extra or {})}
        CallReport.objects.create(call=call, disposition=disposition, final_mood=mood, data=data)
    return call


def event(call, seq, type, payload, when=None):
    return CallEvent.objects.create(call=call, seq=seq, type=type, payload=payload,
                                    at=when or at(ss=seq % 60))


# --- outcomes ---------------------------------------------------------------------------------------

def test_display_outcome_mapping():
    expected = {
        "INTERESTED": "Interested",
        "CBR": "Call back",
        "NI": "Not interested", "NE": "Not interested", "ISUDO": "Not interested", "ISUID": "Not interested",
        "OWNVA": "Not interested", "ABULR": "Not interested", "WRGN": "Not interested",
        "LANGUAGE_BARRIER": "Not interested", "HND": "Not interested",
        "CDRP": "Dropped", "UNRESOLVED": "Dropped",
        "NOT_CONNECTED": "Not reached",
    }
    assert DISPLAY_OUTCOME == expected and len(expected) == 14
    for code, group in expected.items():
        assert display_outcome(code) == group
    assert display_outcome("") == "" and display_outcome(None) == ""
    assert display_outcome("SOMETHING_NEW") == "Dropped"
    assert display_outcome(" interested ") == "Interested"


# --- list -------------------------------------------------------------------------------------------

def test_calls_list_shape_and_fields(member, workspace):
    _, version = agent_version(workspace)
    make_call(workspace, "r1", started=at(hh=10), answered=at(hh=10, ss=5), ended=at(hh=10, mm=2, ss=5),
              disposition="INTERESTED", outcome={"summary": "Wants the weekly plan", "city": "Pune"},
              mood="happy", version=version)
    body = member("viewer").get("/api/calls").json()
    assert body["count"] == 1 and body["page"] == 1 and body["pages"] == 1
    row = body["results"][0]
    assert set(row) == {"room", "started_at", "caller", "agent_name", "outcome", "outcome_code", "mood",
                        "duration_s", "summary"}
    assert row["room"] == "r1" and row["agent_name"] == "Driver lead qualifier"
    assert row["outcome"] == "Interested" and row["outcome_code"] == "INTERESTED" and row["mood"] == "happy"
    assert row["duration_s"] == 120 and row["summary"] == "Wants the weekly plan"
    assert row["caller"] == "+919876543210"


def test_calls_duration_fallbacks(member, workspace):
    make_call(workspace, "a", started=at(hh=9), ended=at(hh=9, mm=1))
    make_call(workspace, "b", started=at(hh=8))
    rows = {r["room"]: r for r in member("viewer").get("/api/calls").json()["results"]}
    assert rows["a"]["duration_s"] == 60 and rows["b"]["duration_s"] is None
    assert rows["b"]["outcome"] == "" and rows["b"]["agent_name"] is None and rows["b"]["summary"] == ""


def test_calls_filter_by_outcome_group(member, workspace):
    make_call(workspace, "ni", started=at(hh=9), disposition="NI")
    make_call(workspace, "wrgn", started=at(hh=9, mm=1), disposition="WRGN")
    make_call(workspace, "int", started=at(hh=9, mm=2), disposition="INTERESTED")
    make_call(workspace, "odd", started=at(hh=9, mm=3), disposition="MADE_UP")
    make_call(workspace, "cdrp", started=at(hh=9, mm=4), disposition="CDRP")
    c = member("viewer")

    def rooms(**params):
        return {r["room"] for r in c.get("/api/calls", params).json()["results"]}

    assert rooms(outcome="Not interested") == {"ni", "wrgn"}
    assert rooms(outcome="Interested") == {"int"}
    assert rooms(outcome="Dropped") == {"odd", "cdrp"}
    assert rooms(outcome="Not reached") == set()
    assert c.get("/api/calls", {"outcome": "Nope"}).status_code == 400


def test_calls_search_digits(member, workspace):
    make_call(workspace, "a", started=at(hh=9), caller="+91 98765 43210")
    make_call(workspace, "b", started=at(hh=9, mm=1), caller="+919111122222")
    c = member("viewer")
    assert [r["room"] for r in c.get("/api/calls", {"q": "98765-432"}).json()["results"]] == ["a"]
    assert [r["room"] for r in c.get("/api/calls", {"q": "1111"}).json()["results"]] == ["b"]
    assert c.get("/api/calls", {"q": "+91"}).json()["count"] == 2


def test_calls_other_filters(member, workspace):
    agent, version = agent_version(workspace)
    make_call(workspace, "a", started=at("2026-11-03", hh=23, mm=59), disposition="NI", mood="angry",
              outcome={"city": "Pune"}, version=version)
    make_call(workspace, "b", started=at("2026-11-04", hh=0, mm=1), disposition="NI", mood="happy",
              outcome={"city": "Delhi"})
    c = member("viewer")

    def rooms(**params):
        r = c.get("/api/calls", params)
        assert r.status_code == 200, r.content
        return {x["room"] for x in r.json()["results"]}

    assert rooms(agent=agent.id) == {"a"}
    assert rooms(mood="Angry") == {"a"}
    assert rooms(city="delhi") == {"b"}
    assert rooms(**{"from": "2026-11-04"}) == {"b"}
    assert rooms(to="2026-11-03") == {"a"}
    assert rooms(**{"from": "2026-11-03", "to": "2026-11-04"}) == {"a", "b"}
    for bad in ({"from": "04-11-2026"}, {"to": "2026-13-01"}, {"agent": "x"}, {"page": "zero"}):
        assert c.get("/api/calls", bad).status_code == 400, bad


def test_calls_pagination(member, workspace):
    for i in range(27):
        make_call(workspace, f"r{i:02d}", started=at(hh=9) + timedelta(minutes=i))
    c = member("viewer")
    p1 = c.get("/api/calls").json()
    assert p1["count"] == 27 and p1["pages"] == 2 and len(p1["results"]) == 25
    assert p1["results"][0]["room"] == "r26"  # newest first
    p2 = c.get("/api/calls", {"page": 2}).json()
    assert p2["page"] == 2 and [r["room"] for r in p2["results"]] == ["r01", "r00"]


def test_calls_list_query_count(member, workspace):
    _, version = agent_version(workspace)
    for i in range(10):
        make_call(workspace, f"r{i}", started=at(hh=9, mm=i), disposition="NI", version=version)
    c = member("viewer")
    c.get("/api/calls")  # warm the membership cache path
    with CaptureQueriesContext(connection) as ctx:
        assert c.get("/api/calls").status_code == 200
    assert len(ctx.captured_queries) <= 6


def test_calls_isolated(member, workspace, other_workspace):
    make_call(other_workspace, "theirs", started=at(hh=9), disposition="NI")
    make_call(None, "orphan", started=at(hh=9), disposition="NI")
    make_call(workspace, "ours", started=at(hh=9), disposition="NI", needs_person=True)
    c = member("editor")
    assert [r["room"] for r in c.get("/api/calls").json()["results"]] == ["ours"]
    assert_isolated(c, "/api/calls/theirs")
    assert_isolated(c, "/api/calls/orphan")
    assert c.post("/api/calls/theirs/needs-person", {"handled": True}, format="json").status_code == 404
    rows = list(csv.reader(io.StringIO(c.get("/api/calls/export.csv").content.decode("utf-8-sig"))))
    assert [r[1] for r in rows[1:]] == ["+919876543210"] and len(rows) == 2
    dash = c.get("/api/dashboard", {"date": "2026-11-05"}).json()
    assert dash["calls_today"] == 1 and [n["room"] for n in dash["needs_person"]] == ["ours"]


# --- detail -----------------------------------------------------------------------------------------

def test_call_detail_transcript_from_events(member, workspace):
    _, version = agent_version(workspace)
    call = make_call(workspace, "r1", started=at(hh=10), answered=at(hh=10, ss=2), ended=at(hh=10, mm=1, ss=2),
                     disposition="CBR",
                     outcome={"reason": "Busy driving", "summary": "Call back at 6", "city": "Pune",
                              "licence": "", "experience": "3 years", "callback_time": "6pm", "uber_id": None},
                     version=version)
    event(call, 3, "turn", {"speaker": "agent", "text": "Namaste! [[expr:happy]]", "expressions": ["happy"]})
    event(call, 1, "step_entered", {"step_id": "s1", "step_name": "Greeting"})
    event(call, 2, "turn", {"speaker": "caller", "text": "हाँ बोलिए"})
    event(call, 4, "turn", {"speaker": "caller"})  # no text: skipped
    event(call, 5, "turn", "not a dict")  # malformed: skipped
    event(call, 6, "field_captured", {"field": "city", "value": "Mumbai"})
    event(call, 7, "field_captured", {"field": "licence", "value": "yes"})
    event(call, 8, "field_captured", {"nope": 1})
    event(call, 9, "mood", ["bad"])
    r = member("viewer").get("/api/calls/r1")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["room"] == "r1" and body["outcome"] == "Call back" and body["duration_s"] == 60
    assert body["reason"] == "Busy driving" and body["summary"] == "Call back at 6"
    assert body["answers"] == {"city": "Mumbai", "licence": "yes", "experience": "3 years", "callback_time": "6pm"}
    assert body["step_path"] == ["Greeting"]
    assert [(t["speaker"], t["text"], t["expressions"]) for t in body["transcript"]] == [
        ("caller", "हाँ बोलिए", []),
        ("agent", "Namaste! [[expr:happy]]", ["happy"]),
    ]
    assert all(t["at"] for t in body["transcript"])
    assert body["recording_url"] is None


def test_call_detail_step_path_from_report(member, workspace):
    call = make_call(workspace, "r1", started=at(hh=10), disposition="NI",
                     data_extra={"step_path": ["Greeting", "Qualify"]})
    event(call, 1, "step_entered", {"step_name": "Other"})
    body = member("viewer").get("/api/calls/r1").json()
    assert body["step_path"] == ["Greeting", "Qualify"]
    assert body["answers"] == {} and body["reason"] == "" and body["transcript"] == []


def test_call_detail_without_report_or_bad_data(member, workspace):
    make_call(workspace, "bare", started=at(hh=10))
    call = make_call(workspace, "weird", started=at(hh=10), disposition="NI")
    CallReport.objects.filter(call=call).update(data={"outcome": "oops", "step_path": "nope"})
    c = member("viewer")
    for room in ("bare", "weird"):
        r = c.get(f"/api/calls/{room}")
        assert r.status_code == 200, r.content
        assert r.json()["answers"] == {} and r.json()["step_path"] == []


# --- export -----------------------------------------------------------------------------------------

def test_csv_export_headers_and_devanagari(member, workspace):
    _, version = agent_version(workspace, name="प्रिया agent")
    make_call(workspace, "r1", started=at(hh=10), answered=at(hh=10), ended=at(hh=10, mm=1, ss=30),
              disposition="INTERESTED", outcome={"summary": "ड्राइवर weekly plan चाहता है"}, mood="happy",
              version=version)
    make_call(workspace, "r2", started=at(hh=11), disposition="NI", outcome={"summary": "=HYPERLINK(1)"})
    c = member("viewer")
    r = c.get("/api/calls/export.csv")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")
    assert r["Content-Disposition"] == 'attachment; filename="calls.csv"'
    raw = b"".join(r.streaming_content) if r.streaming else r.content
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == ["When", "Caller", "Agent", "Outcome", "Mood", "Duration", "Summary"]
    assert rows[1][1:] == ["+919876543210", "", "Not interested", "", "", "'=HYPERLINK(1)"]
    assert rows[2] == ["2026-11-05 10:00", "+919876543210", "प्रिया agent", "Interested", "happy", "90",
                       "ड्राइवर weekly plan चाहता है"]
    filtered = c.get("/api/calls/export.csv", {"outcome": "Interested"})
    raw = b"".join(filtered.streaming_content) if filtered.streaming else filtered.content
    assert len(list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))) == 2
    assert c.get("/api/calls/export.csv", {"from": "bad"}).status_code == 400


# --- needs person -----------------------------------------------------------------------------------

def test_needs_person_handled(member, workspace):
    call = make_call(workspace, "r1", started=at(hh=10), needs_person=True)
    viewer = member("viewer")
    assert viewer.post("/api/calls/r1/needs-person", {"handled": True}, format="json").status_code == 403
    c = member("editor")
    assert c.post("/api/calls/r1/needs-person", {"handled": "yes"}, format="json").status_code == 400
    r = c.post("/api/calls/r1/needs-person", {"handled": True}, format="json")
    assert r.status_code == 200, r.content
    call.refresh_from_db()
    assert call.needs_person_handled_at is not None
    assert r.json()["handled_at"] is not None
    r = c.post("/api/calls/r1/needs-person", {"handled": False}, format="json")
    call.refresh_from_db()
    assert r.status_code == 200 and call.needs_person_handled_at is None
    assert c.post("/api/calls/missing/needs-person", {"handled": True}, format="json").status_code == 404


# --- dashboard --------------------------------------------------------------------------------------

def test_dashboard_numbers(member, workspace):
    agent, version = agent_version(workspace, phone_number="+911234567890")
    agent.status, agent.published_version = Agent.PUBLISHED, version
    agent.save()
    day = "2026-11-05"
    # 4 calls that day: 1 not reached, 3 connected (durations 60, 120, 300); one interested.
    make_call(workspace, "c1", started=at(day, 9), answered=at(day, 9), ended=at(day, 9, 1),
              disposition="INTERESTED")
    make_call(workspace, "c2", started=at(day, 10), answered=at(day, 10), ended=at(day, 10, 2),
              disposition="NI")
    make_call(workspace, "c3", started=at(day, 11), answered=at(day, 11), ended=at(day, 11, 5),
              disposition="CBR", outcome={"reason": "Driving now"}, needs_person=True)
    make_call(workspace, "c4", started=at(day, 12), ended=at(day, 12, 0, 30), disposition="NOT_CONNECTED")
    # Earlier in the week (counts in outcomes_week only), and one outside the week.
    make_call(workspace, "w1", started=at("2026-10-31", 12), disposition="NI", needs_person=True,
              needs_person_handled_at=timezone.now())
    make_call(workspace, "w2", started=at("2026-10-29", 23, 59), disposition="INTERESTED")
    make_call(workspace, "next", started=at("2026-11-06", 0, 5), disposition="INTERESTED")
    c = member("viewer")
    r = c.get("/api/dashboard", {"date": day})
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["calls_today"] == 4
    assert body["connected_pct"] == 75
    assert body["interested"] == 1
    assert body["avg_duration_s"] == 160
    assert [(n["room"], n["reason"]) for n in body["needs_person"]] == [("c3", "Driving now")]
    assert body["needs_person"][0]["caller"] == "+919876543210" and body["needs_person"][0]["at"]
    week = {o["outcome"]: o["count"] for o in body["outcomes_week"]}
    assert week == {"Interested": 1, "Call back": 1, "Not interested": 2, "Dropped": 0, "Not reached": 1}
    assert body["live_agent"] == {"id": agent.id, "name": "Driver lead qualifier", "phone_number": "+911234567890"}
    assert c.get("/api/dashboard", {"date": "2026/11/05"}).status_code == 400


def test_dashboard_empty_defaults(member, workspace):
    body = member("viewer").get("/api/dashboard").json()
    assert body["calls_today"] == 0 and body["connected_pct"] is None and body["avg_duration_s"] is None
    assert body["needs_person"] == [] and body["live_agent"] is None
    assert all(o["count"] == 0 for o in body["outcomes_week"])


# --- agents list ------------------------------------------------------------------------------------

def test_agents_list_calls_this_week(member, workspace):
    agent, version = agent_version(workspace)
    other, other_version = agent_version(workspace, name="Other")
    now = timezone.now()
    make_call(workspace, "a1", started=now - timedelta(days=1), version=version)
    make_call(workspace, "a2", started=now - timedelta(days=6), version=version)
    make_call(workspace, "old", started=now - timedelta(days=8), version=version)
    make_call(workspace, "o1", started=now - timedelta(hours=2), version=other_version)
    rows = {a["id"]: a for a in member("viewer").get("/api/agents").json()}
    assert rows[agent.id]["calls_this_week"] == 2 and rows[other.id]["calls_this_week"] == 1


def test_answers_use_real_outcome_shape(member, workspace):
    # Exactly the keys agent/agent.py record_outcome writes.
    outcome = {
        "disposition": "INTERESTED", "reason": "Wants work", "summary": "Keen on weekly rental",
        "interest_strength": "none", "telecaller_followup_agreed": False,
        "callback_time": "", "city": "Pune", "licence": "valid 4-wheeler, own name",
        "experience": "Ola 2 years", "uber_id": "active", "preferred_plan": "Uber Go rental",
        "main_question": "Deposit kitna hai?", "do_not_call": False,
    }
    call = make_call(workspace, "real", started=at(hh=10), disposition="INTERESTED", outcome=outcome)
    event(call, 1, "field_captured", {"field": "callback_time", "value": "kal shaam"})
    event(call, 2, "field_captured", {"field": "city", "value": "Pune, Hinjewadi"})
    answers = member("viewer").get("/api/calls/real").json()["answers"]
    assert answers == {
        "callback_time": "kal shaam", "city": "Pune, Hinjewadi", "licence": "valid 4-wheeler, own name",
        "experience": "Ola 2 years", "uber_id": "active", "preferred_plan": "Uber Go rental",
        "main_question": "Deposit kitna hai?",
    }
    for meta in ("interest_strength", "telecaller_followup_agreed", "do_not_call"):
        assert meta not in answers


def test_answers_layer_report_captured_under_events(member, workspace):
    outcome = {"disposition": "INTERESTED", "reason": "r", "summary": "s", "city": "Pune", "licence": "yes"}
    captured = {"city": "Pune, Wakad", "shift": "night", "vehicle": "", "bad": 5}
    call = make_call(workspace, "cap", started=at(hh=10), disposition="INTERESTED", outcome=outcome,
                     data_extra={"captured": captured})
    event(call, 1, "field_captured", {"field": "shift", "value": "day"})
    answers = member("viewer").get("/api/calls/cap").json()["answers"]
    # outcome < report captured < live events; empty and non-string captures are skipped.
    assert answers == {"city": "Pune, Wakad", "licence": "yes", "shift": "day"}
    for bad in (["city"], "x", None):
        CallReport.objects.filter(call=call).update(data={"room": "cap", "outcome": outcome, "captured": bad})
        assert member("viewer").get("/api/calls/cap").json()["answers"]["city"] == "Pune"
