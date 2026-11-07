"""Runtime wiring helpers and PhoneAgent construction (no LiveKit session or room needed)."""

import pytest

import agent
import prompt
import workflow
from console_config import Config
from dead_air import DeadAirConfig
from prompt import builtin_instructions, opening_line
from workflow import PathTool

CONSENT = "यह call quality के लिए record हो रही है।"
LEAD = {"lead_id": "L1", "name": "Ramesh"}

GRAPH = {
    "steps": [
        {"id": "s1", "name": "Greet", "type": "start", "prompt": "Greet {{lead.name}}."},
        {"id": "s2", "name": "City", "type": "collect", "prompt": "Ask the city.", "field": "city"},
        {"id": "s3", "name": "Wrap up", "type": "end", "prompt": "Say bye.", "outcome": "INTERESTED"},
    ],
    "paths": [
        {"from": "s1", "to": "s2", "label": "Driver is happy to talk"},
        {"from": "s2", "to": "s3", "label": "Driver gave a city"},
    ],
}


def snapshot(workflow=None, **overrides) -> dict:
    snap = {
        "agent_id": 1,
        "version": 2,
        "name": "Leads",
        "persona_name": "Anjali",
        "settings": {},
        "script": [{"title": "Your job", "body_rendered": "Qualify the driver."}],
        "knowledge": [],
        "workflow": workflow,
    }
    snap.update(overrides)
    return snap


def console(snap: dict) -> Config:
    return Config("console", snap, 7)


@pytest.fixture(autouse=True)
def cascaded_pipeline(monkeypatch):
    # Independent of the local .env: agents default to a cascaded pipeline, no handoff number.
    monkeypatch.setattr(agent, "PIPELINE", "sarvam")
    monkeypatch.setattr(agent, "HANDOFF_SIP_URI", "")


TRANSFER_GRAPH = {
    "steps": [
        {"id": "s1", "name": "Greet", "type": "start", "prompt": "Greet."},
        {"id": "t1", "name": "Hand over", "type": "transfer", "prompt": "Hand over to a person."},
    ],
    "paths": [{"from": "s1", "to": "t1", "label": "Driver wants a person"}],
}

LOOP_GRAPH = {
    "steps": [
        {"id": "a", "name": "A", "type": "start", "prompt": ""},
        {"id": "b", "name": "B", "type": "prompt", "prompt": ""},
    ],
    "paths": [{"from": "a", "to": "b", "label": "go b"}, {"from": "b", "to": "a", "label": "go a"}],
}


def tool_named(a, name):
    return next(t for t in a.tools if t.id == name)


def test_path_tool_schema_with_and_without_value():
    with_value = agent.path_tool_schema(PathTool("go_to_city", "Driver gave a city", "s2", True))
    assert with_value == {
        "name": "go_to_city",
        "description": "Driver gave a city",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string", "description": "What the driver answered"}},
            "required": ["value"],
        },
    }
    without = agent.path_tool_schema(PathTool("go_to_wrap_up", "Driver agreed", "s3", False))
    assert without == {
        "name": "go_to_wrap_up",
        "description": "Driver agreed",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }


