"""Carrum Mobility phone agent: qualifies driver-partner leads in Hindi/Hinglish.

Two pipelines, picked with AGENT_PIPELINE:
- gemini-live (default): Gemini Live speech-to-speech. One model listens, thinks
  and speaks; it handles Hindi and regional languages natively. Needs GOOGLE_API_KEY.
- sarvam: Sarvam STT -> OpenAI LLM -> Sarvam TTS. Needs SARVAM_API_KEY + OPENAI_API_KEY.
- elevenlabs: same as sarvam, but ElevenLabs speaks. Also needs ELEVEN_API_KEY.

Lead record: dispatch the agent with JSON metadata, e.g.
  {"lead_id": "L123", "name": "Ramesh", "city": "Pune", "previously_interested": true}
and it skips questions the record already answers. Without one it treats the call as a fresh contact.

Approved pricing, offers and plan-routing rules go in knowledge.md next to this file. The agent
quotes only what is there; without it, it quotes no figures.

Every call ends with one "call ended" log line carrying the disposition and telecalling handoff.

Run locally:   python -m livekit.agents start agent.py --dev
Run in prod:   python -m livekit.agents start agent.py
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    AudioConfig,
    BackgroundAudioPlayer,
    BuiltinAudioClip,
    ConversationItemAddedEvent,
    JobContext,
    JobProcess,
    RunContext,
    function_tool,
    get_job_context,
)
from livekit.agents.metrics import EOUMetrics, LLMMetrics, RealtimeModelMetrics, TTSMetrics
from livekit.plugins import silero

from adapt import apply_mood, sends_mood_notes
from console_config import Config, dashboard_url, load_config, load_draft_config, web_test_agent_id
from behavior import BehaviorTracker, reply_latency_reliable
from dead_air import DeadAirConfig, DeadAirWatcher
from events import EventSink
from greeting import GreetingGate, greeting_instructions, start_path_refusal
from metrics import LatencyStats
from mood import MoodReading, MoodTracker
from prompt import BASE_INSTRUCTIONS, SCRIPT_FALLBACK, SYSTEM_LAYER  # noqa: F401  (layers live in prompt.py)
from prompt import (
    PERSONA_NAME,
    build_instructions,
    builtin_instructions,
    custom_hints,
    end_step_check,
    end_step_refusal,
    opening_instructions,
)
from prompt import (  # noqa: F401  (re-exported: tests and callers use agent.X)
    DEFAULT_LANGUAGE,
    DISPOSITIONS,
    GEMINI_LANGUAGE_RULES,
    LANGUAGES,
    capped_outcome,
    opening_line,
    step_block,
)
import voices
from report import build_report, send_report
from sentiment import make_classifier
from tone import mood_message, tone_guide
from workflow import PathTool, Step, WorkflowRun, path_tool_schema  # noqa: F401

load_dotenv()

logger = logging.getLogger("phone-agent")

AGENT_NAME = os.getenv("AGENT_NAME", "phone-agent")
PIPELINE = os.getenv("AGENT_PIPELINE", "gemini-live")
# Background sound under the call: none | office | callcenter | city | path to an audio file
# (relative to this folder, e.g. sounds/my-office.ogg). Default none: the built-in office clip has
# people talking in it, which callers hear as someone else on the line.
AMBIENCE = os.getenv("BACKGROUND_AMBIENCE") or "none"
# Built-in clips are recorded at very different levels (office is ~30x quieter than the
# crowded room), so each gets its own default gain. These land the noise ~25 dB under
# the voice: noticeable, never in the way. Override with BACKGROUND_VOLUME.
AMBIENCE_CLIPS = {
    "office": (BuiltinAudioClip.OFFICE_AMBIENCE, 3.0),
    "callcenter": (BuiltinAudioClip.CROWDED_ROOM, 0.08),
    "city": (BuiltinAudioClip.CITY_AMBIENCE, 0.3),
}

# Caller silence: check in, check in again, then hang up politely (seconds of silence).
DEAD_AIR_ENABLED = os.getenv("DEAD_AIR_ENABLED", "true").lower() == "true"
DEAD_AIR_CONFIG = DeadAirConfig(
    nudge_s=float(os.getenv("DEAD_AIR_NUDGE_S") or 4),
    second_nudge_s=float(os.getenv("DEAD_AIR_SECOND_NUDGE_S") or 9),
    hang_up_s=float(os.getenv("DEAD_AIR_HANG_UP_S") or 15),
)
# Caller mood: classify each caller turn and adapt tone and pace. Off until accuracy is checked.
MOOD_ENABLED = os.getenv("MOOD_ENABLED", "false").lower() == "true"
# Live transfer to a person (tel:+91… or sip:…) for upset callers who agree to it. Empty = off.
HANDOFF_SIP_URI = os.getenv("HANDOFF_SIP_URI", "").strip()
# Per-call report to the dashboard (on the media VM: http://127.0.0.1:8787/api/report). Empty = off.
DASHBOARD_REPORT_URL = os.getenv("DASHBOARD_REPORT_URL", "").strip()
# Include caller/agent turn text in reports, for labelling mood accuracy. Turn off afterwards.
MOOD_EVAL_CAPTURE = os.getenv("MOOD_EVAL_CAPTURE", "false").lower() == "true"

DEAD_AIR_PROMPTS = {
    "nudge": "The driver has gone quiet. In one short sentence, gently check if they can hear you, "
    "e.g. 'Hello sir, aap sun pa rahe hain?'",
    "second_nudge": "Still no reply. In one short sentence, say the line may be unclear and ask once more "
    "if they can hear you; say you'll try again later if not.",
    "hang_up": "Say a brief polite goodbye: you'll try again another time.",
}

BUILTIN_CONFIG = Config("builtin", None, None)

Disposition = Literal[DISPOSITIONS]


SARVAM_LANGUAGE_RULES = f"""
Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- If the driver speaks a different language, call `switch_language` once, then reply in that language.
  If it isn't supported, record LANGUAGE_BARRIER and close politely.
