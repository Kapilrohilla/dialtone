"""Console "Voice test": talk to an agent's draft from the browser over WebRTC, with no SIP call.

The dashboard signs a LiveKit token for a fresh `web-…` room. The token's room configuration dispatches the
voice agent worker (AGENT_NAME) into the room as soon as the browser joins, with dispatch metadata
`{"web_test": {"agent_id": N}}`. The worker then asks /api/runtime/config for that agent's draft instead of
the agent published on a phone number, so what you hear is what the agent would be if published now.
Nothing is published and no phone minutes are used; the call is logged in call history like any other.
"""
import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from livekit import api
from rest_framework.response import Response
from rest_framework.views import APIView

from workspaces.permissions import CanEdit, workspace_for

from .models import Agent

ROOM_PREFIX = "web-"
# Only needs to be valid when the browser joins; LiveKit keeps the connection alive after that.
TOKEN_TTL = timedelta(minutes=10)
# The caller shown in call history for a voice test.
WEB_CALLER = "Web test"


def is_web_room(room: str) -> bool:
    return room.startswith(ROOM_PREFIX)


def web_room_agent_id(room: str) -> int | None:
    """The agent a voice test room (`web-<agent id>-<hex>`) was made for, or None for any other room."""
    if not is_web_room(room):
        return None
    head = room[len(ROOM_PREFIX):].split("-", 1)[0]
    return int(head) if head.isdigit() else None


def web_call_token(room: str, identity: str, name: str, agent_id: int) -> str:
    dispatch = api.RoomAgentDispatch(
        agent_name=settings.AGENT_NAME,
        metadata=json.dumps({"web_test": {"agent_id": agent_id}}),
    )
    return (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(name)
        .with_ttl(TOKEN_TTL)
        .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                                     can_publish_data=True))
        .with_room_config(api.RoomConfiguration(agents=[dispatch]))
        .to_jwt()
    )


class AgentWebCallView(APIView):
    permission_classes = [CanEdit]

    def post(self, request, pk):
        agent = get_object_or_404(Agent, pk=pk, workspace=workspace_for(request))
        room = f"{ROOM_PREFIX}{agent.id}-{secrets.token_hex(4)}"
        identity = f"web-test-{request.user.id}"
        name = request.user.get_full_name() or request.user.email or identity
        return Response({
            "url": settings.LIVEKIT_PUBLIC_URL,
            "token": web_call_token(room, identity, name, agent.id),
            "room": room,
        })
