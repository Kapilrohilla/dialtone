"""Call audits (KAP-17), with Gemini mocked: input building, validation, triggers, API, call list, retention."""
import copy
from datetime import datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from django.utils import timezone

from audits import build, run
from audits.models import CallAudit
from audits.rubric import AREA_KEYS, DEFAULT_WEIGHTS, overall
from audits.validate import Invalid, scorecard
from calls.models import Call, CallEvent, CallReport
from tests.helpers import assert_isolated
from tests.test_workflow_graph import driver_graph
from voiceagents.models import Agent, AgentVersion

pytestmark = pytest.mark.django_db

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 11, 5, 10, 0, 0, tzinfo=IST)

LINES = [
    ("agent", "s1", "Namaste! Main Northwind se Priya bol rahi hoon."),
    ("caller", None, "haan boliye"),
    ("agent", "s2", "Aap kis city mein rehte ho?"),
    ("caller", None, "Pune"),
    ("agent", "s3", "Kya aapke paas commercial licence hai?"),
    ("caller", None, "haan hai"),
]


def area(score, line, quote, kind="good"):
    return {"score": score, "summary": f"{kind} work", "evidence": [{"line": line, "quote": quote, "kind": kind,
                                                                      "note": "n"}]}


GEMINI_OUT = {
    "summary": "Polite and clear; the licence question sounded scripted.",
    "scores": {
        "naturalness": area(3, 4, "commercial licence hai", "problem"),
        "listening": area(4, 2, "kis city mein"),
        "empathy": area(4, 0, "Namaste!"),
        "pacing": {"score": 5, "summary": "short turns", "evidence": [
            {"line": -1, "quote": "", "kind": "good", "event": "latency", "note": "fast replies"}]},
        "flow": area(4, 2, "Aap kis city mein rehte ho?"),
        "accuracy": area(5, 0, "Northwind se Priya"),
    },
    "moments": [
        {"line": 0, "kind": "good", "area": "empathy", "quote": "Namaste!", "note": "warm opening"},
        {"line": 4, "kind": "problem", "area": "naturalness", "quote": "commercial licence", "note": "stiff"},
        {"line": 9, "kind": "problem", "area": "listening", "quote": "made up words", "note": "invented"},
    ],
}


def make_version(workspace, graph=None):
    agent = Agent.objects.create(workspace=workspace, name="Driver lead qualifier")
    return AgentVersion.objects.create(agent=agent, number=1, snapshot={
        "name": "Driver lead qualifier", "persona_name": "Priya", "language": "Hindi + Hinglish",
        "script": "Be polite.", "knowledge": [],
        "workflow": {"id": 999, "revision": 1, "graph": graph or driver_graph()},
    })


def make_call(workspace, room="r1", lines=LINES, version=None, started=T0, report=True):
    call = Call.objects.create(room=room, workspace=workspace, started_at=started, answered_at=started,
                               ended_at=started + timedelta(minutes=2), caller="+919876543210",
                               agent_version=version)
    seq = 0
    current = None
    for i, (speaker, step, text) in enumerate(lines):
        if step and step != current:
            seq += 1
            CallEvent.objects.create(call=call, seq=seq, type="step_entered",
                                     payload={"step_id": step, "step_name": step.upper()}, at=started)
            current = step
        seq += 1
        CallEvent.objects.create(call=call, seq=seq, type="turn", payload={"speaker": speaker, "text": text},
                                 at=started + timedelta(seconds=5 * i + 1))
    if report:
        CallReport.objects.create(call=call, disposition="INTERESTED", data={
            "room": room, "disposition": "INTERESTED", "mood": {"final": "happy"},
            "latency": {"llm_ttft": {"p50_ms": 420, "p95_ms": 900, "n": 3}}, "behavior": {"interruptions": 0},
            "dead_air": [{"action": "nudge", "silence_s": 6.0}],
            "response_gap": {"n": 3, "system": {"avg_ms": 900, "p50_ms": 850, "p95_ms": 1300, "max_ms": 1300},
                             "perceived": {"p50_ms": "x"}, "slow_replies": 0, "agent_cut_ins": 1,
                             "replies": [{"at_s": 1.0, "system_ms": 850, "perceived_ms": 850}]}})
    return call