def test_dead_air_config_from_settings_and_defaults():
    assert agent.dead_air_config(None) == agent.DEAD_AIR_CONFIG
    assert agent.dead_air_config({}) == agent.DEAD_AIR_CONFIG
    custom = agent.dead_air_config({"dead_air": {"enabled": True, "nudge_s": 5, "second_nudge_s": 10, "hang_up_s": 20}})
    assert custom == DeadAirConfig(nudge_s=5.0, second_nudge_s=10.0, hang_up_s=20.0)
    # Partial settings keep the env defaults for the rest.
    partial = agent.dead_air_config({"dead_air": {"nudge_s": 6}})
    assert partial.nudge_s == 6.0 and partial.hang_up_s == agent.DEAD_AIR_CONFIG.hang_up_s
    # Nonsense (wrong types, out of order) falls back to the defaults rather than breaking the call.
    assert agent.dead_air_config({"dead_air": {"nudge_s": "soon"}}) == agent.DEAD_AIR_CONFIG
    assert agent.dead_air_config({"dead_air": {"nudge_s": 30, "second_nudge_s": 9}}) == agent.DEAD_AIR_CONFIG
    assert agent.dead_air_config({"dead_air": "on"}) == agent.DEAD_AIR_CONFIG

    assert agent.dead_air_enabled(None) is agent.DEAD_AIR_ENABLED
    assert agent.dead_air_enabled({"dead_air": {"enabled": False}}) is False
    assert agent.dead_air_enabled({"dead_air": {"enabled": True}}) is True
    assert agent.dead_air_enabled({"dead_air": {"enabled": "no"}}) is agent.DEAD_AIR_ENABLED


def test_mood_enabled_needs_env_and_setting(monkeypatch):
    monkeypatch.setattr(agent, "MOOD_ENABLED", False)
    assert agent.mood_enabled({"mood_adaptation": True}) is False
    assert agent.mood_enabled(None) is False
    monkeypatch.setattr(agent, "MOOD_ENABLED", True)
    assert agent.mood_enabled({"mood_adaptation": False}) is False
    assert agent.mood_enabled({"mood_adaptation": True}) is True
    # Setting absent (or not a bool): defaults to on, so the env decides.
    assert agent.mood_enabled(None) is True
    assert agent.mood_enabled({}) is True
    assert agent.mood_enabled({"mood_adaptation": "no"}) is True


def test_events_url_whenever_console_configured(monkeypatch):
    monkeypatch.setenv("DASHBOARD_URL", "http://127.0.0.1:8787/")
    assert agent.events_url() == "http://127.0.0.1:8787/api/runtime/events"
    monkeypatch.setenv("DASHBOARD_URL", "")
    monkeypatch.delenv("DASHBOARD_REPORT_URL", raising=False)
    assert agent.events_url() == ""


def test_opening_line_consent_only_when_recording():
    for lead in ({}, {"previously_interested": True}):
        assert opening_line(lead, recording=True).endswith(" " + CONSENT)
        assert CONSENT not in opening_line(lead, recording=False)
        assert opening_line(lead, recording=False) == opening_line(lead)  # today's default (env off)


def test_opening_line_uses_persona():
    assert "main Anjali, Carrum Mobility" in opening_line({}, persona_name="Anjali")
    assert "main Anjali, Carrum Mobility" in opening_line({"previously_interested": True}, persona_name="Anjali")
    # No persona given: exactly today's text.
    assert opening_line({}).startswith("Namaste sir, main Carrum Mobility se AI calling assistant")


def test_builtin_when_no_snapshot():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, Config("builtin", None, None))
    assert a.instructions == builtin_instructions(LEAD, agent.GEMINI_LANGUAGE_RULES)
    assert a.base_instructions == a.instructions
    assert a.workflow is None
    assert {t.id for t in a.tools} == {"record_outcome", "end_call", "transfer_to_telecaller"}
    # Default construction (no cfg) is today's agent.
    assert agent.PhoneAgent(LEAD).instructions == a.instructions


def test_snapshot_without_workflow_uses_script_and_persona_opening():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot()))
    assert a.workflow is None
    assert "You are Anjali" in a.instructions and "Qualify the driver." in a.instructions
    assert "Your opening line: Namaste sir, main Anjali, Carrum Mobility" in a.instructions
    assert "If the driver speaks first" in a.instructions
    assert a.opening == opening_line(LEAD, persona_name="Anjali")


