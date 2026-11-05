"""Runtime wiring helpers and PhoneAgent construction (no LiveKit session or room needed)."""

import agent
import prompt
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


def test_recording_default_follows_env():
    assert prompt.RECORDING_ENABLED is False  # tests run without RECORDING_ENABLED


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
    assert "agent_version_id" not in sent[0] and "step_path" not in sent[0]
