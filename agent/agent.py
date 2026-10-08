"""Inbound phone agent for Indian languages.

Two pipelines, picked with AGENT_PIPELINE:
- gemini-live (default): Gemini Live speech-to-speech. One model listens, thinks
  and speaks; it handles Hindi and regional languages natively. Needs GOOGLE_API_KEY.
- sarvam: Sarvam STT -> OpenAI LLM -> Sarvam TTS. Needs SARVAM_API_KEY + OPENAI_API_KEY.

Run locally:   python -m livekit.agents start agent.py --dev
Run in prod:   python -m livekit.agents start agent.py
"""

import logging
import os

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ConversationItemAddedEvent,
    JobContext,
    JobProcess,
    RunContext,
    function_tool,
    get_job_context,
)
from livekit.plugins import silero

load_dotenv()

logger = logging.getLogger("phone-agent")

AGENT_NAME = os.getenv("AGENT_NAME", "phone-agent")
PIPELINE = os.getenv("AGENT_PIPELINE", "gemini-live")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "hi-IN")

# Languages Sarvam TTS can speak (Gemini Live covers these and more).
LANGUAGES = {
    "hi-IN": "Hindi",
    "en-IN": "English",
    "bn-IN": "Bengali",
    "gu-IN": "Gujarati",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
    "mr-IN": "Marathi",
    "od-IN": "Odia",
    "pa-IN": "Punjabi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
}

BASE_INSTRUCTIONS = """
You are a friendly customer support voice agent for Carrum, speaking on a phone call.

Style:
- This is a phone call. Keep replies to one or two short sentences.
- No markdown, lists, emojis or symbols. Speak numbers the way a person would say them.
- Ask one question at a time.
- If you cannot help, say so politely. When the caller is done, say goodbye and call `end_call`.
""".strip()

GEMINI_LANGUAGE_RULES = f"""
Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- Always reply in the language the caller is speaking (Hindi, English, Tamil, Telugu, Bengali,
  Marathi, Gujarati, Kannada, Malayalam, Punjabi, Odia, ...). Hinglish callers get Hindi,
  keeping common English words as they are.
""".strip()

SARVAM_LANGUAGE_RULES = f"""
Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- If the caller speaks a different language, call `switch_language` once, then reply in that language.
- Hinglish callers: reply in Hindi, keeping common English words as they are.
""".strip()


class PhoneAgent(Agent):
    def __init__(self, language_rules: str = GEMINI_LANGUAGE_RULES) -> None:
        super().__init__(instructions=f"{BASE_INSTRUCTIONS}\n\n{language_rules}")

    @function_tool
    async def end_call(self, ctx: RunContext) -> None:
        """Hang up the call. Use only after saying goodbye."""
        await ctx.wait_for_playout()
        await get_job_context().delete_room()


class SarvamPhoneAgent(PhoneAgent):
    def __init__(self) -> None:
        super().__init__(language_rules=SARVAM_LANGUAGE_RULES)

    @function_tool
    async def switch_language(self, ctx: RunContext, language_code: str) -> str:
        """Switch the spoken reply language to match the caller.

        Args:
            language_code: One of hi-IN, en-IN, bn-IN, gu-IN, kn-IN, ml-IN, mr-IN, od-IN, pa-IN, ta-IN, te-IN.
        """
        from livekit.plugins import sarvam

        if language_code not in LANGUAGES:
            return f"Unsupported language. Use one of: {', '.join(LANGUAGES)}"
        tts = ctx.session.tts
        if isinstance(tts, sarvam.TTS):
            tts.update_options(target_language_code=language_code)
        logger.info("switched language", extra={"language": language_code})
        return f"Now speaking {LANGUAGES[language_code]}."


def gemini_live_session() -> tuple[AgentSession, Agent]:
    from livekit.plugins import google

    llm = google.realtime.RealtimeModel(
        model=os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live"),
        voice=os.getenv("GEMINI_VOICE", "Kore"),
        temperature=0.6,
    )
    # Gemini does its own turn detection; no local VAD/STT/TTS needed.
    return AgentSession(llm=llm), PhoneAgent()


def sarvam_session(proc: JobProcess) -> tuple[AgentSession, Agent]:
    from livekit.plugins import openai, sarvam
    from livekit.plugins.turn_detector.multilingual import MultilingualModel

    session = AgentSession(
        vad=proc.userdata["vad"],
        # "unknown" lets Sarvam auto-detect the caller's language.
        stt=sarvam.STT(language="unknown", model="saaras:v4"),
        llm=openai.LLM(model=os.getenv("LLM_MODEL", "gpt-4.1-mini")),
        tts=sarvam.TTS(
            target_language_code=DEFAULT_LANGUAGE,
            model="bulbul:v3",
            speaker=os.getenv("TTS_SPEAKER", "priya"),
        ),
        turn_handling={"turn_detection": MultilingualModel()},
    )
    return session, SarvamPhoneAgent()


def prewarm(proc: JobProcess) -> None:
    # Loaded once per worker process, shared by every call it handles.
    if PIPELINE == "sarvam":
        proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(
    setup_fnc=prewarm,
    num_idle_processes=int(os.getenv("NUM_IDLE_PROCESSES", "3")),
    load_threshold=float(os.getenv("LOAD_THRESHOLD", "0.75")),
)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name, "pipeline": PIPELINE}

    if PIPELINE == "sarvam":
        session, agent = sarvam_session(ctx.proc)
    elif PIPELINE == "gemini-live":
        session, agent = gemini_live_session()
    else:
        raise ValueError(f"unknown AGENT_PIPELINE {PIPELINE!r}")

    @session.on("conversation_item_added")
    def _on_item(ev: ConversationItemAddedEvent) -> None:
        text = getattr(ev.item, "text_content", None)
        if text:
            logger.info("transcript", extra={"role": ev.item.role, "text": text})

    @session.on("close")
    def _on_close(_ev) -> None:
        logger.info("call ended", extra={"usage": str(session.usage)})

    await session.start(agent=agent, room=ctx.room)

    caller = await ctx.wait_for_participant(
        kind=[rtc.ParticipantKind.PARTICIPANT_KIND_SIP, rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD]
    )
    logger.info("call started", extra={"caller": caller.attributes.get("sip.phoneNumber")})

    await session.generate_reply(
        instructions="Greet the caller warmly, say you are Carrum's assistant, and ask how you can help."
    )