def test_snapshot_workflow_starts_and_registers_path_tools():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    assert a.workflow is not None and a.workflow.current.name == "Greet"
    assert "Current step: Greet" in a.instructions and "Greet Ramesh." in a.instructions
    assert "- Driver is happy to talk: call go_to_city" in a.instructions
    # Every path tool of the graph is registered up front.
    assert {t.id for t in a.tools} == {
        "record_outcome", "end_call", "transfer_to_telecaller", "go_to_city", "go_to_wrap_up"
    }
    # ...but the prompt only offers the current step's paths.
    assert "go_to_wrap_up" not in a.instructions


def test_all_path_tools_registered_once():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    names = [t.id for t in a.tools]
    for tool in a.workflow.all_path_tools():
        assert names.count(tool.name) == 1


def test_sarvam_agent_keeps_switch_language_with_path_tools():
    a = agent.SarvamPhoneAgent(LEAD, console(snapshot({"id": 1, "graph": GRAPH})))
    assert {"switch_language", "go_to_city", "go_to_wrap_up", "record_outcome"} <= {t.id for t in a.tools}


def test_bad_snapshot_falls_back_to_builtin(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("bad console data")

    monkeypatch.setattr(agent, "build_instructions", boom)
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    assert a.instructions == builtin_instructions(LEAD, agent.GEMINI_LANGUAGE_RULES)
    assert a.workflow is None
    assert a.opening == opening_line(LEAD)
    assert {t.id for t in a.tools} == {"record_outcome", "end_call", "transfer_to_telecaller"}


async def test_path_tool_moves_step_and_emits_events():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    events = []
    a.emit = lambda type, payload: events.append((type, payload))
    a.mood_note = "Caller sounds annoyed."
    tool = next(t for t in a.tools if t.id == "go_to_city")
    assert await tool({}) == "Now at step City."
    assert a.workflow.current.name == "City"
    assert "Current step: City" in a.base_instructions
    assert a.instructions == a.base_instructions + "\n\nCaller sounds annoyed."  # mood note kept
    assert events == [("step_entered", {"step_id": "s2", "step_name": "City"})]
    # A path not valid from the current step is refused by the engine.
    assert await tool({}) == "That path isn't available from City."
    assert a.workflow.current.name == "City"

    collect = next(t for t in a.tools if t.id == "go_to_wrap_up")
    assert await collect({}) == "Say what the driver answered in `value`."
    assert a.workflow.current.name == "City"
    assert await collect({"value": "Pune"}) == "Now at step Wrap up."
    assert events[-2:] == [
        ("step_entered", {"step_id": "s3", "step_name": "Wrap up"}),
        ("field_captured", {"field": "city", "value": "Pune"}),
    ]
    assert a.workflow.path == ["Greet", "City", "Wrap up"]


async def test_transition_updates_instructions_not_tools(monkeypatch):
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    calls = []

    async def update_instructions(text):
        calls.append(("instructions", text))

    async def update_tools(tools):
        calls.append(("tools", tools))

    monkeypatch.setattr(a, "update_instructions", update_instructions)
    monkeypatch.setattr(a, "update_tools", update_tools)
    assert await next(t for t in a.tools if t.id == "go_to_city")({}) == "Now at step City."
    assert [kind for kind, _ in calls] == ["instructions"]
    assert calls[0][1] == a.base_instructions


async def test_path_tool_never_raises(monkeypatch):
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    tool = next(t for t in a.tools if t.id == "go_to_city")

    def boom(*_a, **_k):
        raise RuntimeError("bad step")

    monkeypatch.setattr(agent, "build_instructions", boom)
    result = await tool({})
    assert isinstance(result, str) and result


async def test_end_step_wrong_disposition_refused():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    await next(t for t in a.tools if t.id == "go_to_city")({})
    await next(t for t in a.tools if t.id == "go_to_wrap_up")({"value": "Pune"})
    refused = await a.record_outcome(disposition="NI", reason="r", summary="s")
    assert refused == "This step ends with INTERESTED. Call record_outcome with disposition INTERESTED."
    assert a.outcome is None
    ok = await a.record_outcome(disposition="INTERESTED", reason="r", summary="s")
    assert ok == "Recorded. Now say your closing line."
    assert a.outcome["disposition"] == "INTERESTED"


async def test_record_outcome_unguarded_without_workflow():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot()))
    assert await a.record_outcome(disposition="NI", reason="r", summary="s") == "Recorded. Now say your closing line."


