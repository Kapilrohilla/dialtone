"""Text simulation server (console "Try it" / "Test call"): scripted fake model, no network."""

import inspect

import pytest
from aiohttp.test_utils import TestClient, TestServer

import simulate
from console_config import runtime_token
from simulate import ModelTurn

KEY, SECRET = "APIsimkey", "sim-secret-0123456789abcdef0123456789"
LEAD = {"name": "Ramesh"}

GRAPH = {
    "steps": [
        {"id": "s1", "name": "Greet", "type": "start", "prompt": "Greet {{lead.name}}."},
        {"id": "s2", "name": "City", "type": "collect", "prompt": "Ask the city.", "field": "city"},
        {"id": "s3", "name": "Not interested", "type": "end", "prompt": "Say bye.", "outcome": "NI"},
    ],
    "paths": [
        {"from": "s1", "to": "s2", "label": "Driver is happy to talk"},
        {"from": "s1", "to": "s3", "label": "Driver says no"},
        {"from": "s2", "to": "s1", "label": "Driver wants to start over"},
    ],
}


def snapshot(workflow=True) -> dict:
    return {
        "agent_id": 1,
        "version": 0,
        "persona_name": "Anjali",
        "settings": {},
        "script": [{"title": "Your job", "body_rendered": "Qualify the driver."}],
        "knowledge": [],
        "workflow": {"id": 3, "revision": 1, "graph": GRAPH} if workflow else None,
    }


def call(name, **arguments):
    return {"name": name, "arguments": arguments}


class FakeModel:
    """Replays scripted turns; records what each call was given."""

    def __init__(self, *turns: ModelTurn, repeat: ModelTurn | None = None):
        self.turns = list(turns)
        self.repeat = repeat
        self.calls: list[dict] = []

    async def complete(self, instructions, messages, tools):
        self.calls.append({"instructions": instructions, "messages": list(messages), "tools": tools})
        if self.turns:
            return self.turns.pop(0)
        return self.repeat or ModelTurn(text="")


def token(identity="console-sim", secret=SECRET):
    return runtime_token(KEY, secret, identity=identity)


@pytest.fixture
def make_client():
    clients = []

    async def make(model):
        client = TestClient(TestServer(simulate.make_app(model, KEY, SECRET)))
        await client.start_server()
        clients.append(client)
        return client

    yield make


async def post(client, body, identity="console-sim", secret=SECRET):
    headers = {"Authorization": f"Bearer {token(identity, secret)}"} if identity else {}
    return await client.post("/simulate", json=body, headers=headers)


TRANSFER_GRAPH = {
    "steps": [
        {"id": "s1", "name": "Greet", "type": "start", "prompt": "Greet."},
        {"id": "t1", "name": "Hand over", "type": "transfer", "prompt": "Hand over to a person."},
    ],
    "paths": [{"from": "s1", "to": "t1", "label": "Driver wants a person"}],
}
AT_TRANSFER = {"current_step_id": "t1", "visits": {"s1": 1, "t1": 1}, "transitions": 1, "captured": {},
               "path": ["Greet", "Hand over"], "outcome": None}
OUTCOME = {"disposition": "INTERESTED", "reason": "Wants to join", "summary": "Agreed to talk to the team."}


def transfer_body(outcome=None):
    b = body([{"role": "caller", "text": "Haan, kisi se baat karao"}], {**AT_TRANSFER, "outcome": outcome})
    b["snapshot"]["workflow"]["graph"] = TRANSFER_GRAPH
    return b


def body(messages=(), state=None, workflow=True):
    return {"snapshot": snapshot(workflow), "lead": LEAD, "messages": list(messages), "state": state}


async def test_sim_requires_console_sim_token(make_client):
    model = FakeModel(repeat=ModelTurn(text="Namaste"))
    client = await make_client(model)
    try:
        assert (await post(client, body(), identity=None)).status == 401
        assert (await post(client, body(), identity="agent-runtime")).status == 401
        assert (await post(client, body(), secret="another-secret-0123456789abcdef-xyz")).status == 401
        bad = await client.post("/simulate", json=body(), headers={"Authorization": "Bearer not-a-jwt"})
        assert bad.status == 401
        assert model.calls == []
        assert (await post(client, body())).status == 200
    finally:
        await client.close()


