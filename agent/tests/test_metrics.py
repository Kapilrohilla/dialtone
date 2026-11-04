from metrics import LatencyStats


def test_summary_percentiles():
    stats = LatencyStats()
    for i in range(1, 11):
        stats.add("eou", i / 10)
    assert stats.summary()["eou"] == {"p50_ms": 500, "p95_ms": 1000, "n": 10}


def test_empty_kinds_omitted():
    assert LatencyStats().summary() == {}


def test_negative_ignored():
    stats = LatencyStats()
    stats.add("llm_ttft", -1)
    assert stats.summary() == {}