def test_recording_default_follows_env(monkeypatch):
    monkeypatch.delenv("RECORDING_ENABLED", raising=False)
    assert CONSENT not in opening_line({})
    monkeypatch.setenv("RECORDING_ENABLED", "false")
    assert CONSENT not in opening_line({})
    monkeypatch.setenv("RECORDING_ENABLED", "true")
    assert opening_line({}).endswith(" " + CONSENT)
    assert CONSENT not in opening_line({}, recording=False)


async def test_gemini_step_change_returns_step_block_without_instruction_update(monkeypatch):
    a = agent.PhoneAgent(
        LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})), pipeline="gemini-live"
    )
    start = a.base_instructions
    calls = []

    async def update_instructions(text):
        calls.append(text)

    monkeypatch.setattr(a, "update_instructions", update_instructions)
    result = await tool_named(a, "go_to_city")({})
    block = prompt.step_block(
        {"name": "City", "type": "collect", "prompt": "Ask the city."},
        LEAD,
        [{"name": "go_to_wrap_up", "label": "Driver gave a city"}],
    )
    assert result == "Now at step City. Instructions for you; say only the words meant for the driver.\n" + block
    assert "- Driver gave a city: call go_to_wrap_up" in result
    assert calls == [] and a.base_instructions == start
    end = await tool_named(a, "go_to_wrap_up")({"value": "Pune"})
    assert "Record the outcome as INTERESTED with record_outcome" in end
    assert calls == []


async def test_cascaded_step_change_updates_instructions(monkeypatch):
    a = agent.PhoneAgent(
        LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})), pipeline="sarvam"
    )
    calls = []

    async def update_instructions(text):
        calls.append(text)

    monkeypatch.setattr(a, "update_instructions", update_instructions)
    assert await tool_named(a, "go_to_city")({}) == "Now at step City."
    assert calls == [a.base_instructions] and "Current step: City" in calls[0]


def test_step_updates_instructions_by_pipeline():
    assert agent.step_updates_instructions("gemini-live") is False
    assert agent.step_updates_instructions("sarvam") is True
    assert agent.step_updates_instructions("elevenlabs") is True


async def test_transfer_step_without_handoff_offers_callback():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": TRANSFER_GRAPH})))
    await tool_named(a, "go_to_hand_over")({})
    assert prompt.NO_TRANSFER_DIRECTION in a.instructions
    assert "tell the driver you are connecting them" not in a.instructions


async def test_transfer_step_with_handoff_connects(monkeypatch):
    monkeypatch.setattr(agent, "HANDOFF_SIP_URI", "sip:desk@example.test")
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": TRANSFER_GRAPH})))
    await tool_named(a, "go_to_hand_over")({})
    assert prompt.TRANSFER_DIRECTION in a.instructions


def test_call_config_builtin_when_snapshot_unusable(monkeypatch):
    cfg = console(snapshot())
    good = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, cfg)
    assert agent.call_config(cfg, good) is cfg

    def boom(*_a, **_k):
        raise RuntimeError("bad console data")

    monkeypatch.setattr(agent, "build_instructions", boom)
    bad = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, cfg)
    fallback = agent.call_config(cfg, bad)
    assert fallback.source == "builtin" and fallback.version_id is None
    builtin = Config("builtin", None, None)
    assert agent.call_config(builtin, bad) is builtin


async def test_loop_cap_records_unresolved():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": LOOP_GRAPH})))
    results = []
    for _ in range(6):
        results.append(await tool_named(a, "go_to_b")({}))
        results.append(await tool_named(a, "go_to_a")({}))
    assert any(r == workflow.CAPPED_MESSAGE for r in results)
    assert a.outcome["disposition"] == "UNRESOLVED"
    assert a.outcome["reason"] == "workflow loop limit reached"
    assert set(a.outcome) == set(agent.capped_outcome())
    assert a.outcome["do_not_call"] is False and a.outcome["summary"] == ""


