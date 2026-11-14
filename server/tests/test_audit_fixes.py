"""Audit fixes (KAP-37), with Gemini mocked: generation, validation, ranking, accept / edit / dismiss, auto-apply,
which fixes went into each version and before/after scores."""
import copy
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from audits import fixes
from audits.models import AgentSuggestion, AuditFixRun, CallAudit
from audits.rubric import DEFAULT_WEIGHTS
from audits.run import _workflow_revision
from calls.models import Call
from knowledge.models import KnowledgeDocument
from tests.helpers import assert_isolated
from tests.test_publish import BODY, make_agent, make_workflow
from voiceagents.publish import is_outdated, publish
from voiceagents.suggestions import Invalid as AgentInvalid
from voiceagents.suggestions import validate_settings, validate_script
from workflows.models import WorkflowSuggestion, WorkflowSuggestionSet
from workflows.suggestions import Invalid, validate_prompt

pytestmark = pytest.mark.django_db

NEW_BODY = "Namaste! [[expr:happy]] Aap {{lead.city}} se hain? Theek hai, main bas do minute lungi."


def scores(**override):
    base = {k: {"score": 4, "summary": "fine", "evidence": []} for k in DEFAULT_WEIGHTS}
    for k, v in override.items():
        base[k] = v
    return base


def moment(line, area, step_id, quote, note="stuck"):
    return {"line": line, "at": f"00:{line:02d}", "at_s": float(line), "kind": "problem", "area": area,
            "step_id": step_id, "step_name": step_id.upper(), "quote": quote, "note": note}


PRICE = moment(4, "flow", "s4", "Here is the plan.", "repeated the plan when asked about the price")
STIFF = moment(0, "naturalness", "s1", "I am calling from Northwind", "sounded read aloud")


def make_audit(workspace, version, room, moments=(PRICE,), purged=False, overall=55, **score_override):
    now = timezone.now()
    call = Call.objects.create(room=room, workspace=workspace, started_at=now, answered_at=now,
                               ended_at=now + timedelta(minutes=2), caller="+919876543210", agent_version=version)
    flow = {"score": 2, "summary": "looped at the plan", "evidence": [{**PRICE, "kind": "problem"}]}
    sc = scores(**{"flow": flow, **score_override})
    return CallAudit.objects.create(
        call=call, workspace=workspace, agent_version=version, workflow_revision=_workflow_revision(version),
        status=CallAudit.READY, overall_score=overall, scores=sc, weights=dict(DEFAULT_WEIGHTS),
        moments=[dict(m) for m in moments], quotes_purged=purged, finished_at=now, summary="s",
    )


def fix(kind, ids, **kw):
    return {"kind": kind, "title": f"{kind} fix", "area": kw.pop("area", "flow"), "problem_ids": ids,
            "confidence": kw.pop("confidence", 0.9), "reason": "callers ask about the price here.", **kw}


def problem_ids(prompt, area=None):
    data = json.loads(prompt.split("\n\n", 1)[1])
    return [p["id"] for p in data["problems"] if area is None or p["area"] == area]


@pytest.fixture
def gemini(monkeypatch, settings):
    """Runs generation inline. ``calls.out`` is the output, or a function of the prompt that returns it."""
    settings.GOOGLE_API_KEY = "test-key"

    class Calls(list):
        out = {"fixes": []}
        error = None

    calls = Calls()

    def fake(prompt, timeout_s):
        calls.append(prompt)
        if calls.error:
            raise calls.error
        out = calls.out(prompt) if callable(calls.out) else calls.out
        return copy.deepcopy(out), {"input": 100, "output": 50}

    monkeypatch.setattr(fixes, "call_gemini", fake)
    monkeypatch.setattr(fixes, "start", fixes.generate)
    return calls


@pytest.fixture
def agent(workspace, member):
    c = member("editor")
    wf = make_workflow(workspace)
    a = make_agent(workspace, workflow=wf)
    publish(a, c.user)
    a.refresh_from_db()
    a.client = c
    return a


def suggest_call(c, room, capture):
    with capture(execute=True):
        return c.post(f"/api/calls/{room}/audit/fixes", format="json")


def suggest_batch(c, agent, capture, **body):
    with capture(execute=True):
        return c.post(f"/api/agents/{agent.id}/audit-fixes", body, format="json")


