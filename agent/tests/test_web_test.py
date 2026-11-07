"""Console voice test (browser over WebRTC): dispatch metadata and the draft config fetch."""

import json

import jwt as pyjwt
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import agent
import console_config
from console_config import Config, load_draft_config, web_test_agent_id

KEY, SECRET = "devkey", "s" * 40
SNAP = {"agent_id": 5, "version": 0}


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_CACHE_DIR", str(tmp_path))
    console_config._memo.clear()
    return tmp_path


async def serve(handler):
    app = web.Application()
    app.router.add_get("/api/runtime/config", handler)
    server = TestServer(app)
    await server.start_server()
    return server


async def load(handler, agent_id=5):
    server = await serve(handler)
    try:
        base = str(server.make_url("")).rstrip("/")
        return await load_draft_config(agent_id, "web-5-ab12", base_url=base, api_key=KEY, api_secret=SECRET)
    finally:
        await server.close()


@pytest.mark.parametrize(
    "metadata, expected",
    [
        ({"web_test": {"agent_id": 5}}, 5),
        ({"web_test": {"agent_id": 5}, "city": "Pune"}, 5),
        ({}, None),
        ({"lead_id": "L1"}, None),
        ({"web_test": {"agent_id": "5"}}, None),
        ({"web_test": {"agent_id": True}}, None),
        ({"web_test": {"agent_id": 0}}, None),
        ({"web_test": 5}, None),
        ([], None),
    ],
)
def test_web_test_agent_id(metadata, expected):
    assert web_test_agent_id(metadata) == expected


def test_lead_record_drops_the_web_test_marker():
    meta = json.dumps({"web_test": {"agent_id": 5}, "lead_id": "L1", "city": "Pune"})
    assert agent.lead_record(meta) == {"lead_id": "L1", "city": "Pune"}
    assert agent.web_test_agent_id(agent.dispatch_metadata(meta)) == 5
    assert agent.lead_record("") == {} and agent.lead_record("not json") == {}
    assert agent.dispatch_metadata("[1]") == {}


async def test_draft_fetched_by_agent_and_room_with_runtime_token(cache_dir):
    seen = {}

    async def ok(request):
        seen["params"] = dict(request.query)
        seen["token"] = request.headers["Authorization"].removeprefix("Bearer ")
        return web.json_response({"version_id": None, "draft": True, "snapshot": SNAP})

    cfg = await load(ok)

    assert cfg == Config("draft", SNAP, None)
    assert seen["params"] == {"agent": "5", "room": "web-5-ab12"}
    claims = pyjwt.decode(seen["token"], SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["sub"] == "agent-runtime"
    # A draft is never cached: a phone call must never fall back to it.
    assert list(cache_dir.iterdir()) == [] and console_config._memo == {}


async def test_draft_not_memoised_between_test_calls():
    hits = []

    async def ok(request):
        hits.append(1)
        return web.json_response({"version_id": None, "snapshot": {"n": len(hits)}})

    first, second = await load(ok), await load(ok)
    assert first.snapshot == {"n": 1} and second.snapshot == {"n": 2}


@pytest.mark.parametrize("status", [404, 401, 500])
async def test_draft_unavailable_falls_back_to_builtin(status):
    async def fail(request):
        return web.json_response({"detail": "nope"}, status=status)

    assert await load(fail) == Config("builtin", None, None)


async def test_draft_bad_body_falls_back_to_builtin():
    async def bad(request):
        return web.json_response({"snapshot": "not an object"})

    assert await load(bad) == Config("builtin", None, None)


async def test_draft_without_dashboard_is_builtin():
    cfg = await load_draft_config(5, "web-5-x", base_url="", api_key=KEY, api_secret=SECRET)
    assert cfg == Config("builtin", None, None)


async def test_draft_dashboard_down_is_builtin():
    cfg = await load_draft_config(5, "web-5-x", base_url="http://127.0.0.1:9", api_key=KEY, api_secret=SECRET,
                                  timeout_s=0.5)
    assert cfg == Config("builtin", None, None)
