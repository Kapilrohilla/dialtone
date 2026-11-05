import asyncio
import json

import jwt as pyjwt
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import console_config
from console_config import Config, load_config

KEY, SECRET = "devkey", "s" * 40
SNAP = {"v": 1}


async def serve(handler):
    app = web.Application()
    app.router.add_get("/api/runtime/config", handler)
    server = TestServer(app)
    await server.start_server()
    return server


def url(server):
    return str(server.make_url("")).rstrip("/")


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_CACHE_DIR", str(tmp_path))
    console_config._memo.clear()
    return tmp_path


async def ok(request):
    return web.json_response({"version_id": 7, "workspace": "carrum", "snapshot": SNAP})


async def call(server, number="+91 98765-43210", **kw):
    return await load_config(number, "room1", base_url=url(server), api_key=KEY, api_secret=SECRET, **kw)


async def test_console_ok_and_cached_to_disk(cache_dir):
    server = await serve(ok)
    try:
        cfg = await call(server)
    finally:
        await server.close()
    assert cfg == Config("console", SNAP, 7)
    saved = json.loads((cache_dir / "919876543210.json").read_text())
    assert saved["snapshot"] == SNAP and saved["version_id"] == 7


async def test_404_returns_builtin_and_clears_cache(cache_dir):
    (cache_dir / "123.json").write_text(json.dumps({"version_id": 1, "snapshot": SNAP}))

    async def nf(request):
        return web.json_response({"detail": "No published agent for this number."}, status=404)

    server = await serve(nf)
    try:
        cfg = await call(server, "123")
    finally:
        await server.close()
    assert cfg == Config("builtin", None, None)
    assert not (cache_dir / "123.json").exists()


async def test_timeout_uses_cache(cache_dir):
    (cache_dir / "123.json").write_text(json.dumps({"version_id": 3, "snapshot": SNAP}))

    async def slow(request):
        await asyncio.sleep(3)
        return await ok(request)

    server = await serve(slow)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    try:
        cfg = await call(server, "123", timeout_s=0.2)
    finally:
        await server.close()
    assert loop.time() - t0 < 0.6
    assert cfg == Config("cache", SNAP, 3)


async def test_down_no_cache_uses_builtin():
    cfg = await load_config("123", "r", base_url="http://127.0.0.1:1", api_key=KEY, api_secret=SECRET)
    assert cfg == Config("builtin", None, None)


async def test_5xx_uses_cache(cache_dir):
    (cache_dir / "123.json").write_text(json.dumps({"version_id": 3, "snapshot": SNAP}))

    async def boom(request):
        return web.Response(status=503)

    server = await serve(boom)
    try:
        cfg = await call(server, "123")
    finally:
        await server.close()
    assert cfg.source == "cache"


async def test_401_falls_back_with_warning(cache_dir, caplog):
    async def unauth(request):
        return web.json_response({"detail": "Invalid token."}, status=401)

    server = await serve(unauth)
    try:
        with caplog.at_level("WARNING"):
            cfg = await call(server, "123")
    finally:
        await server.close()
    assert cfg.source == "builtin"
    assert any(r.levelname == "WARNING" for r in caplog.records)


async def test_bad_json_uses_cache(cache_dir):
    (cache_dir / "123.json").write_text(json.dumps({"version_id": 3, "snapshot": SNAP}))

    async def bad(request):
        return web.Response(text="not json", content_type="application/json")

    server = await serve(bad)
    try:
        cfg = await call(server, "123")
    finally:
        await server.close()
    assert cfg == Config("cache", SNAP, 3)


async def test_corrupt_cache_ignored(cache_dir):
    (cache_dir / "123.json").write_text("{nope")
    cfg = await load_config("123", "r", base_url="http://127.0.0.1:1", api_key=KEY, api_secret=SECRET)
    assert cfg.source == "builtin"


async def test_token_identity_agent_runtime():
    seen = {}

    async def h(request):
        tok = request.headers["Authorization"].removeprefix("Bearer ")
        seen["claims"] = pyjwt.decode(tok, SECRET, algorithms=["HS256"], options={"verify_aud": False})
        seen["q"] = dict(request.query)
        return await ok(request)

    server = await serve(h)
    try:
        await call(server, "+91 1")
    finally:
        await server.close()
    assert seen["claims"]["sub"] == "agent-runtime"
    assert seen["claims"]["iss"] == KEY
    assert seen["q"] == {"number": "+91 1", "room": "room1"}


def test_runtime_token_defaults():
    tok = console_config.runtime_token(KEY, SECRET)
    c = pyjwt.decode(tok, SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert c["sub"] == "agent-runtime" and c["exp"] - c["nbf"] <= 61


async def test_memo_skips_http_within_15s():
    hits = []

    async def h(request):
        hits.append(1)
        return await ok(request)

    server = await serve(h)
    t = [100.0]
    try:
        a = await call(server, now=lambda: t[0])
        t[0] += 14
        b = await call(server, now=lambda: t[0])
        assert len(hits) == 1 and b == a
        t[0] += 2
        await call(server, now=lambda: t[0])
        assert len(hits) == 2
    finally:
        await server.close()


async def test_unwritable_cache_dir_memory_only(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("CONFIG_CACHE_DIR", str(blocker / "sub"))
    server = await serve(ok)
    try:
        cfg = await call(server)
    finally:
        await server.close()
    assert cfg == Config("console", SNAP, 7)


async def test_console_off_when_no_url():
    cfg = await load_config("123", "r", base_url="", api_key=KEY, api_secret=SECRET)
    assert cfg == Config("builtin", None, None)


def test_default_dashboard_url(monkeypatch):
    monkeypatch.delenv("DASHBOARD_URL", raising=False)
    monkeypatch.setenv("DASHBOARD_REPORT_URL", "https://x.example/api/report")
    assert console_config.dashboard_url() == "https://x.example"
    monkeypatch.setenv("DASHBOARD_URL", "")
    assert console_config.dashboard_url() == ""


@pytest.mark.parametrize("respond", [
    lambda: web.json_response({"detail": "Not found."}, status=404),  # e.g. a proxy or a wrong path
    lambda: web.Response(status=404, text="<html>Not Found</html>"),
    lambda: web.json_response(["No published agent for this number."], status=404),
])
async def test_other_404_is_unavailable_and_keeps_cache(cache_dir, caplog, respond):
    (cache_dir / "123.json").write_text(json.dumps({"version_id": 3, "snapshot": SNAP}))

    async def nf(request):
        return respond()

    server = await serve(nf)
    try:
        with caplog.at_level("WARNING"):
            cfg = await call(server, "123")
            console_config._memo.clear()
            (cache_dir / "123.json").unlink()
            no_cache = await call(server, "123")
    finally:
        await server.close()
    assert cfg == Config("cache", SNAP, 3)
    assert no_cache == Config("builtin", None, None)
    assert any(r.levelname == "WARNING" and "unavailable" in r.getMessage() for r in caplog.records)
