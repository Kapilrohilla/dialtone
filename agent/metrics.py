"""Per-call latency summary: how long the caller waits at each stage of a reply."""

import math
from typing import Literal

LatencyKind = Literal["eou", "llm_ttft", "tts_ttfb"]


class LatencyStats:
    def __init__(self) -> None:
        self._samples: dict[str, list[float]] = {}

    def add(self, kind: LatencyKind, seconds: float) -> None:
        # Metrics report -1 when a value wasn't measured.
        if seconds >= 0:
            self._samples.setdefault(kind, []).append(seconds)

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            kind: {"p50_ms": _percentile_ms(values, 50), "p95_ms": _percentile_ms(values, 95), "n": len(values)}
            for kind, values in self._samples.items()
        }


def _percentile_ms(values: list[float], pct: int) -> int:
    """Nearest-rank percentile, in milliseconds."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return round(ordered[rank - 1] * 1000)
