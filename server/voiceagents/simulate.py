"""Console "Test call" (agent editor) and "Try it" (workflow builder): text simulation.

The dashboard builds the snapshot to try (the agent's unsaved-to-version draft, or a minimal one around a
workflow), signs a short-lived "console-sim" token and proxies one turn to the agent container's text
simulator (agent/simulate.py, AGENT_SIM_URL). Nothing here is saved.
"""
import copy
import json
import socket
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.shortcuts import get_object_or_404
from livekit import api
from rest_framework.response import Response
from rest_framework.views import APIView

from knowledge.models import KnowledgeDocument
from workflows.models import Workflow
from workspaces.permissions import CanEdit, workspace_for

from .models import Agent
from .publish import _step_knowledge_ids, build_snapshot
from .tokens import render_hints

SIM_IDENTITY = "console-sim"
SIM_TIMEOUT_S = 20
MAX_MESSAGES = 200
MAX_TEXT = 2000
WORKFLOW_PERSONA = "Maya"

DOWN = {"detail": "The test simulator isn't running."}
FAILED = {"detail": "The test simulator failed."}
BAD_BODY = (
    f'Send "messages" as a list of at most {MAX_MESSAGES} turns, each with role "caller" or "agent" and text '
    f'of at most {MAX_TEXT} characters, and "state" as an object or null.'
)


class SimUnavailable(Exception):
    pass


def sim_token(ttl_s: int = 60) -> str:
    return (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(SIM_IDENTITY)
        .with_ttl(timedelta(seconds=ttl_s))
        .to_jwt()
    )


def post_to_sim(url: str, payload: dict, token: str, timeout: float) -> tuple[int, dict | None]:
    """(status, JSON body or None). Raises SimUnavailable when the simulator can't be reached in time."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        raise SimUnavailable() from e
    try:
        body = json.loads(raw)
    except ValueError:
        return status, None
    return status, body if isinstance(body, dict) else None


def _clean_body(data) -> tuple[list, dict | None] | None:
    """(messages, state) from a valid request body, else None."""
    if not isinstance(data, dict):
        return None
    messages = data.get("messages")
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        return None
    clean = []
    for m in messages:
        if (not isinstance(m, dict) or m.get("role") not in ("caller", "agent")
                or not isinstance(m.get("text"), str) or len(m["text"]) > MAX_TEXT):
            return None
        clean.append({"role": m["role"], "text": m["text"]})
    state = data.get("state")
    if state is not None and not isinstance(state, dict):
        return None
    return clean, state


def _proxy(messages: list, state: dict | None, snapshot: dict) -> Response:
    payload = {"snapshot": snapshot, "lead": {}, "messages": messages, "state": state}
    url = settings.AGENT_SIM_URL.rstrip("/") + "/simulate"
    try:
        status, body = post_to_sim(url, payload, sim_token(), SIM_TIMEOUT_S)
    except SimUnavailable:
        return Response(DOWN, status=503)
    if status != 200 or body is None:
        return Response(FAILED, status=502)
    return Response(body)


def workflow_snapshot(workflow: Workflow) -> dict:
    """A minimal snapshot around a workflow: persona Maya, no script, the current revision's graph with
    step prompts rendered (no custom expressions) and the knowledge its knowledge steps use."""
    rev = workflow.revisions.order_by("-number").first()
    graph = copy.deepcopy(rev.graph) if rev and isinstance(rev.graph, dict) else {"steps": [], "paths": []}
    steps = graph.get("steps")
    for st in steps if isinstance(steps, list) else []:
        if isinstance(st, dict) and isinstance(st.get("prompt"), str):
            st["prompt"] = render_hints(st["prompt"], {})
    docs = KnowledgeDocument.objects.filter(
        workspace_id=workflow.workspace_id, archived=False, id__in=_step_knowledge_ids(graph)
    ).order_by("id")
    knowledge = []
    for doc in docs:
        doc_rev = doc.revisions.order_by("-number").first()
        knowledge.append({
            "id": doc.id, "title": doc.title, "revision": doc_rev.number if doc_rev else 0,
            "body_md": doc_rev.body_md if doc_rev else "",
            "body_rendered": render_hints(doc_rev.body_md, {}) if doc_rev else "",
        })
    return {
        "agent_id": None,
        "version": 0,
        "name": workflow.name,
        "persona_name": WORKFLOW_PERSONA,
        "settings": {},
        "custom_expressions": {},
        "script": [],
        "variables": [],
        "knowledge": knowledge,
        "workflow": {"id": workflow.id, "revision": rev.number if rev else 0, "graph": graph},
    }


class _SimulateView(APIView):
    permission_classes = [CanEdit]

    def post(self, request, pk):
        snapshot_for = self.snapshot(pk)  # 404 before validating, like the other per-object endpoints
        cleaned = _clean_body(request.data)
        if cleaned is None:
            return Response({"detail": BAD_BODY}, status=400)
        return _proxy(*cleaned, snapshot_for())


class AgentSimulateView(_SimulateView):
    def snapshot(self, pk):
        agent = get_object_or_404(Agent.objects.select_related("workflow"), pk=pk, workspace=workspace_for(self.request))
        # The draft: what the agent would be if published now. build_snapshot only reads.
        return lambda: build_snapshot(agent, 0)


class WorkflowSimulateView(_SimulateView):
    def snapshot(self, pk):
        workflow = get_object_or_404(Workflow, pk=pk, workspace=workspace_for(self.request), archived=False)
        return lambda: workflow_snapshot(workflow)