- Hinglish callers: reply in Hindi, keeping common English words as they are.
""".strip()



def _settings(snapshot: dict | None) -> dict:
    settings = snapshot.get("settings") if isinstance(snapshot, dict) else None
    return settings if isinstance(settings, dict) else {}


def _seconds(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def dead_air_config(settings: dict | None) -> DeadAirConfig:
    """Dead-air timings from the agent's settings; env defaults for anything missing. Bad values
    (wrong type, not increasing) fall back to the env defaults as a whole."""
    dead_air = settings.get("dead_air") if isinstance(settings, dict) else None
    if not isinstance(dead_air, dict):
        return DEAD_AIR_CONFIG
    timings = []
    for key in ("nudge_s", "second_nudge_s", "hang_up_s"):
        if key not in dead_air:
            timings.append(getattr(DEAD_AIR_CONFIG, key))
            continue
        value = _seconds(dead_air[key])
        if value is None:
            return DEAD_AIR_CONFIG
        timings.append(value)
    if not timings[0] < timings[1] < timings[2]:
        return DEAD_AIR_CONFIG
    return DeadAirConfig(nudge_s=timings[0], second_nudge_s=timings[1], hang_up_s=timings[2])


def dead_air_enabled(settings: dict | None) -> bool:
    dead_air = settings.get("dead_air") if isinstance(settings, dict) else None
    enabled = dead_air.get("enabled") if isinstance(dead_air, dict) else None
    return enabled if isinstance(enabled, bool) else DEAD_AIR_ENABLED


def dead_air_on(snapshot: dict | None) -> bool:
    """Dead-air handling runs only when the account, the agent's workflow and the agent all allow it.

    The account switch is added to the snapshot when the console serves it; the workflow's is in the
    published workflow. A level that says nothing (older snapshots, no workflow) allows it, and anything
    but an explicit false counts as allowing it. The agent's own switch falls back to DEAD_AIR_ENABLED."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    for level in (snap.get("account"), snap.get("workflow")):
        if isinstance(level, dict) and level.get("dead_air_enabled") is False:
            return False
    return dead_air_enabled(_settings(snap))


def spoken_text(chunk) -> bool:
    """Whether an LLM output chunk carries words the agent will say (not just a tool call)."""
    if isinstance(chunk, str):
        return bool(chunk.strip())
    content = getattr(getattr(chunk, "delta", None), "content", None)
    return isinstance(content, str) and bool(content.strip())


def mood_enabled(settings: dict | None) -> bool:
    """Mood adaptation needs the worker's MOOD_ENABLED and the agent's mood_adaptation (default on)."""
    enabled = settings.get("mood_adaptation") if isinstance(settings, dict) else None
    return MOOD_ENABLED and (enabled if isinstance(enabled, bool) else True)


def events_url() -> str:
    """Console events endpoint, or "" (sink off) when no console is configured."""
    base = dashboard_url()
    return f"{base}/api/runtime/events" if base else ""


def step_updates_instructions(pipeline: str) -> bool:
    """Whether a workflow step change rewrites the instructions. Not on Gemini Live: each instruction
    update there adds the whole prompt to the conversation as a model turn, so the new step goes back
    as the path tool's result instead."""
    return pipeline != "gemini-live"


def call_config(cfg: Config, agent) -> Config:
    """The config the call actually runs: built-in when the agent couldn't use the console snapshot."""
    if cfg.snapshot is not None and getattr(agent, "snapshot", None) is None:
        return BUILTIN_CONFIG
    return cfg


def call_settings(cfg: Config, agent) -> tuple[Config, dict]:
    """The config the call runs and its settings: env defaults (no settings) when the agent fell back to
    the built-in prompt, so dead air and mood never follow a snapshot the call isn't using."""
    cfg = call_config(cfg, agent)
    return cfg, _settings(cfg.snapshot)


def captured_answers(agent) -> dict | None:
    """The workflow's captured {field: value} answers for the call report; None without a workflow."""
    run = getattr(agent, "workflow", None)
    return dict(run.captured) if run is not None else None


