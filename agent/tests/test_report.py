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


def test_report_includes_version_and_step_path():
    report = build_report(**ARGS, turns=None, agent_version_id=7, step_path=["a", "b"])
    assert report["agent_version_id"] == 7 and report["step_path"] == ["a", "b"]
    plain = build_report(**ARGS, turns=None)
    assert "agent_version_id" not in plain and "step_path" not in plain


def test_report_includes_captured_answers_when_given():
    report = build_report(**ARGS, turns=None, captured={"city": "Pune", "licence": "yes"})
    assert report["captured"] == {"city": "Pune", "licence": "yes"}
    assert "captured" not in build_report(**ARGS, turns=None)
    assert build_report(**ARGS, turns=None, captured={})["captured"] == {}