@pytest.fixture
def gemini(monkeypatch, settings):
    """Runs audits inline and answers with ``calls.out`` (or raises ``calls.error``)."""
    settings.GOOGLE_API_KEY = "test-key"
    settings.AUDIT_LLM_MODEL = "gemini-test"

    class Calls(list):
        out = GEMINI_OUT
        error = None

    calls = Calls()

    def fake(prompt, timeout_s):
        calls.append(prompt)
        if calls.error:
            raise calls.error
        return copy.deepcopy(calls.out), {"input": 100, "output": 50}

    monkeypatch.setattr(run, "call_gemini", fake)
    monkeypatch.setattr(run, "start", run.run)
    return calls


@pytest.fixture
def audits_on(workspace):
    workspace.audit_enabled = True
    workspace.save()
    return workspace


# --- input ------------------------------------------------------------------------------------------

def test_build_tags_agent_lines_with_their_step(workspace):
    call = make_call(workspace, version=make_version(workspace))
    inp = build.build(call)
    assert [(ln.speaker, ln.step_id) for ln in inp.lines] == [
        ("agent", "s1"), ("caller", ""), ("agent", "s2"), ("caller", ""), ("agent", "s3"), ("caller", "")]
    assert inp.lines[2].step_name == "Ask city"  # the snapshot's name, not the event's
    assert inp.lines[2].at_s == 11.0 and inp.agent_turns == 3
    assert inp.signals["latency"] == {"llm_ttft": {"p50_ms": 420, "p95_ms": 900, "n": 3}}
    assert inp.signals["dead_air"] == [{"action": "nudge", "silence_s": 6.0}]
    # Summary only (no per-reply list); non-numbers dropped.
    assert inp.signals["response_gap"] == {
        "system": {"avg_ms": 900, "p50_ms": 850, "p95_ms": 1300, "max_ms": 1300},
        "n": 3, "slow_replies": 0, "agent_cut_ins": 1}
    assert [s["id"] for s in inp.workflow["steps"]][:2] == ["s1", "s2"]
    prompt = build.prompt_for(inp, "Our callers are drivers.")
    assert '"step_id": "s2"' in prompt and "Our callers are drivers." in prompt


def test_build_falls_back_to_report_turns(workspace):
    call = make_call(workspace, lines=[], report=False)
    CallReport.objects.create(call=call, data={"turns": [
        {"role": "assistant", "text": "Hello ji", "at_s": 1.5}, {"role": "user", "text": "haan", "at_s": 3},
        {"role": "system", "text": "ignored", "at_s": 4}]})
    lines = build.build(call).lines
    assert [(ln.speaker, ln.text, ln.at_s) for ln in lines] == [("agent", "Hello ji", 1.5), ("caller", "haan", 3)]
    assert lines[0].at == T0 + timedelta(seconds=1.5)


def test_long_transcripts_keep_the_start_and_the_end():
    lines = [build.Line(i, "agent", "x" * 100, None, None) for i in range(100)]
    kept, omitted = build.trim(lines, budget=2000)
    assert kept[0].i == 0 and kept[-1].i == 99 and omitted == (8, 80) and len(kept) == 20


# --- validation -------------------------------------------------------------------------------------

def test_scorecard_keeps_only_verbatim_quotes_and_snaps_lines(workspace):
    inp = build.build(make_call(workspace, version=make_version(workspace)))
    data = copy.deepcopy(GEMINI_OUT)
    data["scores"]["listening"]["evidence"][0]["line"] = 0  # wrong line: the quote is in line 2
    card = scorecard(data, inp, DEFAULT_WEIGHTS)
    ev = card["scores"]["listening"]["evidence"][0]
    assert ev["line"] == 2 and ev["step_id"] == "s2"
    assert datetime.fromisoformat(ev["at"]) == T0 + timedelta(seconds=11)
    assert card["scores"]["pacing"]["evidence"][0]["event"] == "latency"
    # the invented moment is dropped; the rest are kept in call order
    assert [(m["line"], m["kind"]) for m in card["moments"]] == [(0, "good"), (4, "problem")]
    assert card["moments"][1]["step_id"] == "s3"
    assert card["overall_score"] == overall({k: v["score"] for k, v in card["scores"].items()}, DEFAULT_WEIGHTS)