def dispatch_metadata(metadata: str) -> dict:
    """The JSON dispatch metadata; empty when there is none."""
    try:
        data = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        logger.warning("dispatch metadata isn't JSON; ignoring it")
        return {}
    return data if isinstance(data, dict) else {}


def lead_record(metadata: str) -> dict:
    """The lead record passed as JSON dispatch metadata; empty when there is none. The console's
    voice-test marker ("web_test") is not part of the lead, so the agent never sees it as a fact."""
    return {k: v for k, v in dispatch_metadata(metadata).items() if k != "web_test"}


class PhoneAgent(Agent):
    def __init__(
        self,
        lead: dict,
        language_rules: str = GEMINI_LANGUAGE_RULES,
        cfg: Config | None = None,
        pipeline: str | None = None,
    ) -> None:
        self.lead = lead
        self.language_rules = language_rules
        self.pipeline = pipeline or PIPELINE
        self.snapshot: dict | None = None
        self.workflow: WorkflowRun | None = None
        self.persona_name: str | None = None
        # Sends call events (step_entered, field_captured); the entrypoint points it at the EventSink.
        self.emit = lambda type, payload: None
        # The current caller-mood note (cascaded pipelines), kept across workflow step changes.
        self.mood_note: str | None = None
        # Serialises instruction updates so a mood note and a step change never overwrite each other.
        self.instructions_lock = asyncio.Lock()
        # Whether the agent has said anything yet. Set as soon as its words or audio are produced, ahead of
        # any tool call in the same reply (llm_node / realtime_audio_output_node).
        self.has_spoken = False
        # Live calls turn this on: until the agent has spoken, the workflow can't leave its start step.
        self.opening_guard = False
        path_tools: list = []
        # Kept so a caller-mood note can be swapped in and out without losing the base prompt. With a
        # workflow it is the current step's prompt, updated on every step change (except on Gemini
        # Live, where it stays the starting prompt and later steps arrive as tool results).
        self.base_instructions = builtin_instructions(lead, language_rules)
        self.opening = opening_line(lead)
        snapshot = cfg.snapshot if cfg is not None else None
        if snapshot is not None:
            try:
                persona = snapshot.get("persona_name")
                persona = persona if isinstance(persona, str) and persona.strip() else PERSONA_NAME
                workflow = self._start_workflow(snapshot)
                step = workflow.current if workflow else None
                paths = workflow.paths_from_current() if workflow else []
                self.snapshot, self.persona_name = snapshot, persona
                self.base_instructions = self._snapshot_instructions(step, paths)
                self.opening = opening_line(lead, persona)
                # Every path tool of the graph, registered once: tools never change mid-call (on Gemini
                # Live a tool update reconnects the session). The engine refuses paths not valid here.
                path_tools = [self._path_tool(p) for p in workflow.all_path_tools()] if workflow else []
                self.workflow = workflow
            except Exception:
                # A call must never fail because of console data: run today's built-in agent instead.
                logger.warning("console config unusable, using the built-in prompt", exc_info=True)
                self.snapshot = self.workflow = self.persona_name = None
                self.base_instructions = builtin_instructions(lead, language_rules)
                self.opening = opening_line(lead)
                path_tools = []
        super().__init__(instructions=self.base_instructions, tools=path_tools)
        self.outcome: dict | None = None
        # The last outcome refused at an end step; the same one again overrides the step (ruling P18).
        self.end_step_refused: dict | None = None
        self.caller_identity: str | None = None

    @staticmethod
    def _start_workflow(snapshot: dict) -> WorkflowRun | None:
        workflow = snapshot.get("workflow")
        graph = workflow.get("graph") if isinstance(workflow, dict) else None
        if not isinstance(graph, dict):
            return None
        run = WorkflowRun(graph)
        if run.start() is None:
            logger.warning("workflow has no start step; running the script only")
            return None
        return run

    @staticmethod
    def _path_labels(paths: list[PathTool]) -> list[dict]:
        return [{"name": p.name, "label": p.description} for p in paths]

    def _snapshot_instructions(self, step: Step | None, paths: list[PathTool]) -> str:
        text = build_instructions(
            self.snapshot,
            self.lead,
            self.language_rules,
            asdict(step) if step is not None else None,
            self._path_labels(paths),
            handoff_available=bool(HANDOFF_SIP_URI),
        )
        return f"{text}\n\n{opening_instructions(self.lead, self.persona_name)}"

    def _path_tool(self, tool: PathTool):
        async def take_path(raw_arguments: dict) -> str:
            return await self._take_path(tool.name, raw_arguments)

        return function_tool(take_path, raw_schema=path_tool_schema(tool))

    async def _take_path(self, tool_name: str, raw_arguments) -> str:
        """Move the workflow along one path. Never raises: a bad step must not break the call."""
        try:
            run = self.workflow
            if run is None:
                return "Carry on with the call."
            if self.opening_guard and run.current is not None:
                refusal = start_path_refusal(run.current.type, run.transitions, self.has_spoken, self.opening)
                if refusal is not None:
                    logger.info("path refused before the opening", extra={"tool": tool_name})
                    return refusal
            value = raw_arguments.get("value") if isinstance(raw_arguments, dict) else None
            transition = run.take(tool_name, value if isinstance(value, str) else None)
            if not transition.ok or transition.entered is None:
                if transition.capped:
                    logger.warning("workflow loop limit reached", extra={"tool": tool_name})
                    if self.outcome is None:
                        self.outcome = capped_outcome()
                return transition.message
            step = transition.entered
            logger.info("workflow step", extra={"step": step.name, "path": run.path})
            self.emit("step_entered", {"step_id": step.id, "step_name": step.name})
            if transition.captured is not None:
                field, captured = transition.captured
                self.emit("field_captured", {"field": field, "value": captured})
            paths = run.paths_from_current()
            if not step_updates_instructions(self.pipeline):
                block = step_block(
                    asdict(step), self.lead, self._path_labels(paths), bool(HANDOFF_SIP_URI),
                    custom_hints(self.snapshot),
                )
                # A tool result is read as text to act on: say plainly that it is instructions, not a script.
                return f"Now at step {step.name}. Instructions for you; say only the words meant for the driver.\n{block}"
            async with self.instructions_lock:
                self.base_instructions = self._snapshot_instructions(step, paths)
                note = f"\n\n{self.mood_note}" if self.mood_note else ""
                await self.update_instructions(self.base_instructions + note)
            return f"Now at step {step.name}."
        except Exception:
            logger.exception("workflow step change failed", extra={"tool": tool_name})
            return "Carry on with the call."

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Cascaded pipelines: the reply's text streams through here before any tool call in it is run."""
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            if not self.has_spoken and spoken_text(chunk):
                self.has_spoken = True
            yield chunk

    async def realtime_audio_output_node(self, audio, model_settings):
        """Gemini Live: the reply's audio streams through here; it arrives before a tool call that follows it."""
        async for frame in Agent.default.realtime_audio_output_node(self, audio, model_settings):
            self.has_spoken = True
            yield frame

    def workflow_stopped(self) -> bool:
        """The loop cap stopped the workflow: the end-step outcome rule no longer applies."""
        return self.workflow is not None and self.workflow.stopped

    def current_step(self) -> dict | None:
        run = self.workflow
        return asdict(run.current) if run is not None and run.current is not None else None

    @function_tool
    async def record_outcome(
        self,
        disposition: Disposition,
        reason: str,
        summary: str,
        interest_strength: Literal["confirmed", "conditional", "tentative", "none"] = "none",
        telecaller_followup_agreed: bool = False,
        callback_time: str = "",
        city: str = "",
        licence: str = "",
        experience: str = "",
        uber_id: str = "",
        preferred_plan: str = "",
        main_question: str = "",
        do_not_call: bool = False,
    ) -> str:
        """Record the call's outcome for Carrum's telecalling team. Call it before your closing line, and
        again if the outcome changes. Fill only what the driver actually said; leave the rest empty.

        Args:
            disposition: INTERESTED: genuine interest, incl. approved VDC/WTHINK cases. NI: clearly refuses.
                NE: fails eligibility. CBR: asked to talk later. CDRP: call cut off with no outcome.
                ISUDO: ineligible because of documents. ISUID: Uber ID blocked. HND: not a driver.
                WRGN: wrong number. OWNVA: has own vehicle. ABULR: abusive. LANGUAGE_BARRIER: no shared
                supported language. NOT_CONNECTED: no real conversation, e.g. voicemail. UNRESOLVED: no clear outcome.
            reason: Why this disposition, from what the driver said. For NE/ISUDO/ISUID, the exact rule they fail.
            summary: Two or three sentences for the telecaller: what you learned, what they asked, what was agreed.
            interest_strength: For INTERESTED: confirmed, conditional or tentative. Otherwise none.
            telecaller_followup_agreed: True only if the driver agreed to talk to the telecalling team.
            callback_time: When the driver asked to be called back, in their words.
            city: City and preferred working location.
            licence: Driving licence status, e.g. "valid 4-wheeler, own name" or "none".
            experience: Uber, Ola, other commercial driving, or new driver.
            uber_id: active, inactive, not created or blocked.
            preferred_plan: Uber Go rental, Uber Black salary, Double Driver, or undecided.
            main_question: The driver's main question or objection.
            do_not_call: True if the driver asked not to be called again.
        """
        refusal, overridden = None, False
        try:
            if not self.workflow_stopped():
                refusal, overridden, self.end_step_refused = end_step_check(
                    self.current_step(), disposition, self.end_step_refused
                )
        except Exception:
            logger.exception("end-step check failed")
            refusal, overridden = None, False
        if refusal is not None:
            logger.info("outcome refused at end step", extra={"disposition": disposition})
            return refusal
        self.outcome = {
            "disposition": disposition,
            "reason": reason,
            "summary": summary,
            "interest_strength": interest_strength,
            "telecaller_followup_agreed": telecaller_followup_agreed,
            "callback_time": callback_time,
            "city": city,
            "licence": licence,
            "experience": experience,
            "uber_id": uber_id,
            "preferred_plan": preferred_plan,
            "main_question": main_question,
            "do_not_call": do_not_call,
        }
        if overridden:
            self.outcome["end_step_outcome_overridden"] = True
            logger.info("end step outcome overridden", extra={"disposition": disposition})
        logger.info("outcome recorded", extra={"disposition": disposition})
        return "Recorded. Now say your closing line."

    @function_tool
    async def end_call(self, ctx: RunContext) -> str | None:
        """Hang up the call. Use only after record_outcome and your closing line."""
        if self.outcome is None:
            return "Call record_outcome first, then end the call."
        try:
            refusal = (None if self.workflow_stopped() or self.outcome.get("end_step_outcome_overridden")
                       else end_step_refusal(self.current_step(), self.outcome.get("disposition")))
        except Exception:
            logger.exception("end-step check failed")
            refusal = None
        if refusal is not None:
            return refusal
        await ctx.wait_for_playout()
        await get_job_context().delete_room()


    @function_tool
    async def transfer_to_telecaller(self, ctx: RunContext) -> str:
        """Connect the driver to a person on Carrum's telecalling team right now. Use only when the
        driver agreed to talk to a person now. Call record_outcome first. If this returns that transfer
        isn't available, offer a callback instead."""
        if not HANDOFF_SIP_URI:
            return "Live transfer isn't available. Offer a callback from the telecalling team instead."
        if self.outcome is None:
            return "Call record_outcome first."
        await ctx.wait_for_playout()
        job = get_job_context()
        try:
            await job.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job.room.name,
                    participant_identity=self.caller_identity or "",
                    transfer_to=HANDOFF_SIP_URI,
                    play_dialtone=True,
                )
            )
        except Exception:
            logger.exception("transfer to telecaller failed")
            return "Transfer failed. Apologise briefly and offer a callback from the telecalling team."
        logger.info("transferred to telecaller")
        return "Transferred."


