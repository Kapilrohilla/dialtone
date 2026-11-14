"""Text simulation for the console's "Try it" and "Test call": one agent reply per request.

The console (dashboard) posts the snapshot it wants to try, the whole transcript so far and the workflow
state from the previous reply. The server is stateless: it rebuilds the WorkflowRun from that state,
builds the same instructions a live call gets (system layer, script, current step, opening block),
asks a text LLM for the agent's next turn and applies its tool calls through the same workflow engine,
record_outcome rules and end-step guard as agent.py. Nothing is dialled and nothing is reported.

Only the dashboard may call it: a LiveKit-signed JWT with identity "console-sim".

Run: python simulate.py  (listens on 127.0.0.1:${SIM_PORT:-8790}). Importing this module starts nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Protocol

from aiohttp import web
from livekit import api

from prompt import (
    DISPOSITIONS,
    GEMINI_LANGUAGE_RULES,
    build_instructions,
    capped_outcome,
    end_step_check,
    end_step_refusal,
    identity,
    opening_instructions,
    opening_line,
)
from greeting import start_path_refusal
from workflow import WorkflowRun, path_tool_schema

logger = logging.getLogger("phone-agent.simulate")

SIM_IDENTITY = "console-sim"
# At most this many model calls per request; a model still calling tools after that gets cut off.
MAX_MODEL_CALLS = 4
# The whole reply (all model calls) must finish inside the dashboard's 20 s proxy timeout.
REQUEST_BUDGET_S = 18.0
MAX_MESSAGES = 200
MAX_TEXT = 2000
NO_REPLY = "…"
INTEREST_STRENGTHS = ("confirmed", "conditional", "tentative", "none")

# record_outcome exactly as agent.PhoneAgent.record_outcome takes it (tests check the field list).
RECORD_OUTCOME_SCHEMA = {
    "name": "record_outcome",
    "description": (
        "Record the call's outcome for the telecalling team. Call it before your closing line, and "
        "again if the outcome changes. Fill only what the driver actually said; leave the rest empty."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "disposition": {
                "type": "string",
                "enum": list(DISPOSITIONS),
                "description": (
                    "INTERESTED: genuine interest, incl. approved VDC/WTHINK cases. NI: clearly refuses. "
                    "NE: fails eligibility. CBR: asked to talk later. CDRP: call cut off with no outcome. "
                    "ISUDO: ineligible because of documents. ISUID: Uber ID blocked. HND: not a driver. "
                    "WRGN: wrong number. OWNVA: has own vehicle. ABULR: abusive. LANGUAGE_BARRIER: no shared "
                    "supported language. NOT_CONNECTED: no real conversation, e.g. voicemail. "
                    "UNRESOLVED: no clear outcome."
                ),
            },
            "reason": {"type": "string", "description": "Why this disposition, from what the driver said."},
            "summary": {"type": "string", "description": "Two or three sentences for the telecaller."},
            "interest_strength": {"type": "string", "enum": list(INTEREST_STRENGTHS)},
            "telecaller_followup_agreed": {"type": "boolean"},
            "callback_time": {"type": "string"},
            "city": {"type": "string"},
            "licence": {"type": "string"},
            "experience": {"type": "string"},
            "uber_id": {"type": "string"},
            "preferred_plan": {"type": "string"},
            "main_question": {"type": "string"},
            "do_not_call": {"type": "boolean"},
        },
        "required": ["disposition", "reason", "summary"],
    },
}

END_CALL_SCHEMA = {
    "name": "end_call",
    "description": "Hang up the call. Use only after record_outcome and your closing line.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

TRANSFER_SCHEMA = {
    "name": "transfer_to_telecaller",
    "description": (
        "Connect the driver to a person on the telecalling team right now. Use only when the driver "
        "agreed to talk to a person now. Call record_outcome first. If this returns that transfer isn't "
        "available, offer a callback instead."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


@dataclass
class ModelTurn:
    """One model reply: what it says, and the tools it calls ({"name", "arguments": dict, ...})."""

    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)


class ChatModel(Protocol):
    async def complete(self, instructions: str, messages: list[dict], tools: list[dict]) -> ModelTurn:
        """`messages`: {"role": "caller"|"agent", "text"} turns, then within one request
        {"role": "tool_call", "name", "arguments", "call_id", "extra"} and
        {"role": "tool_result", "name", "call_id", "output"} items. `tools`: OpenAI-style schemas."""
        ...


class GeminiChatModel:
    """The real model: livekit's Google LLM plugin, driven through llm.ChatContext with raw tools.

    Uses the same plugin (and its thought-signature handling via FunctionCall.extra) as the cascaded
    agent, so no second Gemini client to keep in step. Created lazily: needs GOOGLE_API_KEY."""

    def __init__(self, model: str | None = None):
        from livekit.plugins import google

        self._llm = google.LLM(model=model or os.getenv("SIM_LLM_MODEL", "gemini-3.6-flash"))

    async def complete(self, instructions: str, messages: list[dict], tools: list[dict]) -> ModelTurn:
        from livekit.agents import function_tool, llm

        ctx = llm.ChatContext.empty()
        ctx.add_message(role="system", content=instructions)
        if not messages or messages[0].get("role") != "caller":
            # Gemini wants the conversation to open with a user turn; the call has just connected.
            ctx.add_message(role="user", content="(The call has connected.)")
        for m in messages:
            role = m.get("role")
            if role == "caller":
                ctx.add_message(role="user", content=m["text"])
            elif role == "agent":
                ctx.add_message(role="assistant", content=m["text"])
            elif role == "tool_call":
                ctx.items.append(
                    llm.FunctionCall(
                        call_id=m["call_id"], name=m["name"], arguments=json.dumps(m.get("arguments") or {}),
                        extra=m.get("extra") or {},
                    )
                )
            elif role == "tool_result":
                ctx.items.append(
                    llm.FunctionCallOutput(call_id=m["call_id"], name=m["name"], output=m["output"], is_error=False)
                )

        async def unused(raw_arguments: dict) -> None:  # tools run in simulate.py, never by livekit
            return None

        raw_tools = [function_tool(unused, raw_schema=schema) for schema in tools]
        text: list[str] = []
        calls: list[dict] = []
        async with self._llm.chat(chat_ctx=ctx, tools=raw_tools) as stream:
            async for chunk in stream:
                delta = chunk.delta
                if delta is None:
                    continue
                if delta.content:
                    text.append(delta.content)
                for tc in delta.tool_calls:
                    try:
                        arguments = json.loads(tc.arguments or "{}")
                    except json.JSONDecodeError:
                        arguments = {}
                    calls.append({"name": tc.name, "arguments": arguments, "call_id": tc.call_id,
                                  "extra": tc.extra or {}})
        return ModelTurn(text="".join(text), tool_calls=calls)


def handoff_available() -> bool:
    """HANDOFF_SIP_URI is set, read per request (like agent.py's HANDOFF_SIP_URI, but monkeypatchable)."""
    return bool(os.getenv("HANDOFF_SIP_URI", "").strip())


class BadRequest(Exception):
    pass


def _str(value) -> str:
    return value if isinstance(value, str) else ""


def _bool(value) -> bool:
    return value if isinstance(value, bool) else False


def clean_outcome(raw) -> dict | None:
    """An outcome with record_outcome's fields, or None when `raw` isn't one (tampered state)."""
    if not isinstance(raw, dict) or raw.get("disposition") not in DISPOSITIONS:
        return None
    out = {}
    for key, default in capped_outcome().items():
        value = raw.get(key)
        out[key] = (_bool(value) if isinstance(default, bool) else _str(value)) if key in raw else default
    out["disposition"] = raw["disposition"]
    if out["interest_strength"] not in INTEREST_STRENGTHS:
        out["interest_strength"] = "none"
    if raw.get("end_step_outcome_overridden") is True:
        out["end_step_outcome_overridden"] = True
    return out


def clean_refused(raw) -> dict | None:
    """The end-step refusal kept in the state ({"step_id", "disposition"}), or None."""
    if (isinstance(raw, dict) and set(raw) == {"step_id", "disposition"}
            and isinstance(raw["step_id"], str) and raw["disposition"] in DISPOSITIONS):
        return {"step_id": raw["step_id"], "disposition": raw["disposition"]}
    return None


def parse_body(body) -> tuple[dict, dict, list[dict], dict | None]:
    if not isinstance(body, dict):
        raise BadRequest("Send a JSON object.")
    snapshot = body.get("snapshot")
    if not isinstance(snapshot, dict):
        raise BadRequest("snapshot must be an object.")
    lead = body.get("lead")
    if lead is None:
        lead = {}
    if not isinstance(lead, dict):
        raise BadRequest("lead must be an object.")
    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) > MAX_MESSAGES:
        raise BadRequest(f"messages must be a list of at most {MAX_MESSAGES} turns.")
    clean = []
    for m in messages:
        if (not isinstance(m, dict) or m.get("role") not in ("caller", "agent")
                or not isinstance(m.get("text"), str) or len(m["text"]) > MAX_TEXT):
            raise BadRequest(f'Each message needs role "caller" or "agent" and text of at most {MAX_TEXT} characters.')
        clean.append({"role": m["role"], "text": m["text"]})
    state = body.get("state")
    return snapshot, lead, clean, state if isinstance(state, dict) else None