async def test_loop_cap_keeps_recorded_outcome():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": LOOP_GRAPH})))
    await a.record_outcome(disposition="CBR", reason="later", summary="s")
    for _ in range(6):
        await tool_named(a, "go_to_b")({})
        await tool_named(a, "go_to_a")({})
    assert a.outcome["disposition"] == "CBR"


async def test_end_call_refused_on_end_step_with_wrong_disposition():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    await a.record_outcome(disposition="NI", reason="r", summary="s")  # recorded before the end step
    await tool_named(a, "go_to_city")({})
    await tool_named(a, "go_to_wrap_up")({"value": "Pune"})
    refused = await a.end_call(None)
    assert refused == "This step ends with INTERESTED. Call record_outcome with disposition INTERESTED."


async def test_shutdown_report_before_caller_joins(monkeypatch):
    """The shutdown callback is registered before the participant wait and copes with no config yet."""
    import asyncio
    from types import SimpleNamespace

    callbacks, sent = [], []

    class Ctx:
        room = SimpleNamespace(name="call-early")
        job = SimpleNamespace(metadata="")
        proc = SimpleNamespace(userdata={})
        log_context_fields: dict = {}

        def add_shutdown_callback(self, cb):
            callbacks.append(cb)

        async def wait_for_participant(self, **_kw):
            raise asyncio.CancelledError  # the job ends before anyone joins

    async def fake_send(url, report, key, secret):
        sent.append(report)
        return True

    monkeypatch.setattr(agent, "DASHBOARD_REPORT_URL", "http://127.0.0.1:9/api/report")
    monkeypatch.setattr(agent, "send_report", fake_send)
    monkeypatch.setenv("DASHBOARD_URL", "")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "s")
    try:
        await agent.entrypoint(Ctx())
    except asyncio.CancelledError:
        pass
    assert len(callbacks) == 1
    await callbacks[0]()
    assert sent[0]["disposition"] == "NOT_CONNECTED"
    assert "agent_version_id" not in sent[0] and "step_path" not in sent[0] and "captured" not in sent[0]


LOOP_END_GRAPH = {
    "steps": LOOP_GRAPH["steps"] + [{"id": "z", "name": "Z", "type": "end", "prompt": "", "outcome": "NI"}],
    "paths": LOOP_GRAPH["paths"] + [{"from": "b", "to": "z", "label": "done"}],
}


async def test_loop_cap_stops_the_workflow():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": LOOP_END_GRAPH})))
    for _ in range(2):
        assert await tool_named(a, "go_to_b")({}) == "Now at step B."
        assert await tool_named(a, "go_to_a")({}) == "Now at step A."
    assert await tool_named(a, "go_to_b")({}) == "Now at step B."
    assert await tool_named(a, "go_to_a")({}) == workflow.CAPPED_MESSAGE
    assert await tool_named(a, "go_to_z")({}) == workflow.CAPPED_MESSAGE  # an end step, refused once stopped
    assert a.workflow.stopped and a.workflow.current.name == "B"
    ok = await a.record_outcome(disposition="UNRESOLVED", reason="workflow loop limit reached", summary="s")
    assert ok == "Recorded. Now say your closing line."


async def test_stopped_workflow_skips_end_step_guard(monkeypatch):
    from types import SimpleNamespace

    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    await tool_named(a, "go_to_city")({})
    await tool_named(a, "go_to_wrap_up")({"value": "Pune"})
    a.workflow.stopped = True  # e.g. restored from a capped state
    ok = await a.record_outcome(disposition="UNRESOLVED", reason="workflow loop limit reached", summary="s")
    assert ok == "Recorded. Now say your closing line."
    deleted = []

    async def playout():
        return None

    async def delete_room():
        deleted.append(True)

    monkeypatch.setattr(agent, "get_job_context", lambda: SimpleNamespace(delete_room=delete_room))
    assert await a.end_call(SimpleNamespace(wait_for_playout=playout)) is None
    assert deleted == [True]