async def test_sim_greeting_turn_returns_reply_and_start_step(make_client):
    model = FakeModel(ModelTurn(text="Namaste sir, main Anjali bol rahi hoon."))
    client = await make_client(model)
    try:
        r = await post(client, body())
        assert r.status == 200
        data = await r.json()
    finally:
        await client.close()
    assert data["reply"] == "Namaste sir, main Anjali bol rahi hoon."
    assert data["step"] == {"id": "s1", "name": "Greet"}
    assert data["outcome"] is None and data["ended"] is False
    assert data["state"]["current_step_id"] == "s1" and data["state"]["visits"] == {"s1": 1}
    assert data["state"]["transitions"] == 0 and data["state"]["outcome"] is None
    [first] = model.calls
    assert first["messages"] == []
    text = first["instructions"]
    assert "You are Anjali" in text and "Qualify the driver." in text
    assert "Current step: Greet" in text and "Greet Ramesh." in text
    assert "Your opening line: Namaste sir, main Anjali, Carrum Mobility se AI calling assistant" in text
    names = {t["name"] for t in first["tools"]}
    assert {"record_outcome", "end_call", "transfer_to_telecaller", "go_to_city", "go_to_greet",
            "go_to_not_interested"} <= names


async def test_sim_path_tool_moves_step(make_client):
    model = FakeModel(
        ModelTurn(tool_calls=[call("go_to_city")]),
        ModelTurn(text="Sir, aap kis city mein rehte hain?"),
    )
    client = await make_client(model)
    start = {"current_step_id": "s1", "visits": {"s1": 1}, "transitions": 0, "captured": {}, "path": ["Greet"],
             "outcome": None}
    messages = [{"role": "agent", "text": "Namaste sir"}, {"role": "caller", "text": "Haan ji, boliye"}]
    try:
        data = await (await post(client, body(messages, start))).json()
    finally:
        await client.close()
    assert data["reply"] == "Sir, aap kis city mein rehte hain?"
    assert data["step"] == {"id": "s2", "name": "City"}
    assert data["state"]["transitions"] == 1 and data["state"]["path"] == ["Greet", "City"]
    assert len(model.calls) == 2
    assert model.calls[0]["messages"] == messages
    assert "Current step: Greet" in model.calls[0]["instructions"]
    assert "Current step: City" in model.calls[1]["instructions"]
    tool_msgs = model.calls[1]["messages"][2:]
    assert tool_msgs[0]["role"] == "tool_call" and tool_msgs[0]["name"] == "go_to_city"
    assert tool_msgs[1]["role"] == "tool_result" and "City" in tool_msgs[1]["output"]
    assert tool_msgs[1]["call_id"] == tool_msgs[0]["call_id"]


async def test_sim_collect_step_captures_value_and_refuses_bad_paths(make_client):
    model = FakeModel(
        ModelTurn(tool_calls=[call("go_to_not_interested"), call("go_to_greet")]),
        ModelTurn(text="Theek hai."),
    )
    client = await make_client(model)
    at_city = {"current_step_id": "s2", "visits": {"s1": 1, "s2": 1}, "transitions": 1, "captured": {},
               "path": ["Greet", "City"], "outcome": None}
    try:
        data = await (await post(client, body([{"role": "caller", "text": "Pune"}], at_city))).json()
    finally:
        await client.close()
    results = [m["output"] for m in model.calls[1]["messages"] if m["role"] == "tool_result"]
    assert results[0] == "That path isn't available from City."
    assert results[1] == "Say what the driver answered in `value`."
    assert data["step"] == {"id": "s2", "name": "City"}


async def test_sim_end_step_records_outcome_and_ends(make_client):
    model = FakeModel(
        ModelTurn(tool_calls=[call("end_call")]),
        ModelTurn(tool_calls=[call("record_outcome", disposition="INTERESTED", reason="r", summary="s")]),
        ModelTurn(
            text="Theek hai sir, koi baat nahi.",
            tool_calls=[call("record_outcome", disposition="NI", reason="Said no", summary="Not interested."),
                        call("end_call")],
        ),
    )
    client = await make_client(model)
    at_end = {"current_step_id": "s3", "visits": {"s1": 1, "s3": 1}, "transitions": 1, "captured": {},
              "path": ["Greet", "Not interested"], "outcome": None}
    try:
        data = await (await post(client, body([{"role": "caller", "text": "Nahi chahiye"}], at_end))).json()
    finally:
        await client.close()
    results = [m["output"] for m in model.calls[2]["messages"] if m["role"] == "tool_result"]
    assert results[0] == "Call record_outcome first, then end the call."
    assert results[1] == "This step ends with NI. Call record_outcome with disposition NI."
    assert data["ended"] is True
    assert data["reply"] == "Theek hai sir, koi baat nahi."
    assert data["outcome"]["disposition"] == "NI" and data["outcome"]["reason"] == "Said no"
    assert data["outcome"]["do_not_call"] is False and data["outcome"]["interest_strength"] == "none"
    assert data["state"]["outcome"] == data["outcome"]
    assert len(model.calls) == 3