class SarvamPhoneAgent(PhoneAgent):
    def __init__(self, lead: dict, cfg: Config | None = None, pipeline: str | None = None) -> None:
        super().__init__(lead, language_rules=SARVAM_LANGUAGE_RULES, cfg=cfg, pipeline=pipeline)

    @function_tool
    async def switch_language(self, ctx: RunContext, language_code: str) -> str:
        """Switch the spoken reply language to match the caller.

        Args:
            language_code: One of hi-IN, en-IN, bn-IN, gu-IN, kn-IN, ml-IN, mr-IN, od-IN, pa-IN, ta-IN, te-IN.
        """
        from livekit.plugins import elevenlabs, sarvam

        if language_code not in LANGUAGES:
            return f"Unsupported language. Use one of: {', '.join(LANGUAGES)}"
        tts = ctx.session.tts
        if isinstance(tts, sarvam.TTS):
            tts.update_options(target_language_code=language_code)
        elif isinstance(tts, elevenlabs.TTS):
            # ElevenLabs takes ISO 639-1 codes: "hi", not "hi-IN".
            tts.update_options(language=language_code.split("-")[0])
        logger.info("switched language", extra={"language": language_code})
        return f"Now speaking {LANGUAGES[language_code]}."


def gemini_live_session(
    lead: dict, cfg: Config = BUILTIN_CONFIG, mood_on: bool = MOOD_ENABLED, voice: str | None = None
) -> tuple[AgentSession, PhoneAgent]:
    from livekit.plugins import google

    # Tone follows the caller's emotion. Uses Gemini's v1alpha API; off by default.
    affective = os.getenv("GEMINI_AFFECTIVE_DIALOG", "false").lower() == "true"
    llm = google.realtime.RealtimeModel(
        model=os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live"),
        voice=voice or os.getenv("GEMINI_VOICE", "Kore"),
        # A bit of variety keeps replies from sounding scripted.
        temperature=0.8,
        enable_affective_dialog=affective,
        # The Live API only exists on v1beta/v1alpha. google-genai 3.x defaults to v1, where the
        # Live websocket returns 404 and every call ends before the greeting.
        api_version="v1alpha" if affective else "v1beta",
    )
    # Gemini does its own turn detection; no local VAD/STT/TTS needed.
    rules = GEMINI_LANGUAGE_RULES
    if mood_on:
        # Gemini hears the caller's tone itself; it gets the guide once instead of mid-call notes.
        rules += "\n\n" + tone_guide(handoff_available=bool(HANDOFF_SIP_URI))
    return AgentSession(llm=llm), PhoneAgent(lead, language_rules=rules, cfg=cfg, pipeline="gemini-live")


