from report import build_report, send_report

ARGS = dict(
    room="call-1",
    outcome={"disposition": "CBR", "reason": "busy"},
    mood={"final": "rushed"},
    timeline=[],
    dead_air=[],
    latency={},
    behavior={},
)


def test_build_report_omits_turns_by_default():
    report = build_report(**ARGS, turns=None)
    assert "turns" not in report
    assert set(report) == {"room", "disposition", "outcome", "mood", "timeline", "dead_air", "latency", "behavior"}


def test_build_report_includes_turns_when_given():
    turns = [{"role": "user", "text": "haan", "at_s": 3.2}]
    assert build_report(**ARGS, turns=turns)["turns"] == turns


def test_build_report_disposition_from_outcome():
    assert build_report(**ARGS, turns=None)["disposition"] == "CBR"


async def test_send_report_false_on_connection_error():
    report = build_report(**ARGS, turns=None)
    assert await send_report("http://127.0.0.1:9/x", report, "key", "s" * 32) is False