async def test_sim_tool_round_limit(make_client, monkeypatch):
    monkeypatch.delenv("HANDOFF_SIP_URI", raising=False)
    model = FakeModel(
        ModelTurn(text="Ek minute sir.", tool_calls=[call("transfer_to_telecaller")]),
        repeat=ModelTurn(tool_calls=[call("transfer_to_telecaller")]),
    )
    client = await make_client(model)
    try:
        data = await (await post(client, body([{"role": "caller", "text": "Kisi se baat karao"}]))).json()
    finally:
        await client.close()
    assert len(model.calls) == simulate.MAX_MODEL_CALLS == 4
    assert data["reply"] == "Ek minute sir."
    assert data["ended"] is False
    results = [m["output"] for m in model.calls[1]["messages"] if m["role"] == "tool_result"]
    assert results == ["Live transfer isn't available. Offer a callback from the telecalling team instead."]


async def test_sim_round_limit_without_text_replies_ellipsis(make_client):
    model = FakeModel(repeat=ModelTurn(tool_calls=[call("transfer_to_telecaller")]))
    client = await make_client(model)
    try:
        data = await (await post(client, body([{"role": "caller", "text": "hello"}]))).json()
    finally:
        await client.close()
    assert data["reply"] == "…" and len(model.calls) == 4


async def test_sim_capped_transition_records_unresolved(make_client):
    model = FakeModel(ModelTurn(tool_calls=[call("go_to_greet", value="Pune")]), ModelTurn(text="Dhanyavaad."))
    client = await make_client(model)
    capped = {"current_step_id": "s2", "visits": {"s1": 3, "s2": 2}, "transitions": 4, "captured": {},
              "path": ["Greet", "City"], "outcome": None}
    try:
        data = await (await post(client, body([{"role": "caller", "text": "phir se"}], capped))).json()
    finally:
        await client.close()
    assert data["outcome"]["disposition"] == "UNRESOLVED"
    assert data["outcome"]["reason"] == "workflow loop limit reached"
    assert data["step"] == {"id": "s2", "name": "City"}


async def test_sim_without_workflow_has_no_step(make_client):
    model = FakeModel(ModelTurn(text="Namaste"))
    client = await make_client(model)
    try:
        data = await (await post(client, body(workflow=False))).json()
    finally:
        await client.close()
    assert data["step"] is None and data["state"]["current_step_id"] is None
    names = {t["name"] for t in model.calls[0]["tools"]}
    assert names == {"record_outcome", "end_call", "transfer_to_telecaller"}
    assert "Current step" not in model.calls[0]["instructions"]


async def test_sim_tampered_state_and_bad_arguments_do_not_500(make_client):
    model = FakeModel(
        ModelTurn(tool_calls=[call("record_outcome", disposition="MAYBE", reason=3), call("nope"),
                              {"name": "go_to_city", "arguments": "garbage"}]),
        ModelTurn(text="Ji."),
    )
    client = await make_client(model)
    tampered = {"current_step_id": ["x"], "visits": "lots", "transitions": -4, "outcome": "INTERESTED"}
    try:
        r = await post(client, body([{"role": "caller", "text": "hi"}], tampered))
        assert r.status == 200
        data = await r.json()
    finally:
        await client.close()
    assert data["outcome"] is None
    results = [m["output"] for m in model.calls[1]["messages"] if m["role"] == "tool_result"]
    assert results[0].startswith("Use one of:")
    assert results[1] == "Unknown tool."
    assert data["step"] == {"id": "s2", "name": "City"}


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"snapshot": "x", "messages": []},
        {"snapshot": {}, "messages": "hi"},
        {"snapshot": {}, "messages": [{"role": "boss", "text": "x"}]},
        {"snapshot": {}, "messages": [{"role": "caller", "text": 5}]},
        {"snapshot": {}, "messages": [], "lead": "x"},
    ],
)
async def test_sim_bad_body_is_400(make_client, payload):
    model = FakeModel(repeat=ModelTurn(text="x"))
    client = await make_client(model)
    try:
        r = await client.post("/simulate", json=payload, headers={"Authorization": f"Bearer {token()}"})
        assert r.status == 400
        junk = await client.post("/simulate", data=b"{not json", headers={"Authorization": f"Bearer {token()}"})
        assert junk.status == 400
    finally:
        await client.close()
    assert model.calls == []