async def test_end_step_outcome_overridden_on_second_identical_disposition(monkeypatch):
    from types import SimpleNamespace

    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    await tool_named(a, "go_to_city")({})
    await tool_named(a, "go_to_wrap_up")({"value": "Pune"})
    refusal = "This step ends with INTERESTED. Call record_outcome with disposition INTERESTED."
    assert await a.record_outcome(disposition="NI", reason="r", summary="s") == refusal
    assert await a.record_outcome(disposition="CBR", reason="r", summary="s") == refusal  # a different one
    assert a.outcome is None
    ok = await a.record_outcome(disposition="CBR", reason="later", summary="s")
    assert ok == "Recorded. Now say your closing line."
    assert a.outcome["disposition"] == "CBR" and a.outcome["end_step_outcome_overridden"] is True

    async def playout():
        return None

    async def delete_room():
        return None

    monkeypatch.setattr(agent, "get_job_context", lambda: SimpleNamespace(delete_room=delete_room))
    assert await a.end_call(SimpleNamespace(wait_for_playout=playout)) is None


async def test_end_step_outcome_matching_step_is_not_overridden():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    await tool_named(a, "go_to_city")({})
    await tool_named(a, "go_to_wrap_up")({"value": "Pune"})
    await a.record_outcome(disposition="NI", reason="r", summary="s")
    await a.record_outcome(disposition="INTERESTED", reason="r", summary="s")
    assert "end_step_outcome_overridden" not in a.outcome


def test_unusable_snapshot_settings_fall_back_to_env_defaults(monkeypatch):
    settings = {"dead_air": {"enabled": not agent.DEAD_AIR_ENABLED, "nudge_s": 1, "second_nudge_s": 2,
                             "hang_up_s": 3}, "mood_adaptation": False}
    cfg = console(snapshot(settings=settings))
    good = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, cfg)
    assert agent.call_settings(cfg, good) == (cfg, settings)

    def boom(*_a, **_k):
        raise RuntimeError("bad console data")

    monkeypatch.setattr(agent, "build_instructions", boom)
    monkeypatch.setattr(agent, "MOOD_ENABLED", True)
    bad = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, cfg)
    call_cfg, call_settings = agent.call_settings(cfg, bad)
    assert call_cfg.source == "builtin"
    assert agent.dead_air_enabled(call_settings) is agent.DEAD_AIR_ENABLED
    assert agent.dead_air_config(call_settings) == agent.DEAD_AIR_CONFIG
    assert agent.mood_enabled(call_settings) is True


async def test_captured_answers_for_the_report():
    assert agent.captured_answers(None) is None
    plain = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot()))
    assert agent.captured_answers(plain) is None
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    assert agent.captured_answers(a) == {}
    await tool_named(a, "go_to_city")({})
    await tool_named(a, "go_to_wrap_up")({"value": "Pune"})
    answers = agent.captured_answers(a)
    assert answers == {"city": "Pune"} and answers is not a.workflow.captured


async def test_start_step_path_waits_until_the_agent_has_spoken():
    # The caller says "hello" first and the model takes the start step's path before saying a word.
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    a.opening_guard = True  # on in live calls (entrypoint)
    events = []
    a.emit = lambda type, payload: events.append(type)
    refused = await tool_named(a, "go_to_city")({})
    assert a.opening in refused and "Ji, hello sir" in refused
    assert a.workflow.current.name == "Greet" and a.workflow.transitions == 0 and events == []
    a.has_spoken = True
    assert await tool_named(a, "go_to_city")({}) == "Now at step City."
    assert events == ["step_entered"]


