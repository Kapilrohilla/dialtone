"""Inbound phone agent: Sarvam STT/TTS for Indian languages + an OpenAI LLM.

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
    JobContext,
    JobProcess,
    RunContext,
    function_tool,
    get_job_context,
)
from livekit.plugins import openai, sarvam, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv()

logger = logging.getLogger("phone-agent")

AGENT_NAME = os.getenv("AGENT_NAME", "phone-agent")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "hi-IN")
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "priya")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4.1-mini")

# Languages Sarvam TTS can speak.
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

INSTRUCTIONS = f"""
You are a friendly customer support voice agent for Carrum, speaking on a phone call.

Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- If the caller speaks a different language, call `switch_language` once, then reply in that language.
- Hinglish callers: reply in Hindi, keeping common English words as they are.

Style:
- This is a phone call. Keep replies to one or two short sentences.
- No markdown, lists, emojis or symbols. Speak numbers the way a person would say them.
- Ask one question at a time.
- If you cannot help, say so politely. When the caller is done, say goodbye and call `end_call`.
""".strip()


class PhoneAgent(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)

    @function_tool
    async def switch_language(self, ctx: RunContext, language_code: str) -> str:
        """Switch the spoken reply language to match the caller.

        Args:
            language_code: One of hi-IN, en-IN, bn-IN, gu-IN, kn-IN, ml-IN, mr-IN, od-IN, pa-IN, ta-IN, te-IN.
        """
        if language_code not in LANGUAGES:
            return f"Unsupported language. Use one of: {', '.join(LANGUAGES)}"
        tts = ctx.session.tts
        if isinstance(tts, sarvam.TTS):
            tts.update_options(target_language_code=language_code)
        logger.info("switched language", extra={"language": language_code})
        return f"Now speaking {LANGUAGES[language_code]}."

    @function_tool
    async def end_call(self, ctx: RunContext) -> None:
        """Hang up the call. Use only after saying goodbye."""
        await ctx.wait_for_playout()
        await get_job_context().delete_room()


def prewarm(proc: JobProcess) -> None:
    # Loaded once per worker process, shared by every call it handles.
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(
    setup_fnc=prewarm,
    num_idle_processes=int(os.getenv("NUM_IDLE_PROCESSES", "3")),
    load_threshold=float(os.getenv("LOAD_THRESHOLD", "0.75")),
)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        # "unknown" lets Sarvam auto-detect the caller's language.
        stt=sarvam.STT(language="unknown", model="saaras:v4"),
        llm=openai.LLM(model=LLM_MODEL),
        tts=sarvam.TTS(
            target_language_code=DEFAULT_LANGUAGE,
            model="bulbul:v3",
            speaker=TTS_SPEAKER,
        ),
        turn_handling={"turn_detection": MultilingualModel()},
    )

    @session.on("close")
    def _on_close(_ev) -> None:
        logger.info("call ended", extra={"usage": str(session.usage)})

    await session.start(agent=PhoneAgent(), room=ctx.room)

    caller = await ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
    logger.info("call started", extra={"caller": caller.attributes.get("sip.phoneNumber")})

    await session.generate_reply(
        instructions="Greet the caller warmly, say you are Carrum's assistant, and ask how you can help."
    )
