"""Behaviour signals: how the caller acts on the call, not what they say.

Interruptions and short, slow replies become mood readings that feed the same MoodTracker as the
text classifier. Time is passed in (monotonic seconds), so this has no clock of its own.
"""

from statistics import median

from mood import Emotion, MoodReading

WINDOW = 3
RUSHED_MIN_INTERRUPTIONS = 2
DISENGAGED_MAX_WORDS = 2
DISENGAGED_MIN_LATENCY_S = 2.5
BEHAVIOR_CONFIDENCE = 0.7


def reply_latency_reliable(pipeline: str) -> bool:
    """On Gemini Live the caller's speaking state arrives when the reply starts generating, so the
    measured latency includes the caller's own speech; it can't drive the disengaged rule there."""
    return pipeline != "gemini-live"


class BehaviorTracker:
    def __init__(self) -> None:
        self._interrupted: list[bool] = []
        self._reply_words: list[int] = []
        self._reply_latencies: list[float] = []
        self._last_emitted: Emotion | None = None

    def agent_turn_ended(self, now: float, interrupted: bool) -> None:
        self._interrupted.append(interrupted)

    def user_turn(self, now: float, text: str, reply_latency_s: float) -> None:
        self._reply_words.append(len(text.split()))
        self._reply_latencies.append(reply_latency_s)

    def poll(self, now: float) -> MoodReading | None:
        """At most one reading per call, and never the same emotion twice in a row."""
        for emotion in self._due():
            if emotion != self._last_emitted:
                self._last_emitted = emotion
                return MoodReading(emotion, 0.0, BEHAVIOR_CONFIDENCE, "behavior", now)
        return None

    def features(self) -> dict:
        return {
            "interruptions": sum(self._interrupted),
            "agent_turns": len(self._interrupted),
            "median_reply_latency_s": (
                round(median(self._reply_latencies), 2) if self._reply_latencies else None
            ),
            "median_reply_words": median(self._reply_words) if self._reply_words else None,
        }

    def _due(self) -> list[Emotion]:
        due: list[Emotion] = []
        if sum(self._interrupted[-WINDOW:]) >= RUSHED_MIN_INTERRUPTIONS:
            due.append("rushed")
        words = self._reply_words[-WINDOW:]
        latencies = self._reply_latencies[-WINDOW:]
        if (
            len(words) == WINDOW
            and all(w <= DISENGAGED_MAX_WORDS for w in words)
            and median(latencies) >= DISENGAGED_MIN_LATENCY_S
        ):
            due.append("disengaged")
        return due