def sarvam_tts(voice: str | None = None):
    from livekit.plugins import sarvam

    return sarvam.TTS(
        target_language_code=DEFAULT_LANGUAGE,
        model="bulbul:v3",
        speaker=voice or os.getenv("TTS_SPEAKER", "priya"),
    )


def elevenlabs_tts(voice: str | None = None):
    from livekit.plugins import elevenlabs

    return elevenlabs.TTS(
        # Default: Sarah, a premade voice (free plans can't use library voices over the API).
        voice_id=voice or os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"),
        # Flash is the lowest-latency model and speaks Hindi; eleven_multilingual_v2 sounds richer but lags.
        model=os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        language=DEFAULT_LANGUAGE.split("-")[0],
    )


def cascaded_session(
    proc: JobProcess, lead: dict, tts, cfg: Config = BUILTIN_CONFIG
) -> tuple[AgentSession, PhoneAgent]:
    from livekit.plugins import openai, sarvam
    from livekit.plugins.turn_detector.multilingual import MultilingualModel

    session = AgentSession(
        vad=proc.userdata["vad"],
        # "unknown" lets Sarvam auto-detect the caller's language.
        stt=sarvam.STT(language="unknown", model="saaras:v4"),
        llm=openai.LLM(model=os.getenv("LLM_MODEL", "gpt-4.1-mini")),
        tts=tts,
        turn_handling={"turn_detection": MultilingualModel()},
    )
    return session, SarvamPhoneAgent(lead, cfg)