async def test_sim_model_failure_is_502(make_client):
    class Broken:
        async def complete(self, instructions, messages, tools):
            raise RuntimeError("quota")

    client = await make_client(Broken())
    try:
        r = await post(client, body())
        assert r.status == 502
    finally:
        await client.close()


def test_record_outcome_schema_matches_live_agent():
    import agent

    params = [p for p in inspect.signature(agent.PhoneAgent.record_outcome).parameters if p != "self"]
    schema = simulate.RECORD_OUTCOME_SCHEMA["parameters"]
    assert list(schema["properties"]) == params
    assert schema["properties"]["disposition"]["enum"] == list(agent.DISPOSITIONS)


def test_importing_simulate_starts_no_worker():
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c", "import sys, simulate; print('agent' in sys.modules)"],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("False")


async def test_gemini_model_drives_livekit_chat_context():
    from livekit.agents import llm

    seen = {}

    class Stream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def __aiter__(self):
            async def gen():
                yield llm.ChatChunk(id="1", delta=llm.ChoiceDelta(role="assistant", content="Ji "))
                yield llm.ChatChunk(id="2", delta=llm.ChoiceDelta(content="sir."))
                yield llm.ChatChunk(id="3", delta=llm.ChoiceDelta(tool_calls=[llm.FunctionToolCall(
                    name="go_to_city", arguments='{"value": "Pune"}', call_id="c9", extra={"google": "sig"})]))
            return gen()

    class FakeLLM:
        def chat(self, *, chat_ctx, tools):
            seen["ctx"], seen["tools"] = chat_ctx, tools
            return Stream()

    model = object.__new__(simulate.GeminiChatModel)
    model._llm = FakeLLM()
    messages = [
        {"role": "agent", "text": "Namaste"},
        {"role": "caller", "text": "Haan"},
        {"role": "tool_call", "name": "go_to_city", "arguments": {}, "call_id": "c1", "extra": None},
        {"role": "tool_result", "name": "go_to_city", "call_id": "c1", "output": "Now at step City."},
    ]
    sim = simulate.Simulation(snapshot(), LEAD, None)
    turn = await model.complete("INSTRUCTIONS", messages, sim.tools())
    assert turn.text == "Ji sir."
    assert turn.tool_calls == [{"name": "go_to_city", "arguments": {"value": "Pune"}, "call_id": "c9",
                                "extra": {"google": "sig"}}]
    types = [item.type for item in seen["ctx"].items]
    assert types == ["message", "message", "message", "message", "function_call", "function_call_output"]
    roles = [item.role for item in seen["ctx"].items if item.type == "message"]
    assert roles == ["system", "user", "assistant", "user"]
    assert {t.info.name for t in seen["tools"]} == {t["name"] for t in sim.tools()}


async def run_transfer(make_client, outcome=None):
    model = FakeModel(ModelTurn(tool_calls=[call("transfer_to_telecaller")]), ModelTurn(text="Ji sir."))
    client = await make_client(model)
    try:
        data = await (await post(client, transfer_body(outcome))).json()
    finally:
        await client.close()
    results = [m["output"] for m in model.calls[1]["messages"] if m["role"] == "tool_result"]
    return model, data, results


async def test_sim_transfer_unavailable_without_handoff(make_client, monkeypatch):
    import prompt

    monkeypatch.setenv("HANDOFF_SIP_URI", "  ")
    model, data, results = await run_transfer(make_client, OUTCOME)
    assert prompt.NO_TRANSFER_DIRECTION in model.calls[0]["instructions"]
    assert prompt.TRANSFER_DIRECTION not in model.calls[0]["instructions"]
    assert results == ["Live transfer isn't available. Offer a callback from the telecalling team instead."]


async def test_sim_transfer_requires_outcome(make_client, monkeypatch):
    import prompt

    monkeypatch.setenv("HANDOFF_SIP_URI", "sip:team@example.com")
    model, data, results = await run_transfer(make_client, None)
    assert prompt.TRANSFER_DIRECTION in model.calls[0]["instructions"]
    assert results == ["Call record_outcome first."]


async def test_sim_transfer_simulated_with_handoff_and_outcome(make_client, monkeypatch):
    monkeypatch.setenv("HANDOFF_SIP_URI", "sip:team@example.com")
    model, data, results = await run_transfer(make_client, OUTCOME)
    assert results == ["Transfer simulated."]
    assert data["outcome"]["disposition"] == "INTERESTED" and data["ended"] is False