def test_score_without_evidence_is_not_kept(workspace):
    inp = build.build(make_call(workspace))
    data = copy.deepcopy(GEMINI_OUT)
    data["scores"]["accuracy"]["evidence"] = [{"line": 0, "quote": "not said", "kind": "good", "note": ""}]
    data["scores"]["empathy"]["evidence"] = [{"line": 1, "quote": "haan boliye", "kind": "good", "note": ""}]
    card = scorecard(data, inp, DEFAULT_WEIGHTS)
    assert card["scores"]["accuracy"]["score"] is None  # quote not in the transcript
    assert card["scores"]["empathy"]["score"] is None  # score evidence must quote the agent, not the caller
    for key in ("naturalness", "listening", "flow"):
        data["scores"][key]["score"] = 9
    with pytest.raises(Invalid):
        scorecard(data, inp, DEFAULT_WEIGHTS)


def test_overall_score_is_a_weighted_average():
    assert overall(dict.fromkeys(AREA_KEYS, 5), DEFAULT_WEIGHTS) == 100
    assert overall(dict.fromkeys(AREA_KEYS, 1), DEFAULT_WEIGHTS) == 0
    assert overall({"naturalness": 5, "accuracy": 1}, DEFAULT_WEIGHTS) == round(25 * 100 / 35)
    assert overall({}, DEFAULT_WEIGHTS) is None


# --- triggers ---------------------------------------------------------------------------------------

def store(room, capture):
    with capture(execute=True):
        CallReport.store({"room": room, "disposition": "INTERESTED"})


def test_report_queues_an_audit_once(audits_on, gemini, django_capture_on_commit_callbacks):
    call = make_call(audits_on, version=make_version(audits_on), report=False)
    store(call.room, django_capture_on_commit_callbacks)
    audit = CallAudit.objects.get(call=call)
    assert audit.status == CallAudit.READY and audit.is_current and audit.created_by is None
    assert 0 <= audit.overall_score <= 100 and audit.tokens_in == 100 and audit.model == "gemini-test"
    assert audit.agent_version_id == call.agent_version_id
    store(call.room, django_capture_on_commit_callbacks)  # a re-sent report
    assert CallAudit.objects.filter(call=call).count() == 1 and len(gemini) == 1


def test_audits_off_never_calls_gemini(workspace, gemini, django_capture_on_commit_callbacks):
    call = make_call(workspace, report=False)
    store(call.room, django_capture_on_commit_callbacks)
    assert not CallAudit.objects.exists() and gemini == []


def test_sampling_is_stable_per_call(audits_on, gemini, django_capture_on_commit_callbacks):
    audits_on.audit_sample_pct = 10
    audits_on.save()
    rooms = [f"room-{i}" for i in range(40)]
    for room in rooms:
        make_call(audits_on, room=room, report=False)
        store(room, django_capture_on_commit_callbacks)
    audited = set(CallAudit.objects.values_list("call__room", flat=True))
    assert audited == {r for r in rooms if run.sampled(r, 10)} and len(audited) < 40


def test_short_calls_are_skipped_without_gemini(audits_on, gemini, django_capture_on_commit_callbacks):
    call = make_call(audits_on, lines=LINES[:2], report=False)
    store(call.room, django_capture_on_commit_callbacks)
    audit = CallAudit.objects.get(call=call)
    assert audit.status == CallAudit.SKIPPED and audit.skipped_reason == CallAudit.TOO_SHORT and gemini == []


