"""Suggest with AI API, with Gemini mocked: start, poll, edit, dismiss, discard, accept on Save, limits, permissions."""
import copy
from datetime import timedelta

import pytest
from django.utils import timezone

from tests.helpers import assert_isolated
from tests.test_workflow_graph import driver_graph
from workflows import suggest
from workflows.models import Workflow, WorkflowSuggestion, WorkflowSuggestionSet

GEMINI_OUT = {
    "answers": [
        {"step_id": "s3", "label": "Not sure which licence", "examples": ["पता नहीं", "not sure ji"],
         "reason": "callers often don't know their licence type.",
         "new_step": {"name": "Explain licence types", "type": "prompt", "prompt": "[[expr:pause:0.6]] कोई बात नहीं जी।",
                      "then_step_id": "s3", "then_label": "Explained licence types"}},
        {"step_id": "s3", "label": "Licence applied, not received", "examples": ["apply किया है"],
         "reason": "many drivers are waiting for their licence.", "target_step_id": "e4"},
    ],
    "expressions": [{"step_id": "s4", "after": "[[expr:happy]] Here is the plan.", "reason": "sounds warmer."}],
}


@pytest.fixture
def gemini(monkeypatch, settings):
    """Runs generation inline and answers every batch with ``calls.out`` (or raises ``calls.error``)."""
    settings.GOOGLE_API_KEY = "test-key"

    class Calls(list):
        out = GEMINI_OUT
        error = None

    calls = Calls()

    def fake(prompt, timeout_s):
        calls.append(prompt)
        if calls.error:
            raise calls.error
        return copy.deepcopy(calls.out), {"input": 10, "output": 5}

    monkeypatch.setattr(suggest, "call_gemini", fake)
    monkeypatch.setattr(suggest, "start", suggest.generate)
    return calls


@pytest.fixture
def wf(member):
    c = member("editor")
    pk = c.post("/api/workflows", {"name": "Driver onboarding"}, format="json").json()["id"]
    c.patch(f"/api/workflows/{pk}", {"graph": driver_graph()}, format="json")
    return c, pk


def start(c, pk, capture, **body):
    with capture(execute=True):
        r = c.post(f"/api/workflows/{pk}/suggestions",
                   {"scope": "step", "step_id": "s3", "kinds": ["answers", "expressions"], **body}, format="json")
    return r


@pytest.mark.django_db
def test_start_and_read_the_draft(wf, gemini, django_capture_on_commit_callbacks):
    c, pk = wf
    r = start(c, pk, django_capture_on_commit_callbacks, scope="workflow", step_id="")
    assert r.status_code == 202 and r.json()["status"] == "running"
    assert r.json()["step_ids"] == ["s1", "s2", "s3", "s4"] and r.json()["total_steps"] == 4
    cur = c.get(f"/api/workflows/{pk}/suggestions/current")
    body = cur.json()
    assert cur.status_code == 200 and body["status"] == "ready" and body["error"] == ""
    assert body["created_by"]["id"] == c.user.id and body["base_revision"] == 1
    assert [(i["kind"], i["step_id"], i["status"], i["invalid_reason"], i["stale"]) for i in body["items"]] == [
        ("answer", "s3", "pending", "", False), ("answer", "s3", "pending", "", False),
        ("expression", "s4", "pending", "", False)]
    assert body["items"][0]["payload"]["target"]["new_step"]["then"] == {
        "step_id": "s3", "label": "Explained licence types"}
    assert len(gemini) == 1 and '"steps_to_improve"' in gemini[0]
    # The workflow itself is untouched.
    assert c.get(f"/api/workflows/{pk}").json()["current_revision"] == 1


@pytest.mark.django_db
def test_nothing_to_suggest_and_errors(wf, gemini, django_capture_on_commit_callbacks):
    c, pk = wf
    gemini.out = {"answers": [], "expressions": []}
    start(c, pk, django_capture_on_commit_callbacks)
    assert c.get(f"/api/workflows/{pk}/suggestions/current").json()["status"] == "empty"
    gemini.error = TimeoutError("slow")
    start(c, pk, django_capture_on_commit_callbacks)
    body = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    assert body["status"] == "error" and body["error"] == "Couldn't get suggestions." and body["items"] == []
    assert c.get(f"/api/workflows/{pk}").json()["current_revision"] == 1
    # Only the latest set is open.
    assert WorkflowSuggestionSet.objects.exclude(status="closed").count() == 1


@pytest.mark.django_db
def test_no_api_key(wf, gemini, settings, django_capture_on_commit_callbacks):
    c, pk = wf
    settings.GOOGLE_API_KEY = ""
    start(c, pk, django_capture_on_commit_callbacks)
    body = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    assert body["status"] == "error" and "Google API key" in body["error"] and gemini == []