def single_call_out(prompt):
    ids = problem_ids(prompt)
    return {"fixes": [
        fix("answer", ids[:1], step_id="s4", label="Asks about the price", examples=["kitna milega", "price kya hai"],
            new_step={"name": "Explain pay", "type": "prompt", "prompt": "Har hafte payout milta hai.",
                      "then_step_id": "e3", "then_label": "understood"}),
        fix("prompt", ids[:1], step_id="s4", after="Plan simple hai ji. [[expr:happy]] Har hafte payout milta hai."),
        fix("script", ids[-1:], area="naturalness", section_id="s1", after=NEW_BODY),
        fix("knowledge", ids[:1], knowledge_title="Pay and price", knowledge_body="Payouts are weekly."),
        fix("settings", ids[-1:], area="naturalness", settings={"name_pronunciation": "Pree-ya"}),
        # Invalid: bad step, unknown expression, too long, no supporting moments.
        fix("answer", ids[:1], step_id="nope", label="x", examples=["y"], target_step_id="t1"),
        fix("expression", ids[:1], step_id="s4", after="[[expr:dance]] Here is the plan."),
        fix("prompt", ids[:1], step_id="s1", after="Namaste " * 400),
        fix("script", [], section_id="s1", after="Hello"),
    ]}


# --- generation -------------------------------------------------------------------------------------

