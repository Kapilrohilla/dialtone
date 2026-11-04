from mood import MoodReading, MoodTracker


def r(e, c=0.9, t=0, s=0.0) -> MoodReading:
    return MoodReading(emotion=e, sentiment=s, confidence=c, source="text", at_s=t)


def test_single_reading_does_not_switch():
    m = MoodTracker()
    assert m.observe(r("frustrated")) is None
    assert m.current == "neutral"


def test_two_agreeing_readings_switch():
    m = MoodTracker()
    m.observe(r("frustrated"))
    assert m.observe(r("frustrated", t=1)) == "frustrated"
    assert m.current == "frustrated"


def test_low_confidence_never_switches():
    m = MoodTracker()
    m.observe(r("confused", c=0.5))
    m.observe(r("confused", c=0.5, t=1))
    assert m.current == "neutral"
    assert len(m.timeline) == 2


def test_confident_anger_switches_immediately():
    m = MoodTracker()
    assert m.observe(r("angry", c=0.85)) == "angry"


def test_curt_refusal_then_neutral_stays_neutral():
    m = MoodTracker()
    m.observe(r("frustrated"))
    m.observe(r("neutral", t=1))
    assert m.current == "neutral"
    assert m.summary()["changes"] == 0


def test_summary_worst_and_avg():
    m = MoodTracker()
    m.observe(r("frustrated", s=-0.8, t=0))
    m.observe(r("frustrated", s=-0.6, t=1))
    m.observe(r("interested", s=0.0, t=2))
    m.observe(r("interested", s=0.0, t=3))
    s = m.summary()
    assert s["final"] == "interested"
    assert s["worst"] == "frustrated"
    assert s["changes"] == 2
    assert s["avg_sentiment"] == -0.35
    assert set(s) == {"final", "worst", "avg_sentiment", "changes"}