def test_gemini_failure_is_an_audit_error_not_an_ingest_error(audits_on, gemini, client,
                                                             django_capture_on_commit_callbacks):
    gemini.error = RuntimeError("boom")
    call = make_call(audits_on, report=False)
    store(call.room, django_capture_on_commit_callbacks)
    audit = CallAudit.objects.get(call=call)
    assert audit.status == CallAudit.ERROR and audit.error == run.ERROR_FAILED
    assert len(gemini) == 2  # retried once


def test_busy_gemini_is_tried_again_later(audits_on, gemini, django_capture_on_commit_callbacks):
    gemini.error = RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
    call = make_call(audits_on, report=False)
    store(call.room, django_capture_on_commit_callbacks)
    audit = CallAudit.objects.get(call=call)
    assert audit.status == CallAudit.QUEUED and audit.attempts == 1 and audit.error == ""
    gemini.error = None
    CallAudit.objects.filter(pk=audit.pk).update(updated_at=timezone.now() - timedelta(minutes=6))
    assert run.sweep() == 1
    audit.refresh_from_db()
    assert audit.status == CallAudit.READY and audit.attempts == 2


def test_retired_model_has_a_clear_error(audits_on, gemini, django_capture_on_commit_callbacks):
    gemini.error = RuntimeError("404 NOT_FOUND. models/gemini-old is not found")
    call = make_call(audits_on, report=False)
    store(call.room, django_capture_on_commit_callbacks)
    assert CallAudit.objects.get(call=call).error == run.ERROR_MODEL and len(gemini) == 1


def test_missing_api_key(audits_on, gemini, settings, django_capture_on_commit_callbacks):
    settings.GOOGLE_API_KEY = ""
    call = make_call(audits_on, report=False)
    store(call.room, django_capture_on_commit_callbacks)
    assert CallAudit.objects.get(call=call).error == run.ERROR_NO_KEY and gemini == []


def test_queue_failure_never_breaks_ingest(audits_on, monkeypatch, client, django_capture_on_commit_callbacks):
    def broken(*a, **k):
        raise RuntimeError("db gone")

    monkeypatch.setattr(run, "create", broken)
    make_call(audits_on, report=False)
    store("r1", django_capture_on_commit_callbacks)  # does not raise
    assert CallReport.objects.filter(call__room="r1").exists()


def test_sweep_requeues_stuck_audits_then_gives_up(workspace, gemini):
    call = make_call(workspace)
    audit = run.create(call)
    old = timezone.now() - timedelta(minutes=10)
    CallAudit.objects.filter(pk=audit.pk).update(status=CallAudit.RUNNING, attempts=1, updated_at=old)
    assert run.sweep() == 1
    audit.refresh_from_db()
    assert audit.status == CallAudit.READY and audit.attempts == 2
    CallAudit.objects.filter(pk=audit.pk).update(status=CallAudit.RUNNING, attempts=3, updated_at=old)
    assert run.sweep() == 1
    audit.refresh_from_db()
    assert audit.status == CallAudit.ERROR and audit.error == run.ERROR_TOO_LONG


def test_a_late_run_does_not_overwrite_a_newer_attempt(workspace, gemini):
    audit = run.create(make_call(workspace))
    attempt = run._claim(audit.pk)
    CallAudit.objects.filter(pk=audit.pk).update(attempts=attempt + 1)  # the sweep took it over
    assert run._finish(audit.pk, attempt, status=CallAudit.READY) is False


# --- API --------------------------------------------------------------------------------------------

def test_api_runs_and_reads_an_audit(member, workspace, gemini):
    call = make_call(workspace, version=make_version(workspace))
    viewer, editor = member("viewer"), member("editor")
    assert viewer.get(f"/api/calls/{call.room}/audit").json() == {"status": "none", "enabled": False}
    assert viewer.post(f"/api/calls/{call.room}/audit").status_code == 403
    r = editor.post(f"/api/calls/{call.room}/audit")
    assert r.status_code == 202 and r.json()["status"] == "ready" and r.json()["automatic"] is False
    body = viewer.get(f"/api/calls/{call.room}/audit").json()
    assert [a["key"] for a in body["areas"]] == AREA_KEYS
    assert body["areas"][0] == {"key": "naturalness", "label": "Sounds human", "weight": 25, "score": 3,
                                "summary": "problem work", "evidence": body["areas"][0]["evidence"]}
    assert body["moments"][0]["quote"] == "Namaste!" and body["overall_score"] is not None
    first = CallAudit.objects.get()
    # re-audit: a new current audit, the old one kept for history
    assert editor.post(f"/api/calls/{call.room}/audit").status_code == 202
    assert CallAudit.objects.count() == 2
    first.refresh_from_db()
    assert first.is_current is False