def test_suggest_fixes_from_one_call(agent, workspace, gemini, django_capture_on_commit_callbacks):
    c = agent.client
    make_audit(workspace, agent.published_version, "r1", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    r = suggest_call(c, "r1", django_capture_on_commit_callbacks)
    assert r.status_code == 202, r.content
    assert r.json()["status"] == "running"
    body = c.get(f"/api/calls/r1/audit/fixes").json()
    assert body["status"] == "ready" and body["scope"] == "call" and body["call"] == "r1"
    assert body["agent_version"] == 1 and body["calls"] == 1 and body["dropped"] == 4
    kinds = sorted((i["target"], i["kind"]) for i in body["items"])
    assert kinds == [("agent", "knowledge"), ("agent", "script"), ("agent", "settings"),
                     ("workflow", "answer"), ("workflow", "prompt")]
    for item in body["items"]:
        assert item["status"] == "pending" and item["invalid_reason"] == ""
        assert item["evidence"] and item["evidence"][0]["call"] == "r1" and item["evidence"][0]["quote"]
        assert item["calls"] == 1 and item["pool"] == 1
    answer = next(i for i in body["items"] if i["kind"] == "answer")
    assert answer["step_name"] == "Explain the plan"
    assert answer["payload"]["target"]["new_step"]["then"] == {"step_id": "e3", "label": "understood"}
    assert answer["evidence"][0]["line"] == 4 and answer["evidence"][0]["step_id"] == "s4"
    # The prompt Gemini saw: the draft, the problems and the low area; the line-4 moment and the flow evidence
    # for the same line count once.
    data = json.loads(gemini[0].split("\n\n", 1)[1])
    assert len(data["problems"]) == 2 and data["low_scoring_areas"][0]["area"] == "flow"
    assert data["agent"]["script"][0]["id"] == "s1" and data["workflow"]["steps"][0]["id"] == "s1"
    # Nothing changed yet; the audit-fix set stays out of the workflow editor's Suggest with AI draft.
    assert agent.workflow.current.number == 1
    assert c.get(f"/api/workflows/{agent.workflow_id}/suggestions/current").status_code == 204
    assert WorkflowSuggestionSet.objects.get(audit_run_id=body["id"]).source == "audit"


def test_batch_groups_repeated_problems_and_ranks(agent, workspace, gemini, django_capture_on_commit_callbacks):
    c = agent.client
    v = agent.published_version
    for i in range(3):
        make_audit(workspace, v, f"price{i}", purged=(i == 0))
    make_audit(workspace, v, "stiff", moments=(STIFF,), flow={"score": 4, "summary": "ok", "evidence": []},
               naturalness={"score": 3, "summary": "stiff", "evidence": []})
    gemini.out = lambda p: {"fixes": [
        fix("prompt", problem_ids(p, "naturalness"), area="naturalness", step_id="s1",
            after="Namaste ji! [[expr:happy]] Northwind se bol rahi hoon."),
        fix("answer", problem_ids(p, "flow"), step_id="s4", label="Asks about the price",
            examples=["kitna milega"], target_step_id="e2"),
    ]}
    r = suggest_batch(c, agent, django_capture_on_commit_callbacks, limit=10)
    assert r.status_code == 202, r.content
    body = c.get(f"/api/agents/{agent.id}/audit-fixes").json()
    assert body["scope"] == "batch" and body["calls"] == 4
    first, second = body["items"]
    assert (first["kind"], first["calls"], first["pool"]) == ("answer", 3, 4)  # 3 of 4 calls
    assert (second["kind"], second["calls"]) == ("prompt", 1)
    assert first["rank_score"] > second["rank_score"] > 0
    # Purged audits count toward how often, but their quotes aren't evidence and never reach Gemini.
    assert sorted(e["call"] for e in first["evidence"]) == ["price1", "price2"]
    data = json.loads(gemini[0].split("\n\n", 1)[1])
    purged = [p for p in data["problems"] if p["area"] == "flow" and "quote" not in p]
    assert len(purged) == 1 and data["calls_audited"] == 4


def test_batch_by_workflow_revision_and_errors(agent, workspace, gemini, django_capture_on_commit_callbacks):
    c = agent.client
    r = suggest_batch(c, agent, django_capture_on_commit_callbacks)
    assert r.status_code == 409 and "No audited calls" in r.json()["detail"]
    make_audit(workspace, agent.published_version, "r1")
    gemini.out = lambda p: {"fixes": []}
    r = suggest_batch(c, agent, django_capture_on_commit_callbacks, by="workflow_revision")
    assert r.status_code == 202
    assert c.get(f"/api/audit-fixes/{r.json()['id']}").json()["status"] == "empty"
    gemini.error = TimeoutError("slow")
    r = suggest_batch(c, agent, django_capture_on_commit_callbacks)
    body = c.get(f"/api/audit-fixes/{r.json()['id']}").json()
    assert body["status"] == "error" and body["error"] == fixes.ERROR_FAILED
    assert suggest_batch(c, agent, django_capture_on_commit_callbacks, limit=0).status_code == 400


def test_call_needs_a_ready_audit_with_problems_on_the_latest_version(agent, workspace, gemini,
                                                                       django_capture_on_commit_callbacks):
    c = agent.client
    a = make_audit(workspace, agent.published_version, "r1", moments=())
    a.scores = scores()
    a.save()
    r = suggest_call(c, "r1", django_capture_on_commit_callbacks)
    assert r.status_code == 409 and "no problems" in r.json()["detail"]
    make_audit(workspace, agent.published_version, "r2")
    publish(agent, c.user)  # v2: v1's problems may be fixed already
    r = suggest_call(c, "r2", django_capture_on_commit_callbacks)
    assert r.status_code == 409 and "v1" in r.json()["detail"] and "v2" in r.json()["detail"]
    assert not gemini


def test_suggest_fixes_from_a_voice_test_call(agent, workspace, gemini, other_workspace,
                                              django_capture_on_commit_callbacks):
    """A voice test (`web-<agent>-…` room) ran on the draft, with no version: fixes still come from its audit."""
    c = agent.client
    make_audit(workspace, None, f"web-{agent.id}-0aabb8b2", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    r = suggest_call(c, f"web-{agent.id}-0aabb8b2", django_capture_on_commit_callbacks)
    assert r.status_code == 202, r.content
    body = c.get(f"/api/calls/web-{agent.id}-0aabb8b2/audit/fixes").json()
    assert body["status"] == "ready" and body["agent"]["id"] == agent.id and body["agent_version"] is None
    assert {i["target"] for i in body["items"]} == {"agent", "workflow"}
    # Another workspace's agent id in the room name, or no agent id at all: still refused.
    other = make_agent(other_workspace)
    for room in (f"web-{other.id}-1234abcd", "web-x-1234abcd", "phone-1"):
        make_audit(workspace, None, room)
        r = suggest_call(c, room, django_capture_on_commit_callbacks)
        assert r.status_code == 409 and "published agent" in r.json()["detail"]


def test_daily_limit_and_permissions(agent, workspace, member, settings, gemini, other_workspace,
                                     django_capture_on_commit_callbacks):
    c = agent.client
    settings.AUDIT_FIX_DAILY_LIMIT = 1
    make_audit(workspace, agent.published_version, "r1")
    gemini.out = single_call_out
    run_id = suggest_call(c, "r1", django_capture_on_commit_callbacks).json()["id"]
    assert suggest_call(c, "r1", django_capture_on_commit_callbacks).status_code == 429
    viewer = member("viewer")
    assert viewer.get(f"/api/audit-fixes/{run_id}").status_code == 200
    assert viewer.post(f"/api/calls/r1/audit/fixes").status_code == 403
    item = c.get(f"/api/audit-fixes/{run_id}").json()["items"][0]
    assert viewer.post(f"/api/audit-fixes/{run_id}/{item['target']}/{item['id']}/accept").status_code == 403

    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient
    from workspaces.models import Membership

    outsider = get_user_model().objects.create_user(username="o@x.com", email="o@x.com", password="pw-test-12345")
    Membership.objects.create(user=outsider, workspace=other_workspace, role="editor")
    oc = APIClient()
    oc.force_login(outsider)
    assert_isolated(oc, f"/api/audit-fixes/{run_id}")
    assert_isolated(oc, f"/api/agents/{agent.id}/audit-fixes")


# --- accept / edit / dismiss ------------------------------------------------------------------------

def _items(c, run_id):
    return {i["kind"]: i for i in c.get(f"/api/audit-fixes/{run_id}").json()["items"]}


def _url(run_id, item, action=""):
    return f"/api/audit-fixes/{run_id}/{item['target']}/{item['id']}" + (f"/{action}" if action else "")


def test_accept_writes_to_the_draft_only(agent, workspace, gemini, django_capture_on_commit_callbacks):
    c = agent.client
    make_audit(workspace, agent.published_version, "r1", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    run_id = suggest_call(c, "r1", django_capture_on_commit_callbacks).json()["id"]
    snapshot = copy.deepcopy(agent.published_version.snapshot)
    items = _items(c, run_id)

    r = c.post(_url(run_id, items["answer"], "accept"))
    assert r.status_code == 200, r.content
    accepted = next(i for i in r.json()["items"] if i["kind"] == "answer")
    assert accepted["status"] == "accepted" and accepted["applied_revision"] == 2
    graph = agent.workflow.current.graph
    new = graph["steps"][-1]
    assert (new["id"], new["name"], new["type"], new["prompt"]) == (
        "explain-pay-fix1", "Explain pay", "prompt", "Har hafte payout milta hai.")
    assert {"from": "explain-pay-fix1", "to": "e3", "label": "understood"}.items() <= graph["paths"][-2].items()
    assert {"from": "s4", "to": "explain-pay-fix1", "label": "Asks about the price",
            "examples": ["kitna milega", "price kya hai"]}.items() <= graph["paths"][-1].items()
    from workflows.api import validate_for
    assert validate_for(agent.workflow, graph) == []
    assert c.post(_url(run_id, items["answer"], "accept")).status_code == 409

    assert c.post(_url(run_id, items["prompt"], "accept")).status_code == 200
    s4 = next(s for s in agent.workflow.current.graph["steps"] if s["id"] == "s4")
    assert s4["prompt"].startswith("Plan simple hai ji.") and agent.workflow.current.number == 3

    assert c.post(_url(run_id, items["script"], "accept")).status_code == 200
    assert c.post(_url(run_id, items["knowledge"], "accept")).status_code == 200
    assert c.post(_url(run_id, items["settings"], "accept")).status_code == 200
    agent.refresh_from_db()
    assert agent.script[0]["body"] == NEW_BODY and agent.settings["name_pronunciation"] == "Pree-ya"
    doc = KnowledgeDocument.objects.get(workspace=workspace, title="Pay and price")
    assert doc.current.body_md == "Payouts are weekly." and doc in agent.knowledge.all()

    # Callers still get v1 until someone publishes.
    agent.published_version.refresh_from_db()
    assert agent.published_version.number == 1 and agent.published_version.snapshot == snapshot
    assert is_outdated(agent)


def test_edit_dismiss_restore_and_stale(agent, workspace, gemini, django_capture_on_commit_callbacks):
    c = agent.client
    make_audit(workspace, agent.published_version, "r1", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    run_id = suggest_call(c, "r1", django_capture_on_commit_callbacks).json()["id"]
    items = _items(c, run_id)
    prompt = items["prompt"]

    bad = {**prompt["payload"], "after": "[[expr:dance]] hi"}
    r = c.patch(_url(run_id, prompt), {"edited_payload": bad}, format="json")
    assert r.status_code == 400 and "Unknown expression" in r.json()["after"][0]
    good = {**prompt["payload"], "after": "Plan simple hai ji."}
    r = c.patch(_url(run_id, prompt), {"edited_payload": good}, format="json")
    edited = next(i for i in r.json()["items"] if i["kind"] == "prompt")
    assert edited["edited"] and edited["payload"]["after"] == "Plan simple hai ji."
    assert c.post(_url(run_id, prompt, "accept")).status_code == 200
    s4 = next(s for s in agent.workflow.current.graph["steps"] if s["id"] == "s4")
    assert s4["prompt"] == "Plan simple hai ji."

    script = items["script"]
    r = c.patch(_url(run_id, script), {"status": "dismissed"}, format="json")
    assert next(i for i in r.json()["items"] if i["kind"] == "script")["status"] == "dismissed"
    assert c.post(_url(run_id, script, "accept")).status_code == 409
    r = c.patch(_url(run_id, script), {"status": "pending"}, format="json")
    assert next(i for i in r.json()["items"] if i["kind"] == "script")["status"] == "pending"

    # The editor changes the section by hand: the fix is out of date and can't be accepted.
    c.patch(f"/api/agents/{agent.id}", {"script": [{"id": "s1", "title": "Opening", "body": "Hello"}]},
            format="json")
    item = _items(c, run_id)["script"]
    assert item["invalid_reason"] == "This script section has changed since."
    r = c.post(_url(run_id, script, "accept"))
    assert r.status_code == 409 and r.json()["detail"] == "This script section has changed since."


# --- auto-apply -------------------------------------------------------------------------------------

def _batch_out(p):
    return {"fixes": [
        fix("answer", problem_ids(p, "flow"), step_id="s4", label="Asks about the price", examples=["kitna milega"],
            target_step_id="e2", confidence=0.95),
        fix("script", problem_ids(p, "flow")[:1], section_id="s1", after=NEW_BODY, confidence=0.95),  # 1 call
        fix("knowledge", problem_ids(p, "flow"), knowledge_title="Pay", knowledge_body="Weekly.", confidence=0.5),
    ]}


def test_auto_apply_is_off_by_default(agent, workspace, gemini, django_capture_on_commit_callbacks):
    assert workspace.audit_fix_auto_apply is False
    assert agent.client.get("/api/workspace").json()["audit_fix_auto_apply"] is False
    for i in range(3):
        make_audit(workspace, agent.published_version, f"r{i}")
    gemini.out = _batch_out
    run_id = suggest_batch(agent.client, agent, django_capture_on_commit_callbacks).json()["id"]
    body = agent.client.get(f"/api/audit-fixes/{run_id}").json()
    assert body["auto_applied"] == 0 and all(i["status"] == "pending" for i in body["items"])
    assert agent.workflow.current.number == 1


def test_auto_apply_writes_confident_repeated_fixes_to_the_draft(agent, workspace, member, settings, gemini,
                                                                  django_capture_on_commit_callbacks):
    owner = member("owner")
    assert owner.patch("/api/workspace", {"audit_fix_auto_apply": True}, format="json").json()[
        "audit_fix_auto_apply"] is True
    settings.AUDIT_FIX_AUTO_MIN_CONFIDENCE, settings.AUDIT_FIX_AUTO_MIN_CALLS = 0.8, 3
    for i in range(3):
        make_audit(workspace, agent.published_version, f"r{i}")
    gemini.out = _batch_out
    snapshot = copy.deepcopy(agent.published_version.snapshot)
    run_id = suggest_batch(agent.client, agent, django_capture_on_commit_callbacks).json()["id"]
    body = agent.client.get(f"/api/audit-fixes/{run_id}").json()
    by_kind = {i["kind"]: i for i in body["items"]}
    assert body["auto_applied"] == 1
    assert by_kind["answer"]["status"] == "accepted" and by_kind["answer"]["auto_applied"]
    assert by_kind["script"]["status"] == "pending"  # one call: not repeated enough
    assert by_kind["knowledge"]["status"] == "pending"  # not confident enough
    assert WorkflowSuggestion.objects.get(pk=by_kind["answer"]["id"]).decided_by is None
    assert agent.workflow.current.number == 2
    agent.published_version.refresh_from_db()
    agent.refresh_from_db()
    assert agent.published_version.snapshot == snapshot and agent.published_version.number == 1


# --- did it help? -----------------------------------------------------------------------------------

def test_versions_show_their_fixes_and_score_change(agent, workspace, settings, gemini,
                                                    django_capture_on_commit_callbacks):
    c = agent.client
    settings.AUDIT_FIX_MIN_CALLS_FOR_SCORES = 2
    v1 = agent.published_version
    make_audit(workspace, v1, "a1", moments=(PRICE, STIFF), overall=40)
    gemini.out = single_call_out
    run_id = suggest_call(c, "a1", django_capture_on_commit_callbacks).json()["id"]
    items = _items(c, run_id)
    c.post(_url(run_id, items["answer"], "accept"))
    c.post(_url(run_id, items["script"], "accept"))
    c.patch(_url(run_id, items["knowledge"]), {"status": "dismissed"}, format="json")
    assert c.post(f"/api/agents/{agent.id}/publish").status_code == 200

    versions = c.get(f"/api/agents/{agent.id}/versions").json()
    v2, first = versions
    assert v2["number"] == 2 and first["number"] == 1 and first["compared_to"] is None
    assert sorted(f["kind"] for f in v2["audit_fixes"]) == ["answer", "script"]
    assert v2["compared_to"]["version"] == 1 and v2["compared_to"]["enough"] is False
    assert v2["compared_to"]["change"] is None and v2["min_calls"] == 2

    agent.refresh_from_db()
    v2_obj = agent.published_version
    make_audit(workspace, v1, "a2", overall=50)
    make_audit(workspace, v2_obj, "b1", overall=80, flow={"score": 4, "summary": "ok", "evidence": []})
    make_audit(workspace, v2_obj, "b2", overall=90, flow={"score": 5, "summary": "ok", "evidence": []})
    v2 = c.get(f"/api/agents/{agent.id}/versions").json()[0]
    assert v2["audit_scores"]["calls"] == 2 and v2["audit_scores"]["overall"] == 85.0
    assert v2["compared_to"]["enough"] is True
    assert v2["compared_to"]["change"]["overall"] == 40.0  # 85 vs 45
    assert v2["compared_to"]["change"]["areas"]["flow"] == 2.5  # 4.5 vs 2

    # A later publish doesn't claim v2's fixes again.
    c.patch(f"/api/agents/{agent.id}", {"name": "Renamed"}, format="json")
    c.post(f"/api/agents/{agent.id}/publish")
    assert c.get(f"/api/agents/{agent.id}/versions").json()[0]["audit_fixes"] == []
    assert AgentSuggestion.objects.get(kind="script").included_in == v2_obj


def test_purge_blanks_quotes_copied_into_fixes(agent, workspace, gemini, django_capture_on_commit_callbacks):
    a = make_audit(workspace, agent.published_version, "r1", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    run_id = suggest_call(agent.client, "r1", django_capture_on_commit_callbacks).json()["id"]
    assert fixes.purge_fix_quotes([a.id]) == 5
    for item in fixes.ranked_items(AuditFixRun.objects.get(pk=run_id)):
        assert all(e["quote"] == "" for e in item.audit["evidence"])


# --- validation -------------------------------------------------------------------------------------

def test_validate_prompt_rules():
    from tests.test_workflow_graph import driver_graph

    g = driver_graph()
    ok = validate_prompt({"before": "Here is the plan.", "after": " Short plan. ", "reason": "r"}, g, "s4")
    assert ok["after"] == "Short plan."
    cases = [
        ({"before": "Here is the plan.", "after": "Here is the plan."}, "s4", "doesn't change"),
        ({"before": "old words", "after": "x"}, "s4", "have changed"),
        ({"before": "Here is the plan.", "after": "Hi {{lead.name}}"}, "s4", "isn't used by this step"),
        ({"before": "Here is the plan.", "after": "[[expr:pause:20]] Hi"}, "s4", "Pause is too long"),
        ({"before": "Here is the plan.", "after": "x" * 2001}, "s4", "2000 characters"),
        ({"before": "", "after": "x"}, "zz", "was removed"),
    ]
    for payload, sid, msg in cases:
        with pytest.raises(Invalid) as e:
            validate_prompt(payload, g, sid)
        assert msg in e.value.reason


def test_validate_agent_fixes(workspace):
    a = make_agent(workspace)
    assert validate_script({"section_id": "s1", "before": BODY, "after": NEW_BODY}, a)["title"] == "Opening"
    with pytest.raises(AgentInvalid, match="was removed"):
        validate_script({"section_id": "zz", "before": BODY, "after": NEW_BODY}, a)
    with pytest.raises(AgentInvalid, match="Unknown expression"):
        validate_script({"section_id": "s1", "before": BODY, "after": "[[expr:dance]] hi"}, a)
    out = validate_settings({"changes": {"language": "English", "mood_adaptation": True},
                             "before": {"language": "Hindi + Hinglish", "mood_adaptation": True}}, a)
    assert out["changes"] == {"language": "English"}  # unchanged values drop out
    with pytest.raises(AgentInvalid, match="can't be changed"):
        validate_settings({"changes": {"voice_id": "x"}, "before": {"voice_id": ""}}, a)
    with pytest.raises(AgentInvalid, match="have changed since"):
        validate_settings({"changes": {"language": "English"}, "before": {"language": "Tamil"}}, a)


# --- review follow-ups ------------------------------------------------------------------------------

def test_a_fix_the_editor_overwrote_is_not_recorded_in_the_version(agent, workspace, gemini,
                                                                   django_capture_on_commit_callbacks):
    c = agent.client
    make_audit(workspace, agent.published_version, "r1", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    run_id = suggest_call(c, "r1", django_capture_on_commit_callbacks).json()["id"]
    items = _items(c, run_id)
    c.post(_url(run_id, items["script"], "accept"))
    c.post(_url(run_id, items["prompt"], "accept"))
    # An editor with a stale copy saves over both.
    c.patch(f"/api/agents/{agent.id}", {"script": [{"id": "s1", "title": "Opening", "body": BODY}]}, format="json")
    from tests.test_workflow_graph import driver_graph
    c.patch(f"/api/workflows/{agent.workflow_id}", {"graph": driver_graph()}, format="json")
    assert c.post(f"/api/agents/{agent.id}/publish").status_code == 200
    assert c.get(f"/api/agents/{agent.id}/versions").json()[0]["audit_fixes"] == []


def test_fixes_for_a_workflow_the_agent_left_cant_be_accepted(agent, workspace, gemini,
                                                               django_capture_on_commit_callbacks):
    c = agent.client
    make_audit(workspace, agent.published_version, "r1", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    run_id = suggest_call(c, "r1", django_capture_on_commit_callbacks).json()["id"]
    other = make_workflow(workspace, name="Other")
    c.patch(f"/api/agents/{agent.id}", {"workflow": other.id}, format="json")
    answer = _items(c, run_id)["answer"]
    assert answer["invalid_reason"] == "The agent no longer uses this workflow."
    r = c.post(_url(run_id, answer, "accept"))
    assert r.status_code == 409 and agent.workflow.current.number == 1


def test_workflow_revision_pool_spanning_versions_keeps_only_workflow_fixes(agent, workspace, gemini,
                                                                           django_capture_on_commit_callbacks):
    c = agent.client
    make_audit(workspace, agent.published_version, "old", moments=(PRICE, STIFF))
    c.patch(f"/api/agents/{agent.id}", {"name": "Renamed"}, format="json")
    c.post(f"/api/agents/{agent.id}/publish")  # v2, same workflow revision
    agent.refresh_from_db()
    make_audit(workspace, agent.published_version, "new", moments=(PRICE, STIFF))
    gemini.out = single_call_out
    run_id = suggest_batch(c, agent, django_capture_on_commit_callbacks, by="workflow_revision").json()["id"]
    body = c.get(f"/api/audit-fixes/{run_id}").json()
    assert body["calls"] == 2 and {i["target"] for i in body["items"]} == {"workflow"}


def test_malformed_audit_data_doesnt_crash(agent, workspace, gemini, django_capture_on_commit_callbacks):
    a = make_audit(workspace, agent.published_version, "r1", flow={"score": 2, "summary": "x", "evidence": 7})
    assert [p.area for p in fixes.problems_of([a])] == ["flow"]
    a.scores = ["not", "a", "dict"]
    assert fixes.lost_points(a, "flow") == 0.0 and fixes.low_areas([a]) == []