@pytest.mark.django_db
def test_some_batches_fail(wf, gemini, monkeypatch, django_capture_on_commit_callbacks):
    c, pk = wf
    g = driver_graph()
    for i in range(6):
        g["steps"].append({"id": f"x{i}", "name": f"Extra {i}", "type": "prompt", "prompt": "hi"})
        g["paths"].append({"id": f"px{i}", "from": "s4", "to": f"x{i}", "label": f"extra {i}"})
        g["paths"].append({"id": f"py{i}", "from": f"x{i}", "to": "e3", "label": "done"})
    c.patch(f"/api/workflows/{pk}", {"graph": g}, format="json")
    real = suggest.call_gemini

    def flaky(prompt, timeout_s):
        if '"id": "x5"' in prompt.split('"steps_to_improve"')[1]:
            raise RuntimeError("boom")
        return real(prompt, timeout_s)

    monkeypatch.setattr(suggest, "call_gemini", flaky)
    start(c, pk, django_capture_on_commit_callbacks, scope="workflow", step_id="", kinds=["answers"])
    body = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    assert body["status"] == "ready" and body["failed_step_ids"] == ["x1", "x2", "x3", "x4", "x5"]
    assert len(body["items"]) == 2  # answers only


@pytest.mark.django_db
def test_stuck_run_becomes_an_error(wf, monkeypatch):
    c, pk = wf
    monkeypatch.setattr(suggest, "start", lambda set_id: None)  # the thread never finishes
    c.post(f"/api/workflows/{pk}/suggestions", {"scope": "step", "step_id": "s3", "kinds": ["answers"]}, format="json")
    assert c.get(f"/api/workflows/{pk}/suggestions/current").json()["status"] == "running"
    WorkflowSuggestionSet.objects.update(created_at=timezone.now() - timedelta(seconds=46))
    body = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    assert body["status"] == "error" and body["error"] == "Took too long."
    # A late result is discarded.
    suggest.generate(body["id"])
    assert WorkflowSuggestion.objects.count() == 0


@pytest.mark.django_db
def test_bad_start_requests(wf, member):
    c, pk = wf
    assert c.post(f"/api/workflows/{pk}/suggestions", {"scope": "x", "kinds": ["answers"]}, format="json").status_code == 400
    assert c.post(f"/api/workflows/{pk}/suggestions", {"scope": "workflow", "kinds": []}, format="json").status_code == 400
    r = c.post(f"/api/workflows/{pk}/suggestions", {"scope": "step", "step_id": "nope", "kinds": ["answers"]}, format="json")
    assert r.status_code == 400 and "step_id" in r.json()
    empty = c.post("/api/workflows", {"name": "Empty"}, format="json").json()["id"]
    r = c.post(f"/api/workflows/{empty}/suggestions", {"scope": "workflow", "kinds": ["answers"]}, format="json")
    assert r.status_code == 400
    assert c.get(f"/api/workflows/{empty}/suggestions/current").status_code == 204


@pytest.mark.django_db
def test_daily_limit(wf, gemini, settings, django_capture_on_commit_callbacks):
    c, pk = wf
    settings.SUGGEST_DAILY_LIMIT = 2
    gemini.error = RuntimeError("down")
    start(c, pk, django_capture_on_commit_callbacks)  # failed runs don't count
    gemini.error = None
    assert start(c, pk, django_capture_on_commit_callbacks).status_code == 202
    assert start(c, pk, django_capture_on_commit_callbacks).status_code == 202
    r = start(c, pk, django_capture_on_commit_callbacks)
    assert r.status_code == 429 and r.json() == {"detail": "Daily limit reached"}
    WorkflowSuggestionSet.objects.update(created_at=timezone.now() - timedelta(days=1))
    assert start(c, pk, django_capture_on_commit_callbacks).status_code == 202


@pytest.mark.django_db
def test_edit_dismiss_and_restore(wf, gemini, django_capture_on_commit_callbacks):
    c, pk = wf
    start(c, pk, django_capture_on_commit_callbacks)
    items = c.get(f"/api/workflows/{pk}/suggestions/current").json()["items"]
    a, b = items[0], items[1]
    url = f"/api/workflows/{pk}/suggestions/{a['id']}"
    bad = c.patch(url, {"edited_payload": {**a["payload"], "label": b["payload"]["label"]}}, format="json")
    assert bad.status_code == 400 and bad.json() == {"label": ["A path with this name already exists. Rename it to accept."]}
    bad = c.patch(url, {"edited_payload": {**a["payload"], "examples": ["x" * 41]}}, format="json")
    assert bad.status_code == 400 and "examples" in bad.json()
    ok = c.patch(url, {"edited_payload": {**a["payload"], "label": "Doesn't know", "examples": ["pata nahi"]}}, format="json")
    assert ok.status_code == 200
    got = ok.json()["items"][0]
    assert got["edited"] and got["payload"]["label"] == "Doesn't know" and got["payload"]["examples"] == ["pata nahi"]
    assert WorkflowSuggestion.objects.get(pk=a["id"]).payload["label"] == "Not sure which licence"
    assert c.patch(url, {"status": "dismissed"}, format="json").json()["items"][0]["status"] == "dismissed"
    assert c.patch(url, {"status": "pending"}, format="json").json()["items"][0]["status"] == "pending"
    assert c.patch(url, {"status": "accepted"}, format="json").status_code == 400


