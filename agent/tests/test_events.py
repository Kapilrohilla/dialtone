import asyncio
import time

import jwt as pyjwt
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from events import EventSink

KEY, SECRET = "devkey", "s" * 40


class Fake:
    def __init__(self, status=200):
        self.status = status
        self.bodies = []
        self.auth = []

    async def handler(self, request):
        self.bodies.append(await request.json())
        self.auth.append(request.headers.get("Authorization"))
        return web.json_response({"stored": 1, "skipped": 0}, status=self.status)


async def serve(fake):
    app = web.Application()
    app.router.add_post("/api/runtime/events", fake.handler)
    server = TestServer(app)
    await server.start_server()
    return server


def make(server, **kw):
    url = str(server.make_url("/api/runtime/events"))
    kw.setdefault("flush_every_s", 0.02)
    kw.setdefault("retry_delays", (0.01, 0.01, 0.01))
    return EventSink(url, "room1", KEY, SECRET, **kw)


async def test_seq_increasing_and_batches_posted():
    fake = Fake()
    server = await serve(fake)
    try:
        sink = make(server)
        sink.add("step_entered", {"step_id": "a", "step_name": "A"})
        sink.add("turn", {"speaker": "caller", "text": "hi", "expressions": []})
        await asyncio.sleep(0.2)
        sink.add("mood", {"label": "calm", "confidence": 0.9})
        await sink.close()
    finally:
        await server.close()
    events = [e for b in fake.bodies for e in b["events"]]
    assert [e["seq"] for e in events] == [0, 1, 2]
    assert [e["type"] for e in events] == ["step_entered", "turn", "mood"]
    assert all(isinstance(e["at"], float) for e in events)
    assert all(b["room"] == "room1" for b in fake.bodies)
    claims = pyjwt.decode(fake.auth[0].split()[1], SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["sub"] == "agent-runtime"


async def test_post_failure_never_raises():
    fake = Fake(status=500)
    server = await serve(fake)
    try:
        sink = make(server)
        sink.add("mood", {"label": "x", "confidence": 1})
        await asyncio.sleep(0.3)
        assert len(fake.bodies) == 4  # first try + 3 retries
        assert sink.dropped == 1
        sink.add("mood", {"label": "y", "confidence": 1})  # still works
        await sink.close()
    finally:
        await server.close()


async def test_non_retryable_status_dropped_once():
    fake = Fake(status=400)
    server = await serve(fake)
    try:
        sink = make(server)
        sink.add("mood", {"label": "x", "confidence": 1})
        await sink.close()
    finally:
        await server.close()
    assert len(fake.bodies) == 1 and sink.dropped == 1


async def test_flush_on_close():
    fake = Fake()
    server = await serve(fake)
    try:
        sink = make(server, flush_every_s=30)
        sink.add("mood", {"label": "x", "confidence": 1})
        sink.add("mood", {"label": "y", "confidence": 1})
        await sink.close()
    finally:
        await server.close()
    assert [e["seq"] for b in fake.bodies for e in b["events"]] == [0, 1]


async def test_noop_without_url():
    sink = EventSink("", "room1", KEY, SECRET)
    sink.add("mood", {"label": "x", "confidence": 1})
    await sink.close()
    assert sink.dropped == 0


def test_add_without_running_loop_does_not_raise():
    sink = EventSink("http://127.0.0.1:9/x", "r", KEY, SECRET)
    sink.add("mood", {"label": "x", "confidence": 1})


async def test_unreachable_never_raises():
    sink = EventSink("http://127.0.0.1:9/x", "r", KEY, SECRET, retry_delays=(0.01,) * 3)
    sink.add("mood", {"label": "x", "confidence": 1})
    await sink.close()
    assert sink.dropped == 1


async def test_batch_size_capped():
    fake = Fake()
    server = await serve(fake)
    try:
        sink = make(server, max_batch=3, flush_every_s=30)
        for i in range(7):
            sink.add("mood", {"label": str(i), "confidence": 1})
        await sink.close()
    finally:
        await server.close()
    assert [len(b["events"]) for b in fake.bodies] == [3, 3, 1]
    assert [e["seq"] for b in fake.bodies for e in b["events"]] == list(range(7))


@pytest.mark.parametrize("status", [403, 404, 422])
async def test_non_retryable_4xx_single_attempt(status):
    fake = Fake(status=status)
    server = await serve(fake)
    try:
        sink = make(server)
        sink.add("mood", {"label": "x", "confidence": 1})
        await sink.close()
    finally:
        await server.close()
    assert len(fake.bodies) == 1 and sink.dropped == 1


async def test_2xx_is_success():
    fake = Fake(status=204)
    server = await serve(fake)
    try:
        sink = make(server)
        sink.add("mood", {"label": "x", "confidence": 1})
        await sink.close()
    finally:
        await server.close()
    assert len(fake.bodies) == 1 and sink.dropped == 0


async def test_close_bounded_when_server_hangs():
    release = asyncio.Event()

    async def hang(request):
        await release.wait()
        return web.json_response({})

    app = web.Application()
    app.router.add_post("/api/runtime/events", hang)
    server = TestServer(app)
    await server.start_server()
    try:
        sink = make(server)
        sink.add("mood", {"label": "x", "confidence": 1})
        await asyncio.sleep(0.1)
        t = time.monotonic()
        await sink.close(timeout_s=0.3)
        assert time.monotonic() - t < 0.6
        assert sink.dropped == 1
    finally:
        release.set()
        await server.close()


async def test_close_bounded_during_backoff():
    fake = Fake(status=500)
    server = await serve(fake)
    try:
        sink = make(server, retry_delays=(5, 5, 5))
        sink.add("mood", {"label": "x", "confidence": 1})
        await asyncio.sleep(0.15)
        t = time.monotonic()
        await sink.close(timeout_s=0.3)
        assert time.monotonic() - t < 0.6
        assert sink.dropped == 1
    finally:
        await server.close()


async def test_buffer_cap_drops_oldest():
    sink = EventSink("http://127.0.0.1:9/x", "r", KEY, SECRET, max_buffer=3, retry_delays=(), flush_every_s=30)
    for i in range(5):
        sink.add("mood", {"label": str(i), "confidence": 1})
    assert [e["seq"] for e in sink._buffer] == [2, 3, 4]
    assert sink.dropped == 2
    await sink.close()


async def test_task_restarts_after_crash(monkeypatch):
    fake = Fake()
    server = await serve(fake)
    try:
        sink = make(server)
        real = sink._send
        calls = {"n": 0}

        async def flaky(batch):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            await real(batch)

        monkeypatch.setattr(sink, "_send", flaky)
        sink.add("mood", {"label": "a", "confidence": 1})
        await asyncio.sleep(0.15)
        sink._task.cancel()  # simulate the task dying
        await asyncio.sleep(0)
        sink.add("mood", {"label": "b", "confidence": 1})
        assert not sink._task.done()
        await sink.close()
    finally:
        await server.close()
    assert [e["seq"] for b in fake.bodies for e in b["events"]] == [1]
