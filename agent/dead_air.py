"""Dead-air detection: notices when the caller goes quiet and says what to do about it.

Silence only counts while the agent is idle and waiting for the caller. The agent thinking or
speaking (including its own check-ins) pauses the count without resetting it, so nudges escalate
to a hang-up. Only caller activity resets it. Time is passed in (monotonic seconds) so this has
no clock of its own and is easy to test.
"""

from dataclasses import dataclass
from typing import Literal

DeadAirAction = Literal["nudge", "second_nudge", "hang_up"]

# Phrases that mean "hold on": the next silence gets longer thresholds.
HOLD_PHRASES: tuple[str, ...] = (
    "ek minute", "ek min", "ek second", "do minute", "ruko", "rukiye",
    "hold", "wait", "one minute", "one second",
)


@dataclass(frozen=True)
class DeadAirConfig:
    nudge_s: float = 4.0
    second_nudge_s: float = 9.0
    hang_up_s: float = 15.0
    hold_multiplier: float = 3.0


class DeadAirWatcher:
    def __init__(self, config: DeadAirConfig) -> None:
        self.config = config
        self.events: list[dict] = []
        self._silence = 0.0  # accumulated silence before the current listening stretch
        self._listening_since: float | None = None
        self._fired: set[DeadAirAction] = set()
        self._multiplier = 1.0

    def agent_listening(self, now: float) -> None:
        """The agent is idle, waiting for the caller."""
        if self._listening_since is None:
            self._listening_since = now

    def agent_busy(self, now: float) -> None:
        """The agent is thinking or speaking: pause the count, keep what has accumulated."""
        self._pause(now)

    def user_activity(self, now: float, text: str = "") -> None:
        """The caller spoke: start over. A hold phrase stretches the thresholds for the next silence."""
        self._listening_since = None
        self._silence = 0.0
        self._fired.clear()
        lowered = text.lower()
        holding = any(phrase in lowered for phrase in HOLD_PHRASES)
        self._multiplier = self.config.hold_multiplier if holding else 1.0

    def poll(self, now: float) -> DeadAirAction | None:
        """The action due now, if any. Each fires once per silence; if several are due at once,
        only the most severe fires and the earlier ones are skipped."""
        silence = self._current_silence(now)
        m = self._multiplier
        thresholds: list[tuple[DeadAirAction, float]] = [
            ("hang_up", self.config.hang_up_s * m),
            ("second_nudge", self.config.second_nudge_s * m),
            ("nudge", self.config.nudge_s * m),
        ]
        for i, (action, threshold) in enumerate(thresholds):
            if silence >= threshold:
                if action in self._fired:
                    return None
                self._fired.update(a for a, _ in thresholds[i:])
                self.events.append({"action": action, "silence_s": round(silence, 1)})
                return action
        return None

    def _pause(self, now: float) -> None:
        if self._listening_since is not None:
            self._silence += max(0.0, now - self._listening_since)
            self._listening_since = None

    def _current_silence(self, now: float) -> float:
        if self._listening_since is None:
            return self._silence
        return self._silence + max(0.0, now - self._listening_since)