def test_second_run_while_one_is_running_is_409(member, workspace, monkeypatch):
    monkeypatch.setattr(run, "start", lambda audit_id: None)  # never finishes
    call = make_call(workspace)
    editor = member("editor")
    assert editor.post(f"/api/calls/{call.room}/audit").json()["status"] == "queued"
    assert editor.post(f"/api/calls/{call.room}/audit").status_code == 409


def test_audits_are_workspace_scoped(member, other_workspace, gemini):
    call = make_call(other_workspace)
    run.run(run.create(call).pk)
    assert_isolated(member("editor"), f"/api/calls/{call.room}/audit")
    assert member("editor").post(f"/api/calls/{call.room}/audit").status_code == 404


def test_call_list_has_score_and_filters(member, workspace, gemini):
    good, bad = make_call(workspace, room="good"), make_call(workspace, room="bad")
    make_call(workspace, room="none")
    for call, score in ((good, 90), (bad, 40)):
        a = run.create(call)
        CallAudit.objects.filter(pk=a.pk).update(status=CallAudit.READY, overall_score=score)
    c = member("viewer")
    rows = {r["room"]: r["audit_score"] for r in c.get("/api/calls").json()["results"]}
    assert rows == {"good": 90, "bad": 40, "none": None}
    assert [r["room"] for r in c.get("/api/calls", {"score_max": 59}).json()["results"]] == ["bad"]
    assert [r["room"] for r in c.get("/api/calls", {"score_min": 80}).json()["results"]] == ["good"]
    assert c.get("/api/calls", {"score_min": 101}).status_code == 400
    assert c.get("/api/calls", {"score_min": 70, "score_max": 50}).status_code == 400


def test_workspace_audit_settings(member):
    assert member("editor").patch("/api/workspace", {"audit_enabled": True}, format="json").status_code == 403
    admin = member("admin")
    r = admin.patch("/api/workspace", {"audit_enabled": True, "audit_sample_pct": 25,
                                       "audit_weights": {"naturalness": 40}, "audit_instructions": "Keep it informal."},
                    format="json")
    assert r.status_code == 200
    body = r.json()
    assert body["audit_enabled"] is True and body["audit_sample_pct"] == 25
    assert body["audit_weights"]["naturalness"] == 40 and body["audit_weights"]["listening"] == 20
    assert admin.patch("/api/workspace", {"audit_sample_pct": 33}, format="json").status_code == 400
    assert admin.patch("/api/workspace", {"audit_weights": {"vibes": 3}}, format="json").status_code == 400
    assert admin.patch("/api/workspace", {"audit_weights": {"accuracy": 101}}, format="json").status_code == 400


# --- retention --------------------------------------------------------------------------------------

def test_purge_blanks_audit_quotes_but_keeps_scores(workspace, gemini):
    old = make_call(workspace, room="old", started=timezone.now() - timedelta(days=91))
    new = make_call(workspace, room="new", started=timezone.now() - timedelta(days=1))
    for call in (old, new):
        run.run(run.create(call).pk)
    call_command("purge_old_call_data", stdout=StringIO())
    a = CallAudit.objects.get(call=old)
    assert a.quotes_purged and a.summary == "" and a.overall_score is not None
    assert all(m["quote"] == "" for m in a.moments) and a.moments[0]["step_id"] == "s1"
    assert all(e["quote"] == "" for s in a.scores.values() for e in s["evidence"])
    assert a.scores["naturalness"]["score"] == 3
    b = CallAudit.objects.get(call=new)
    assert not b.quotes_purged and b.summary