def prewarm(proc: JobProcess) -> None:
    # Loaded once per worker process, shared by every call it handles.
    if PIPELINE in ("sarvam", "elevenlabs"):
        proc.userdata["vad"] = silero.VAD.load()


def ambient_sound() -> AudioConfig | None:
    if AMBIENCE == "none":
        return None
    if AMBIENCE in AMBIENCE_CLIPS:
        source, volume = AMBIENCE_CLIPS[AMBIENCE]
    else:
        path = Path(AMBIENCE) if Path(AMBIENCE).is_absolute() else Path(__file__).parent / AMBIENCE
        if not path.is_file():
            logger.warning("BACKGROUND_AMBIENCE file not found, no background sound", extra={"path": str(path)})
            return None
        source, volume = str(path), 1.0
    volume = float(os.getenv("BACKGROUND_VOLUME") or volume)
    # Fade in so the noise doesn't start abruptly under the greeting.
    return AudioConfig(source, volume=volume, fade_in=1.5)


def driver_spoke(session: AgentSession) -> bool:
    return any(getattr(item, "role", None) == "user" for item in session.history.items)


async def watch_dead_air(session: AgentSession, agent: PhoneAgent, watcher: DeadAirWatcher) -> None:
    """Act on caller silence until the call ends or the agent hangs up."""
    while True:
        await asyncio.sleep(0.5)
        action = watcher.poll(time.monotonic())
        if action is None:
            continue
        logger.info("dead air", extra={"action": action})
        if action != "hang_up":
            session.generate_reply(instructions=DEAD_AIR_PROMPTS[action])
            continue
        if agent.outcome is None:
            agent.outcome = {
                "disposition": "UNRESOLVED" if driver_spoke(session) else "NOT_CONNECTED",
                "reason": f"caller silent for {watcher.config.hang_up_s:g} s",
            }
        await session.generate_reply(instructions=DEAD_AIR_PROMPTS["hang_up"])
        await get_job_context().delete_room()
        return