class Simulation:
    """One request's worth of call: workflow position, outcome, and the tools the model may call."""

    def __init__(self, snapshot: dict, lead: dict, state: dict | None):
        self.snapshot, self.lead = snapshot, lead
        # Like PhoneAgent: company, persona and consent line from the snapshot, else the env.
        self.identity = identity(snapshot)
        self.persona = self.identity.persona
        workflow = snapshot.get("workflow")
        graph = workflow.get("graph") if isinstance(workflow, dict) else None
        graph = graph if isinstance(graph, dict) else {}
        # Like the live agent: a graph without a start step means script only.
        has_start = WorkflowRun(graph).start() is not None
        self.run = WorkflowRun.from_state(graph if has_start else {}, state)
        self.has_workflow = has_start
        self.outcome = clean_outcome(state.get("outcome")) if state else None
        # Like PhoneAgent.end_step_refused: carried between requests in the state.
        self.end_step_refused = clean_refused(state.get("end_step_refused")) if state else None
        self.ended = False
        self.path_names = {p.name for p in self.run.all_path_tools()} if has_start else set()
        # Like PhoneAgent.has_spoken: whether the agent has said anything yet (earlier turns or this reply).
        self.agent_spoke = False

    def current_step(self) -> dict | None:
        return asdict(self.run.current) if self.run.current is not None else None

    def instructions(self) -> str:
        step = self.run.current
        paths = [{"name": p.name, "label": p.description} for p in self.run.paths_from_current()] if step else []
        # Same as a live call on this host: the transfer direction depends on the handoff number.
        text = build_instructions(
            self.snapshot, self.lead, GEMINI_LANGUAGE_RULES, self.current_step(), paths,
            handoff_available=handoff_available(),
        )
        return f"{text}\n\n{opening_instructions(self.lead, self.persona, who=self.identity)}"

    def tools(self) -> list[dict]:
        paths = [path_tool_schema(p) for p in self.run.all_path_tools()] if self.has_workflow else []
        return paths + [RECORD_OUTCOME_SCHEMA, END_CALL_SCHEMA, TRANSFER_SCHEMA]

    def call_tool(self, name, arguments) -> str:
        args = arguments if isinstance(arguments, dict) else {}
        if name == "record_outcome":
            return self.record_outcome(args)
        if name == "end_call":
            if self.outcome is None:
                return "Call record_outcome first, then end the call."
            refusal = (None if self.run.stopped or self.outcome.get("end_step_outcome_overridden")
                       else end_step_refusal(self.current_step(), self.outcome["disposition"]))
            if refusal is not None:
                return refusal
            self.ended = True
            return "Call ended."
        if name == "transfer_to_telecaller":
            # The live tool's guards, in its order; only the SIP transfer itself is simulated.
            if not handoff_available():
                return "Live transfer isn't available. Offer a callback from the telecalling team instead."
            if self.outcome is None:
                return "Call record_outcome first."
            return "Transfer simulated."
        if isinstance(name, str) and name in self.path_names:
            current = self.run.current
            refusal = start_path_refusal(
                current.type if current else None, self.run.transitions, self.agent_spoke,
                opening_line(self.lead, self.persona, who=self.identity),
            )
            if refusal is not None:
                return refusal
            value = args.get("value")
            transition = self.run.take(name, value if isinstance(value, str) else None)
            if not transition.ok or transition.entered is None:
                if transition.capped and self.outcome is None:
                    self.outcome = capped_outcome()
                return transition.message
            # The instructions are rebuilt for the new step before the next model call.
            return f"Now at step {transition.entered.name}."
        return "Unknown tool."

    def record_outcome(self, args: dict) -> str:
        disposition = args.get("disposition")
        if disposition not in DISPOSITIONS:
            return f"Use one of: {', '.join(DISPOSITIONS)}."
        refusal, overridden = None, False
        if not self.run.stopped:
            refusal, overridden, self.end_step_refused = end_step_check(
                self.current_step(), disposition, self.end_step_refused
            )
        if refusal is not None:
            return refusal
        # The override flag comes only from the end-step check, never from the model's arguments.
        self.outcome = clean_outcome({**args, "disposition": disposition, "end_step_outcome_overridden": overridden})
        return "Recorded. Now say your closing line."

    def response(self, reply: str) -> dict:
        step = self.run.current
        return {
            "reply": reply,
            "state": {**self.run.to_state(), "outcome": self.outcome, "end_step_refused": self.end_step_refused},
            "step": {"id": step.id, "name": step.name} if step is not None else None,
            "outcome": self.outcome,
            "ended": self.ended,
        }


