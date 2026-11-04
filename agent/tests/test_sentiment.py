import asyncio
import logging

from mood import MoodReading
from sentiment import TurnClassifier, parse_reading


def test_parse_plain_json():
    raw = '{"emotion":"confused","sentiment":-0.2,"confidence":0.7}'
    assert parse_reading(raw, 3.0) == MoodReading("confused", -0.2, 0.7, "text", 3.0)


def test_parse_fenced_and_clamped():
    raw = '```json\n{"emotion":"angry","sentiment":4,"confidence":-1}\n```'
    reading = parse_reading(raw, 1.0)
    assert reading is not None
    assert reading.sentiment == 1.0
    assert reading.confidence == 0.0


def test_parse_rejects_unknown_label_and_junk():
    assert parse_reading('{"emotion":"happy","sentiment":0.5,"confidence":0.9}', 0) is None
    assert parse_reading("sorry I can't", 0) is None


async def test_classify_timeout_returns_none():
    async def slow(system: str, user: str) -> str:
        await asyncio.sleep(5)
        return '{"emotion":"neutral","sentiment":0,"confidence":1}'

    c = TurnClassifier(slow, timeout_s=0.05)
    assert await c.classify("agent", "caller", 1.0) is None


async def test_classify_error_logged_once(caplog):
    async def broken(system: str, user: str) -> str:
        raise RuntimeError("boom")

    c = TurnClassifier(broken)
    with caplog.at_level(logging.WARNING):
        assert await c.classify("agent", "caller", 1.0) is None
        assert await c.classify("agent", "caller", 2.0) is None
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert len(warnings) == 1


async def test_classify_passes_context():
    seen: list[tuple[str, str]] = []

    async def fake(system: str, user: str) -> str:
        seen.append((system, user))
        return '{"emotion":"interested","sentiment":0.6,"confidence":0.8}'

    c = TurnClassifier(fake)
    reading = await c.classify("Kya aap gaadi chalate hain?", "haan ji, batao", 4.0)
    assert reading == MoodReading("interested", 0.6, 0.8, "text", 4.0)
    _, user = seen[0]
    assert "Kya aap gaadi chalate hain?" in user
    assert "haan ji, batao" in user