@pytest.mark.django_db
def test_discard_all(wf, gemini, django_capture_on_commit_callbacks):
    c, pk = wf
    start(c, pk, django_capture_on_commit_callbacks)
    s = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    assert c.post(f"/api/workflows/{pk}/suggestions/{s['id']}/close").status_code == 204
    assert c.get(f"/api/workflows/{pk}/suggestions/current").status_code == 204
    assert set(WorkflowSuggestion.objects.values_list("status", flat=True)) == {"dismissed"}
    r = c.patch(f"/api/workflows/{pk}/suggestions/{s['items'][0]['id']}", {"status": "pending"}, format="json")
    assert r.status_code == 409


@pytest.mark.django_db
def test_accept_on_save_and_out_of_date(wf, gemini, django_capture_on_commit_callbacks):
    c, pk = wf
    start(c, pk, django_capture_on_commit_callbacks, scope="workflow", step_id="")
    s = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    applied, waiting, expr = s["items"]
    g = driver_graph()
    g["paths"].append({"id": "pa", "from": "s3", "to": "e4", "label": waiting["payload"]["label"],
                       "examples": waiting["payload"]["examples"]})
    # Accept the second answer only (the console applied it to the graph).
    r = c.patch(f"/api/workflows/{pk}", {"graph": g, "accepted_suggestions": [waiting["id"], 999999]}, format="json")
    assert r.status_code == 200 and r.json()["errors"] == [] and r.json()["current_revision"] == 2
    body = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    by = {i["id"]: i for i in body["items"]}
    assert by[waiting["id"]]["status"] == "accepted"
    # s3 changed after the run (a path was added): its other answer is out of date but still valid.
    assert by[applied["id"]]["stale"] is True and by[applied["id"]]["invalid_reason"] == ""
    assert by[expr["id"]]["stale"] is False
    # Someone rewrites the plan's words: the expression no longer fits.
    g["steps"][3]["prompt"] = "A different plan."
    c.patch(f"/api/workflows/{pk}", {"graph": g}, format="json")
    item = next(i for i in c.get(f"/api/workflows/{pk}/suggestions/current").json()["items"] if i["id"] == expr["id"])
    assert item["stale"] and item["invalid_reason"] == "The agent's words for this step have changed."
    # Accepting the last pending item closes the set.
    c.patch(f"/api/workflows/{pk}/suggestions/{expr['id']}", {"status": "dismissed"}, format="json")
    g["paths"].append({"id": "pb", "from": "s3", "to": "s4", "label": "x"})  # stands in for the applied answer
    c.patch(f"/api/workflows/{pk}", {"graph": g, "accepted_suggestions": [applied["id"]]}, format="json")
    assert WorkflowSuggestionSet.objects.get(pk=s["id"]).status == "closed"
    assert c.get(f"/api/workflows/{pk}/suggestions/current").status_code == 204


@pytest.mark.django_db
def test_viewer_can_read_but_not_write(wf, gemini, member, django_capture_on_commit_callbacks):
    c, pk = wf
    start(c, pk, django_capture_on_commit_callbacks)
    s = c.get(f"/api/workflows/{pk}/suggestions/current").json()
    v = member("viewer")
    assert v.get(f"/api/workflows/{pk}/suggestions/current").status_code == 200
    assert v.post(f"/api/workflows/{pk}/suggestions", {"scope": "workflow", "kinds": ["answers"]},
                  format="json").status_code == 403
    assert v.patch(f"/api/workflows/{pk}/suggestions/{s['items'][0]['id']}", {"status": "dismissed"},
                   format="json").status_code == 403
    assert v.post(f"/api/workflows/{pk}/suggestions/{s['id']}/close").status_code == 403


@pytest.mark.django_db
def test_suggestions_isolated(member, other_workspace, gemini):
    c = member("editor")
    wf = Workflow.objects.create(workspace=other_workspace, name="theirs")
    assert_isolated(c, f"/api/workflows/{wf.id}/suggestions/current")
    assert c.post(f"/api/workflows/{wf.id}/suggestions", {"scope": "workflow", "kinds": ["answers"]},
                  format="json").status_code == 404
