"""Console "Voice test": a browser WebRTC call to the agent's draft, with no SIP."""
import json

import pytest
from django.conf import settings
from django.test import override_settings
from livekit import api

from calls.models import Call
from tests.test_publish import make_agent, make_user
from tests.test_runtime_api import get_config
from voiceagents.models import Agent, AgentVersion
from voiceagents.publish import publish

pytestmark = pytest.mark.django_db


def claims_of(token):
    return api.TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).verify(token)


@override_settings(LIVEKIT_PUBLIC_URL="ws://localhost:7880", AGENT_NAME="phone-agent")
def test_web_call_returns_token_that_dispatches_the_agent(member, workspace):
    c = member("editor")
    agent = make_agent(workspace)

    r = c.post(f"/api/agents/{agent.id}/web-call")

    assert r.status_code == 200, r.content
    body = r.json()
    assert body["url"] == "ws://localhost:7880"
    assert body["room"].startswith(f"web-{agent.id}-")
    claims = claims_of(body["token"])
    assert claims.identity == f"web-test-{c.user.id}"
    assert claims.video.room == body["room"] and claims.video.room_join
    assert claims.video.can_publish and claims.video.can_subscribe
    [dispatch] = claims.room_config.agents
    assert dispatch.agent_name == "phone-agent"
    assert json.loads(dispatch.metadata) == {"web_test": {"agent_id": agent.id}}
    # Nothing is recorded until the agent joins and asks for its config.
    assert not Call.objects.exists()


def test_web_call_rooms_are_unique(member, workspace):
    c = member("editor")
    agent = make_agent(workspace)
    rooms = {c.post(f"/api/agents/{agent.id}/web-call").json()["room"] for _ in range(3)}
    assert len(rooms) == 3


def test_web_call_needs_edit_role_and_own_workspace(member, workspace, other_workspace):
    agent = make_agent(workspace)
    assert member("viewer").post(f"/api/agents/{agent.id}/web-call").status_code == 403
    foreign = make_agent(other_workspace)
    assert member("editor").post(f"/api/agents/{foreign.id}/web-call").status_code == 404


def test_runtime_config_serves_the_draft_for_a_web_room(member, workspace):
    c = member("editor")
    agent = make_agent(workspace)
    publish(agent, make_user())
    edited = [{"id": "s1", "title": "Opening", "body": "Naya draft script."}]
    assert c.patch(f"/api/agents/{agent.id}", {"script": edited}, format="json").status_code == 200
    versions = AgentVersion.objects.count()

    res = get_config(c, agent=str(agent.id), room=f"web-{agent.id}-abcd1234")

    assert res.status_code == 200, res.content
    body = res.json()
    assert body["version_id"] is None and body["draft"] is True
    assert body["snapshot"]["agent_id"] == agent.id and body["snapshot"]["version"] == 0
    assert body["snapshot"]["script"][0]["body_rendered"].startswith("Naya draft script")
    call = Call.objects.get(room=f"web-{agent.id}-abcd1234")
    assert call.workspace == workspace and call.caller == "Web test" and call.agent_version is None
    assert AgentVersion.objects.count() == versions


@pytest.mark.parametrize("room", ["call-123", "", "_web-1-x"])
def test_runtime_draft_only_for_web_rooms(client, workspace, room):
    agent = make_agent(workspace)
    res = get_config(client, agent=str(agent.id), room=room)
    assert res.status_code == 404
    assert res.json() == {"detail": "No agent to voice test."}


@pytest.mark.parametrize("agent_param", ["999999", "abc", "-1"])
def test_runtime_draft_unknown_agent_404s(client, workspace, agent_param):
    make_agent(workspace)
    assert get_config(client, agent=agent_param, room="web-1-x").status_code == 404


def test_runtime_draft_skips_archived_agents(client, workspace):
    agent = make_agent(workspace)
    Agent.objects.filter(pk=agent.pk).update(status=Agent.ARCHIVED)
    assert get_config(client, agent=str(agent.id), room=f"web-{agent.id}-x").status_code == 404


def test_runtime_draft_requires_runtime_token(client, workspace):
    agent = make_agent(workspace)
    assert get_config(client, bearer="junk", agent=str(agent.id), room=f"web-{agent.id}-x").status_code == 401
