"""Console "Try it" / "Test call": the dashboard proxies a draft snapshot to the agent's text simulator."""
import socket
import urllib.error

import pytest
from django.test import override_settings
from livekit import api

from tests.test_publish import make_agent, make_doc, make_workflow, make_user
from tests.test_workflow_graph import driver_graph, path, step
from voiceagents import simulate as sim
from voiceagents.models import Agent, AgentVersion
from voiceagents.publish import publish

SIM_REPLY = {"reply": "Namaste sir", "state": {"current_step_id": "s1"}, "step": {"id": "s1", "name": "Greeting"},
             "outcome": None, "ended": False}


@pytest.fixture
def captured(monkeypatch):
    calls = []

    def fake_post(url, payload, token, timeout):
        calls.append({"url": url, "payload": payload, "token": token, "timeout": timeout})
        return 200, SIM_REPLY

    monkeypatch.setattr(sim, "post_to_sim", fake_post)
    return calls


@pytest.mark.django_db
def test_simulate_uses_draft_snapshot(member, workspace, captured):
    from django.conf import settings

    c = member("editor")
    agent = make_agent(workspace)
    publish(agent, make_user())
    edited = [{"id": "s1", "title": "Opening", "body": "Naya draft script [[expr:happy]] for {{lead.city}}."}]
    assert c.patch(f"/api/agents/{agent.id}", {"script": edited}, format="json").status_code == 200
    versions = AgentVersion.objects.count()
    state = {"current_step_id": None, "visits": {}, "transitions": 0, "captured": {}, "outcome": None}
    messages = [{"role": "agent", "text": "Namaste"}, {"role": "caller", "text": "Haan ji"}]

    r = c.post(f"/api/agents/{agent.id}/simulate", {"messages": messages, "state": state}, format="json")

    assert r.status_code == 200, r.content
    assert r.json() == SIM_REPLY
    [call] = captured
    assert call["url"] == settings.AGENT_SIM_URL.rstrip("/") + "/simulate" and call["timeout"] == 20
    payload = call["payload"]
    assert payload["messages"] == messages and payload["state"] == state and payload["lead"] == {}
    snap = payload["snapshot"]
    assert snap["version"] == 0 and snap["agent_id"] == agent.id
    assert snap["script"][0]["body_rendered"].startswith("Naya draft script (say this")
    assert "{{lead.city}}" in snap["script"][0]["body_rendered"]
    claims = api.TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).verify(call["token"])
    assert claims.identity == "console-sim"
    # The draft was never saved as a version, and the live agent still serves its published one.
    assert AgentVersion.objects.count() == versions
    agent.refresh_from_db()
    assert agent.status == Agent.PUBLISHED and agent.published_version.number == 1


@pytest.mark.django_db
@override_settings(AGENT_SIM_URL="http://127.0.0.1:1")
def test_simulate_503_when_down(member, workspace):
    c = member("editor")
    agent = make_agent(workspace)
    r = c.post(f"/api/agents/{agent.id}/simulate", {"messages": [], "state": None}, format="json")
    assert r.status_code == 503
    assert r.json() == {"detail": "The test simulator isn't running."}


@pytest.mark.django_db
def test_simulate_503_on_timeout_and_502_on_sim_error(member, workspace, monkeypatch):
    c = member("editor")
    agent = make_agent(workspace)
    url = f"/api/agents/{agent.id}/simulate"

    def slow(*a, **kw):
        raise socket.timeout("timed out")

    monkeypatch.setattr(sim.urllib.request, "urlopen", slow)
    assert c.post(url, {"messages": []}, format="json").status_code == 503

    def broken(*a, **kw):
        raise urllib.error.HTTPError("http://x", 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(sim.urllib.request, "urlopen", broken)
    r = c.post(url, {"messages": []}, format="json")
    assert r.status_code == 502 and r.json() == {"detail": "The test simulator failed."}

    monkeypatch.setattr(sim, "post_to_sim", lambda *a, **kw: (400, {"detail": "x"}))
    assert c.post(url, {"messages": []}, format="json").status_code == 502


@pytest.mark.django_db
def test_simulate_viewer_forbidden(member, workspace, captured):
    v = member("viewer")
    agent = make_agent(workspace)
    wf = make_workflow(workspace)
    assert v.post(f"/api/agents/{agent.id}/simulate", {"messages": []}, format="json").status_code == 403
    assert v.post(f"/api/workflows/{wf.id}/simulate", {"messages": []}, format="json").status_code == 403
    assert captured == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data",
    [
        {},
        {"messages": "hi"},
        {"messages": [{"role": "boss", "text": "x"}]},
        {"messages": [{"role": "caller", "text": 5}]},
        {"messages": [{"role": "caller"}]},
        {"messages": ["x"]},
        {"messages": [{"role": "caller", "text": "x" * 2001}]},
        {"messages": [{"role": "caller", "text": "x"}] * 201},
        {"messages": [], "state": "x"},
        {"messages": [], "state": [1]},
    ],
)
def test_simulate_rejects_bad_body(member, workspace, captured, data):
    c = member("editor")
    agent = make_agent(workspace)
    assert c.post(f"/api/agents/{agent.id}/simulate", data, format="json").status_code == 400
    assert captured == []


