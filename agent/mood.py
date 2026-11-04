"""Caller mood tracking: smooths per-turn mood readings so one odd reading doesn't flip the tone.

A reading below MIN_CONFIDENCE is recorded but never causes a switch. The mood switches to X when
the last two accepted readings are both X; confident anger switches at once. Time is passed in
on each reading (monotonic seconds), so this has no clock of its own.
"""

from dataclasses import dataclass
from typing import Literal

Emotion = Literal[
    "neutral", "interested", "confused", "frustrated", "rushed", "suspicious", "angry", "disengaged"
]

MIN_CONFIDENCE = 0.6
ANGER_IMMEDIATE_CONFIDENCE = 0.8
SENTIMENT_ALPHA = 0.5

# Most negative first. Used to pick the worst mood of a call.
NEGATIVITY_RANK: tuple[Emotion, ...] = (
    "angry", "frustrated", "suspicious", "confused", "rushed", "disengaged", "neutral", "interested",
)


@dataclass(frozen=True)
class MoodReading:
    emotion: Emotion
    sentiment: float
    confidence: float
    source: Literal["text", "behavior"]
    at_s: float


class MoodTracker:
    def __init__(self) -> None:
        self.current: Emotion = "neutral"
        self.sentiment: float = 0.0  # EMA over text readings
        self.timeline: list[dict] = []
        self._accepted: list[Emotion] = []
        self._text_sentiments: list[float] = []
        self._moods_held: list[Emotion] = ["neutral"]
        self._changes = 0

    def observe(self, r: MoodReading) -> Emotion | None:
        """Record a reading. Returns the new mood only when it changes."""
        self.timeline.append(
            {"at_s": r.at_s, "emotion": r.emotion, "confidence": r.confidence, "source": r.source}
        )
        if r.source == "text":
            self.sentiment = SENTIMENT_ALPHA * r.sentiment + (1 - SENTIMENT_ALPHA) * self.sentiment
            self._text_sentiments.append(r.sentiment)
        if r.confidence < MIN_CONFIDENCE:
            return None
        self._accepted.append(r.emotion)
        immediate = r.emotion == "angry" and r.confidence >= ANGER_IMMEDIATE_CONFIDENCE
        agreed = len(self._accepted) >= 2 and self._accepted[-2] == r.emotion
        if (immediate or agreed) and r.emotion != self.current:
            self.current = r.emotion
            self._moods_held.append(r.emotion)
            self._changes += 1
            return r.emotion
        return None

    def summary(self) -> dict:
        worst = min(self._moods_held, key=NEGATIVITY_RANK.index)
        avg = sum(self._text_sentiments) / len(self._text_sentiments) if self._text_sentiments else 0.0
        return {
            "final": self.current,
            "worst": worst,
            "avg_sentiment": round(avg, 2),
            "changes": self._changes,
        }