async def simulate_turn(model: ChatModel, snapshot: dict, lead: dict, messages: list[dict],
                        state: dict | None) -> dict:
    """The agent's next reply. Raises BadRequest for a snapshot the prompt can't be built from."""
    sim = Simulation(snapshot, lead, state)
    try:
        sim.instructions()
    except Exception as e:  # malformed snapshot contents (e.g. script items that aren't objects)
        raise BadRequest("The snapshot couldn't be turned into instructions.") from e
    convo = list(messages)
    said: list[str] = []
    sim.agent_spoke = any(m["role"] == "agent" for m in messages)
    for round_no in range(MAX_MODEL_CALLS):
        turn = await model.complete(sim.instructions(), convo, sim.tools())
        text = (turn.text or "").strip()
        if text:
            sim.agent_spoke = True
            said.append(text)
            convo.append({"role": "agent", "text": text})
        if not turn.tool_calls:
            break
        for i, tc in enumerate(turn.tool_calls):
            tc = tc if isinstance(tc, dict) else {}
            name = tc.get("name")
            call_id = tc.get("call_id") or f"sim_{round_no}_{i}"
            convo.append({"role": "tool_call", "name": _str(name), "arguments": tc.get("arguments"),
                          "call_id": call_id, "extra": tc.get("extra")})
            output = sim.call_tool(name, tc.get("arguments"))
            convo.append({"role": "tool_result", "name": _str(name), "call_id": call_id, "output": output})
            if sim.ended:
                break
        if sim.ended:
            break
    return sim.response(" ".join(said) or NO_REPLY)