@pytest.mark.django_db
def test_simulate_accepts_limits(member, workspace, captured):
    c = member("editor")
    agent = make_agent(workspace)
    data = {"messages": [{"role": "caller", "text": "x" * 2000}] * 200}
    assert c.post(f"/api/agents/{agent.id}/simulate", data, format="json").status_code == 200


@pytest.mark.django_db
def test_workflow_simulate_minimal_snapshot(member, workspace, other_workspace, captured):
    c = member("editor")
    doc = make_doc(workspace, "FAQ", "old", "Deposit is [[expr:happy]] refundable.")
    archived = make_doc(workspace, "Old", "gone")
    archived.archived = True
    archived.save()
    foreign = make_doc(other_workspace, "Theirs", "secret")
    unused = make_doc(workspace, "Unused", "not referenced")
    g = driver_graph()
    g["steps"][3]["prompt"] = "Explain [[expr:whisper]] for {{lead.name}}."
    g["steps"] += [step("k1", "Look up FAQ", "knowledge", knowledge_id=doc.id),
                   step("k2", "Old FAQ", "knowledge", knowledge_id=archived.id),
                   step("k3", "Their FAQ", "knowledge", knowledge_id=foreign.id)]
    g["paths"] += [path("p9", "s4", "k1", "question")]
    wf = make_workflow(workspace, g)
    WorkflowRevision = wf.revisions.model
    newer = driver_graph()
    newer["steps"] += [step("k1", "Look up FAQ", "knowledge", knowledge_id=doc.id)]
    newer["steps"][3]["prompt"] = "Newest [[expr:whisper]] plan."
    WorkflowRevision.objects.create(workflow=wf, number=2, graph=newer)

    r = c.post(f"/api/workflows/{wf.id}/simulate", {"messages": [], "state": None}, format="json")

    assert r.status_code == 200, r.content
    snap = captured[0]["payload"]["snapshot"]
    assert snap["persona_name"] == "Priya" and snap["script"] == []
    assert [k["title"] for k in snap["knowledge"]] == ["FAQ"]
    assert snap["knowledge"][0]["body_rendered"].startswith("Deposit is (say this")
    assert "[[expr" not in snap["knowledge"][0]["body_rendered"] and unused.title not in str(snap)
    assert snap["workflow"]["id"] == wf.id and snap["workflow"]["revision"] == 2
    prompt = snap["workflow"]["graph"]["steps"][3]["prompt"]
    assert prompt.startswith("Newest (") and "[[expr" not in prompt
    # The saved revision is untouched by rendering.
    assert wf.revisions.get(number=2).graph["steps"][3]["prompt"] == "Newest [[expr:whisper]] plan."


@pytest.mark.django_db
def test_simulate_isolated(member, other_workspace, captured):
    c = member("editor")
    theirs = make_agent(other_workspace, "Theirs")
    their_wf = make_workflow(other_workspace)
    assert c.post(f"/api/agents/{theirs.id}/simulate", {"messages": []}, format="json").status_code == 404
    assert c.post(f"/api/workflows/{their_wf.id}/simulate", {"messages": []}, format="json").status_code == 404
    assert c.post("/api/agents/999999/simulate", {"messages": []}, format="json").status_code == 404
    assert captured == []
