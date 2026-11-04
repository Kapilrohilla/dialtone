"""Turn classifier: asks a small LLM what mood one caller reply shows.

It never raises into the call: timeouts, errors and junk answers all come back as None, and the
first failure per classifier is logged once. LiveKit plugins are imported only inside
make_classifier, so the rest of this module (and its tests) needs no API keys.
"""

import asyncio
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import get_args

from mood import Emotion, MoodReading

logger = logging.getLogger("phone-agent")

CompleteFn = Callable[[str, str], Awaitable[str]]

_LABELS = frozenset(get_args(Emotion))
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*(.*?)\s*```\s*$", re.DOTALL)

CLASSIFIER_PROMPT = """\
You label the mood of a driver on a phone call. The input is one reply (in Hindi, Hinglish or a \
regional Indian language) from a driver to Carrum's AI caller, plus the agent's previous line for \
context.

Reply with only this JSON and nothing else:
{"emotion": <one of the 8 labels>, "sentiment": <number from -1 to 1>, "confidence": <number from 0 to 1>}

Labels:
- neutral: no clear feeling; answering normally.
- interested: keen, asking about the job or earnings, wants to move ahead.
- confused: doesn't understand the question or what Carrum is.
- frustrated: irritated or fed up, but not hostile.
- rushed: short on time, busy, wants it quick or later.
- suspicious: wary, doubts the call is genuine, worried about documents or money.
- angry: hostile, shouting, abusive, or demands not to be called.
- disengaged: distracted or not following: off-topic replies, talking to someone else, "hmm" without answering.

A plain "no" or "nahi" is neutral unless the wording shows irritation.
Short direct answers to the question asked ("Pune", "haan ji", "nahi hai") are neutral, not disengaged.
"""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_reading(raw: str, at_s: float) -> MoodReading | None:
    """Parse the classifier's JSON (optionally in ``` fences). None if it isn't usable."""
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
        emotion = data["emotion"]
        if emotion not in _LABELS:
            return None
        sentiment = _clamp(float(data["sentiment"]), -1.0, 1.0)
        confidence = _clamp(float(data["confidence"]), 0.0, 1.0)
    except (ValueError, TypeError, KeyError):
        return None
    return MoodReading(emotion, sentiment, confidence, "text", at_s)


class TurnClassifier:
    def __init__(self, complete: CompleteFn, timeout_s: float = 3.0) -> None:
        self._complete = complete
        self._timeout_s = timeout_s
        self._warned = False

    async def classify(self, agent_line: str, caller_text: str, at_s: float) -> MoodReading | None:
        user = f"Agent's previous line: {agent_line}\nDriver's reply: {caller_text}"
        try:
            raw = await asyncio.wait_for(self._complete(CLASSIFIER_PROMPT, user), self._timeout_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # timeout or any provider error: carry on without a mood
            self._warn_once(f"mood classifier failed: {type(e).__name__}: {e}")
            return None
        reading = parse_reading(raw, at_s)
        if reading is None:
            self._warn_once(f"mood classifier returned an unusable answer: {raw[:80]!r}")
        return reading

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            self._warned = True
            logger.warning(message)


def make_classifier(pipeline: str) -> TurnClassifier | None:
    """Build a classifier on the pipeline's provider. None (with a warning) if its key is missing."""
    model = os.getenv("SENTIMENT_MODEL") or None
    if pipeline == "gemini-live":
        if not os.getenv("GOOGLE_API_KEY"):
            logger.warning("mood classifier off: GOOGLE_API_KEY is not set")
            return None
        from livekit.plugins import google

        llm = google.LLM(model=model or "gemini-flash-lite-latest")
    else:
        if not os.getenv("OPENAI_API_KEY"):
            logger.warning("mood classifier off: OPENAI_API_KEY is not set")
            return None
        from livekit.plugins import openai

        llm = openai.LLM(model=model or "gpt-4.1-mini")

    from livekit.agents.llm import ChatContext

    async def complete(system: str, user: str) -> str:
        ctx = ChatContext.empty()
        ctx.add_message(role="system", content=system)
        ctx.add_message(role="user", content=user)
        parts: list[str] = []
        async with llm.chat(chat_ctx=ctx) as stream:
            async for chunk in stream:
                if chunk.delta and chunk.delta.content:
                    parts.append(chunk.delta.content)
        return "".join(parts)

    return TurnClassifier(complete)