def make_app(model: ChatModel | None = None, api_key: str | None = None, api_secret: str | None = None
             ) -> web.Application:
    key = api_key if api_key is not None else os.getenv("LIVEKIT_API_KEY", "")
    secret = api_secret if api_secret is not None else os.getenv("LIVEKIT_API_SECRET", "")
    # An empty secret would let anyone sign tokens: then every request is refused.
    verifier = api.TokenVerifier(key, secret) if key and secret else None
    holder: dict = {"model": model}

    def authorised(request: web.Request) -> bool:
        bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if verifier is None or not bearer:
            return False
        try:
            claims = verifier.verify(bearer)
        except Exception:
            return False
        return claims is not None and claims.identity == SIM_IDENTITY

    async def handle(request: web.Request) -> web.Response:
        if not authorised(request):
            return web.json_response({"detail": "Not allowed."}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"detail": "Send a JSON object."}, status=400)
        try:
            snapshot, lead, messages, state = parse_body(body)
            if holder["model"] is None:
                holder["model"] = GeminiChatModel()
            result = await asyncio.wait_for(
                simulate_turn(holder["model"], snapshot, lead, messages, state), REQUEST_BUDGET_S
            )
        except BadRequest as e:
            return web.json_response({"detail": str(e)}, status=400)
        except Exception:
            logger.exception("simulation failed")
            return web.json_response({"detail": "The simulation failed."}, status=502)
        return web.json_response(result)

    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.router.add_post("/simulate", handle)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    web.run_app(make_app(), host="127.0.0.1", port=int(os.getenv("SIM_PORT") or 8790))


if __name__ == "__main__":
    main()