async def test_start_step_guard_is_off_unless_the_call_turns_it_on():
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot({"id": 1, "graph": GRAPH})))
    assert a.opening_guard is False and a.has_spoken is False
    assert await tool_named(a, "go_to_city")({}) == "Now at step City."


def test_spoken_text_counts_words_not_tool_calls():
    from livekit.agents import llm

    def chunk(content=None, tool_calls=()):
        return llm.ChatChunk(id="c", delta=llm.ChoiceDelta(role="assistant", content=content, tool_calls=list(tool_calls)))

    call = llm.FunctionToolCall(name="go_to_city", arguments="{}", call_id="1")
    assert agent.spoken_text(chunk("Namaste")) is True
    assert agent.spoken_text("Ji sir") is True
    assert agent.spoken_text(chunk(tool_calls=[call])) is False
    assert agent.spoken_text(chunk("  ")) is False
    assert agent.spoken_text(" ") is False
    assert agent.spoken_text(llm.ChatChunk(id="u")) is False


async def test_reply_text_marks_the_agent_as_having_spoken(monkeypatch):
    from livekit.agents import llm

    call = llm.FunctionToolCall(name="go_to_city", arguments="{}", call_id="1")
    chunks = [
        llm.ChatChunk(id="1", delta=llm.ChoiceDelta(role="assistant", tool_calls=[call])),
        llm.ChatChunk(id="2", delta=llm.ChoiceDelta(role="assistant", content="Ji, hello sir!")),
    ]

    async def fake_llm_node(_agent, _ctx, _tools, _settings):
        for c in chunks:
            yield c

    monkeypatch.setattr(agent.Agent.default, "llm_node", fake_llm_node)
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot()))
    seen = []
    async for c in a.llm_node(None, [], None):
        seen.append((c, a.has_spoken))
    # Passed through untouched; only the text chunk marks speech, at the moment it goes by.
    assert seen == [(chunks[0], False), (chunks[1], True)]


async def test_realtime_audio_marks_the_agent_as_having_spoken(monkeypatch):
    async def fake_audio_node(_agent, audio, _settings):
        async for frame in audio:
            yield frame

    async def frames():
        yield "frame-1"
        yield "frame-2"

    monkeypatch.setattr(agent.Agent.default, "realtime_audio_output_node", fake_audio_node)
    a = agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot()))
    assert a.has_spoken is False
    assert [f async for f in a.realtime_audio_output_node(frames(), None)] == ["frame-1", "frame-2"]
    assert a.has_spoken is True


def test_dead_air_runs_only_when_account_workflow_and_agent_allow_it(monkeypatch):
    monkeypatch.setattr(agent, "DEAD_AIR_ENABLED", True)
    wf_on = {"id": 1, "graph": GRAPH, "dead_air_enabled": True}
    wf_off = {"id": 1, "graph": GRAPH, "dead_air_enabled": False}
    assert agent.dead_air_on(None) is True
    assert agent.dead_air_on(snapshot()) is True  # older snapshots say nothing: on
    assert agent.dead_air_on(snapshot(wf_on, account={"dead_air_enabled": True})) is True
    assert agent.dead_air_on(snapshot(account={"dead_air_enabled": False})) is False
    assert agent.dead_air_on(snapshot(wf_off)) is False
    assert agent.dead_air_on(snapshot(wf_on, settings={"dead_air": {"enabled": False}})) is False
    # Junk never turns it off.
    assert agent.dead_air_on(snapshot(account={"dead_air_enabled": "no"}, workflow="x")) is True
    assert agent.dead_air_on(snapshot(account="off")) is True
    # The agent's own switch falls back to the worker default.
    monkeypatch.setattr(agent, "DEAD_AIR_ENABLED", False)
    assert agent.dead_air_on(snapshot(wf_on, account={"dead_air_enabled": True})) is False
    assert agent.dead_air_on(snapshot(settings={"dead_air": {"enabled": True}})) is True