server = AgentServer(
    setup_fnc=prewarm,
    num_idle_processes=int(os.getenv("NUM_IDLE_PROCESSES", "3")),
    load_threshold=float(os.getenv("LOAD_THRESHOLD", "0.75")),
)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name, "pipeline": PIPELINE}
    lead = lead_record(ctx.job.metadata)
    # Set for a console voice test (browser over WebRTC): the call runs that agent's draft.
    web_test_agent = web_test_agent_id(dispatch_metadata(ctx.job.metadata))
    if PIPELINE not in ("sarvam", "elevenlabs", "gemini-live"):
        raise ValueError(f"unknown AGENT_PIPELINE {PIPELINE!r}")

    # Live call events for the console, whenever it is configured (any config source).
    sink = EventSink(
        events_url(),
        ctx.room.name,
        os.environ.get("LIVEKIT_API_KEY", ""),
        os.environ.get("LIVEKIT_API_SECRET", ""),
    )
    # Set once the caller has joined; the shutdown callback below may run before that.
    session: AgentSession | None = None
    agent: PhoneAgent | None = None
    cfg = BUILTIN_CONFIG
    mood_on = False
    watcher: DeadAirWatcher | None = None
    latency = LatencyStats()
    tracker = MoodTracker()
    behavior = BehaviorTracker()
    call_start_wall = time.time()

    def final_outcome() -> dict:
        # Hung up before the agent recorded anything: dropped if the driver spoke, else never connected.
        if agent is not None and agent.outcome:
            return agent.outcome
        spoke = session is not None and driver_spoke(session)
        return {
            "disposition": "CDRP" if spoke else "NOT_CONNECTED",
            "reason": "call ended before an outcome was recorded",
        }

    def step_path() -> list[str] | None:
        return list(agent.workflow.path) if agent is not None and agent.workflow is not None else None

    async def send_call_report() -> None:
        # Shutdown callbacks are awaited, so the report goes out before the job process exits.
        # Registered before the caller joins, so it copes with no config, session or agent yet.
        # Flush the last events first (bounded), then the report.
        try:
            await sink.close(timeout_s=1.0)
        except Exception:
            logger.warning("event sink close failed", exc_info=True)
        if not DASHBOARD_REPORT_URL:
            return
        turns = None
        if MOOD_EVAL_CAPTURE:
            turns = [
                {
                    "role": item.role,
                    "text": item.text_content,
                    "at_s": round(max(0.0, getattr(item, "created_at", call_start_wall) - call_start_wall), 2),
                }
                for item in (session.history.items if session is not None else [])
                if getattr(item, "role", None) in ("user", "assistant") and getattr(item, "text_content", None)
            ]
        report = build_report(
            room=ctx.room.name,
            outcome=final_outcome(),
            mood=tracker.summary() if mood_on else None,
            timeline=tracker.timeline,
            dead_air=watcher.events if watcher is not None else [],
            latency=latency.summary(),
            behavior=behavior.features() if mood_on else None,
            turns=turns,
            agent_version_id=cfg.version_id,
            step_path=step_path(),
            captured=captured_answers(agent),
        )
        await send_report(
            DASHBOARD_REPORT_URL, report, os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]
        )

    ctx.add_shutdown_callback(send_call_report)

    # The called number picks the published agent; the fetch fits in the greeting gate's listening window.
    caller = await ctx.wait_for_participant(
        kind=[rtc.ParticipantKind.PARTICIPANT_KIND_SIP, rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD]
    )
    phone = caller.attributes.get("sip.phoneNumber")
    called = caller.attributes.get("sip.trunkPhoneNumber", "")
    try:
        if web_test_agent is not None:
            cfg = await load_draft_config(
                web_test_agent,
                ctx.room.name,
                base_url=dashboard_url(),
                api_key=os.environ.get("LIVEKIT_API_KEY", ""),
                api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
            )
        else:
            cfg = await load_config(
                called,
                ctx.room.name,
                base_url=dashboard_url(),
                api_key=os.environ.get("LIVEKIT_API_KEY", ""),
                api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
            )
    except Exception:  # load_config never raises; belt and braces for a live call
        logger.warning("config load failed, using the built-in agent", exc_info=True)
        cfg = BUILTIN_CONFIG
    settings = _settings(cfg.snapshot)
    mood_on = mood_enabled(settings)

    chosen = cfg.snapshot.get("voice_id") if isinstance(cfg.snapshot, dict) else None
    if PIPELINE == "sarvam":
        voice = voices.resolve(PIPELINE, chosen, os.getenv("TTS_SPEAKER", "priya"))
        session, agent = cascaded_session(ctx.proc, lead, sarvam_tts(voice), cfg)
    elif PIPELINE == "elevenlabs":
        voice = voices.resolve(PIPELINE, chosen, os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"))
        session, agent = cascaded_session(ctx.proc, lead, elevenlabs_tts(voice), cfg)
    else:
        voice = voices.resolve(PIPELINE, chosen, os.getenv("GEMINI_VOICE", "Kore"))
        session, agent = gemini_live_session(lead, cfg, mood_on, voice)
    agent.caller_identity = caller.identity
    agent.emit = sink.add
    agent.opening_guard = True
    used, settings = call_settings(cfg, agent)
    if used is not cfg:
        logger.warning("console config unusable, the call runs the built-in agent", extra={"source": cfg.source})
        cfg = used
        mood_on = mood_enabled(settings)
    if agent.workflow is not None and agent.workflow.current is not None:
        sink.add("step_entered", {"step_id": agent.workflow.current.id, "step_name": agent.workflow.current.name})

    watcher = DeadAirWatcher(dead_air_config(settings))
    gate = GreetingGate()
    background_tasks: set[asyncio.Task] = set()
    agent_state = "initializing"
    classifier = make_classifier(PIPELINE) if mood_on else None
    call_start = time.monotonic()
    last_agent_line = ""
    listening_at: float | None = None  # when the agent last started waiting for the caller
    reply_latency: float | None = None  # how long the caller took to start their current reply

    async def classify_turn(agent_line: str, caller_text: str, at_s: float) -> None:
        reading = await classifier.classify(agent_line, caller_text, at_s)
        if reading is not None:
            await handle_reading(reading)

    async def handle_reading(reading: MoodReading) -> None:
        changed = tracker.observe(reading)
        if changed is not None:
            logger.info("mood changed", extra={"mood": changed, "source": reading.source})
            sink.add("mood", {"label": changed, "confidence": reading.confidence})
            if not sends_mood_notes(PIPELINE):
                return
            # Under the lock, so the base is the current workflow step's prompt, never a stale one.
            async with agent.instructions_lock:
                agent.mood_note = mood_message(changed, handoff_available=bool(HANDOFF_SIP_URI))
                await apply_mood(
                    agent, session.tts, changed, agent.base_instructions, handoff_available=bool(HANDOFF_SIP_URI)
                )

    def start_background(coro) -> None:
        task = asyncio.create_task(coro)
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)

    @session.on("metrics_collected")
    def _on_metrics(ev) -> None:
        m = ev.metrics
        if isinstance(m, EOUMetrics):
            latency.add("eou", m.end_of_utterance_delay)
        elif isinstance(m, (LLMMetrics, RealtimeModelMetrics)):
            latency.add("llm_ttft", m.ttft)
        elif isinstance(m, TTSMetrics):
            latency.add("tts_ttfb", m.ttfb)

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        nonlocal agent_state, listening_at
        agent_state = ev.new_state
        if ev.new_state == "listening":
            listening_at = time.monotonic()
            watcher.agent_listening(listening_at)
        elif ev.new_state in ("thinking", "speaking"):
            watcher.agent_busy(time.monotonic())
        if ev.new_state == "speaking":
            agent.has_spoken = True

    @session.on("speech_created")
    def _on_speech(ev) -> None:
        if mood_on:
            ev.speech_handle.add_done_callback(
                lambda handle: behavior.agent_turn_ended(time.monotonic(), handle.interrupted)
            )

    @session.on("user_input_transcribed")
    def _on_user_transcribed(ev) -> None:
        # Partial transcripts arrive while the caller is still talking. Gemini Live reports no
        # "caller started speaking" event while the agent is idle, so this is how we know.
        now = time.monotonic()
        gate.caller_spoke(now, ev.transcript)
        watcher.user_activity(now, ev.transcript)
        if agent_state == "listening":
            watcher.agent_listening(now)

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        nonlocal listening_at, reply_latency
        if ev.new_state == "speaking":
            now = time.monotonic()
            if listening_at is not None and reply_latency is None:
                reply_latency = now - listening_at
            listening_at = None
            gate.caller_spoke(now, None)
            watcher.user_activity(now)
        elif ev.new_state == "listening" and agent_state == "listening":
            # The caller stopped and the agent isn't replying: silence starts counting again.
            watcher.agent_listening(time.monotonic())

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        nonlocal last_agent_line, listening_at, reply_latency
        text = getattr(ev.item, "text_content", None)
        if text:
            logger.info("transcript", extra={"role": ev.item.role, "text": text})
            if ev.item.role in ("user", "assistant"):
                speaker = "caller" if ev.item.role == "user" else "agent"
                sink.add("turn", {"speaker": speaker, "text": text, "expressions": []})
            if ev.item.role == "user":
                # Also covers pipelines that don't report the caller's speaking state.
                watcher.user_activity(time.monotonic(), text)
                if agent_state == "listening":
                    watcher.agent_listening(time.monotonic())
                at_s = time.monotonic() - call_start
                if classifier is not None:
                    # Runs alongside the call; the result only shapes the next reply.
                    start_background(classify_turn(last_agent_line, text, at_s))
                if mood_on:
                    # No speaking-state event (some pipelines): measure up to the transcript instead.
                    if reply_latency is None and listening_at is not None:
                        reply_latency = time.monotonic() - listening_at
                    latency_s = (reply_latency or 0.0) if reply_latency_reliable(PIPELINE) else 0.0
                    behavior.user_turn(time.monotonic(), text, latency_s)
                    reply_latency = None
                    listening_at = None
                    if signal := behavior.poll(at_s):
                        start_background(handle_reading(signal))
            elif ev.item.role == "assistant":
                last_agent_line = text

    @session.on("close")
    def _on_close(_ev) -> None:
        for task in list(background_tasks):
            task.cancel()
        outcome = final_outcome()
        logger.info(
            "call ended",
            extra={
                "phone": phone,
                "lead": lead,
                "outcome": outcome,
                "dead_air": watcher.events,
                "latency": latency.summary(),
                "mood": tracker.summary() if mood_on else None,
                "behavior": behavior.features() if mood_on else None,
                "usage": str(session.usage),
                "config": cfg.source,
                "version_id": cfg.version_id,
                "step_path": step_path(),
            },
        )


    await session.start(agent=agent, room=ctx.room)

    logger.info(
        "call started",
        extra={
            "caller": phone,
            "called": called,
            "lead_id": lead.get("lead_id"),
            "web_test_agent": web_test_agent,
            "config": cfg.source,
            "version_id": cfg.version_id,
        },
    )

    # Listen first: callers often say "hello" as they pick up. Greet once they pause.
    gate.start(time.monotonic())
    while not gate.ready(time.monotonic()):
        await asyncio.sleep(0.1)
    agent_spoke = any(getattr(item, "role", None) == "assistant" for item in session.history.items)
    if agent_state in ("thinking", "speaking") or agent_spoke:
        # The model already answered the caller's hello with the opening line (it's in its instructions).
        logger.info("greeting started by the model", extra={"caller_said": gate.caller_said})
    else:
        session.generate_reply(instructions=greeting_instructions(agent.opening, gate.caller_said))

    if dead_air_on(cfg.snapshot):
        start_background(watch_dead_air(session, agent, watcher))
    else:
        logger.info("dead air off for this call", extra={"config": cfg.source})

    # After the greeting is queued, so ambience setup never delays it.
    if ambient := ambient_sound():
        background = BackgroundAudioPlayer(
            ambient_sound=ambient,
            # Typing while the agent "looks something up" (tool calls).
            thinking_sound=[
                AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.5),
                AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.45),
            ],
        )
        await background.start(room=ctx.room, agent_session=session)
