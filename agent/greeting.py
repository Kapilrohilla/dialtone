"""When to greet: listen briefly first, and if the caller says "hello", let them finish.

Phone callers often speak first. Greeting straight away talks over them; this waits a moment, and
if they speak, until they pause. Time is passed in (monotonic seconds), so there's no clock here.
"""


class GreetingGate:
    def __init__(self, wait_s: float = 1.0, gap_s: float = 0.8, max_s: float = 5.0) -> None:
        self.wait_s = wait_s  # listen this long before greeting a silent caller
        self.gap_s = gap_s  # once the caller speaks, greet after this long without new speech
        self.max_s = max_s  # never wait longer than this, even if they keep talking
        self.caller_said = ""
        self._start = 0.0
        self._last_speech: float | None = None

    def start(self, now: float) -> None:
        self._start = now

    def caller_spoke(self, now: float, text: str | None) -> None:
        """Caller speech, from a (partial) transcript; text is None when only speech was detected."""
        self._last_speech = now
        if text:
            self.caller_said = text

    def ready(self, now: float) -> bool:
        if now - self._start >= self.max_s:
            return True
        if self._last_speech is None:
            return now - self._start >= self.wait_s
        return now - self._last_speech >= self.gap_s


def greeting_instructions(opening: str, caller_said: str) -> str:
    """What to tell the model when it's time to greet."""
    if not caller_said:
        return f"Open the call by saying this, close to word for word: {opening}"
    return (
        f'The driver picked up and said "{caller_said}". Acknowledge that briefly first, e.g. '
        f'"Ji, hello sir!", then say this, close to word for word: {opening}'
    )
