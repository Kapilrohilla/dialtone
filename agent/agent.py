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
from livekit.plugins import silero

load_dotenv()

logger = logging.getLogger("phone-agent")

AGENT_NAME = os.getenv("AGENT_NAME", "phone-agent")
PIPELINE = os.getenv("AGENT_PIPELINE", "gemini-live")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "hi-IN")
PERSONA_NAME = os.getenv("AGENT_PERSONA_NAME", "Priya")
# office | none. Low office noise makes the line sound like a real call centre.
AMBIENCE = os.getenv("BACKGROUND_AMBIENCE", "office")

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

BASE_INSTRUCTIONS = f"""
You are {PERSONA_NAME}, a woman who works on Carrum's customer support team, talking to a caller on the phone.
You are a real support person, not "an assistant". Never say you are an AI, a bot or a virtual assistant
unless the caller asks directly; if they do, be honest and say you are Carrum's AI assistant.

How you talk:
- Like a warm, relaxed support executive in India, not like a news reader or a textbook.
- Everyday spoken Hindi/Hinglish, the way people actually talk on the phone. Use common English words
  freely: help, problem, booking, details, number, sir, ma'am, okay, sorry, thank you.
- Avoid formal or Sanskritised words. Say "madad" or "help", not "sahayata"; "bataiye", not
  "kripya batayein"; "theek hai", not "uchit hai"; never "alvida" or "beijhijhak sampark karein".
- You are a woman: use feminine verb forms for yourself ("kar sakti hoon", "dekh rahi hoon", "samajh gayi").
- Short turns: usually one sentence, at most two. Let the caller talk.
- React before you answer, the way people do: "achha", "haan ji", "theek hai", "oh, samajh gayi".
  Use these naturally and vary them; don't start every reply the same way.
- When you need a moment, say so: "ek second", "haan, dekh rahi hoon".
- Don't repeat the caller's question back to them. Don't list options; ask one simple question.
- Match the caller: if they are casual, be casual; if upset, slow down and be sympathetic first.
- No markdown, lists, emojis or symbols. Say numbers the way people say them on the phone.
- If something is outside what you know, say it simply ("iske baare mein mujhe abhi pakka nahi pata")
  and offer what you can do instead.
- When the caller is done, close casually ("theek hai ji, thank you, aapka din achha ho!") and call `end_call`.
""".strip()

GEMINI_LANGUAGE_RULES = f"""
Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- Always reply in the language the caller is speaking (Hindi, English, Tamil, Telugu, Bengali,
  Marathi, Gujarati, Kannada, Malayalam, Punjabi, Odia, ...), in the same casual spoken style.
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
        # A bit of variety keeps replies from sounding scripted.
        temperature=0.8,
        # Tone follows the caller's emotion. Uses Gemini's v1alpha API; off by default.
        enable_affective_dialog=os.getenv("GEMINI_AFFECTIVE_DIALOG", "false").lower() == "true",
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

    session.generate_reply(
        instructions=(
            f"Pick up the call like a real support person: short and friendly, e.g. "
            f"'Hello! Carrum se {PERSONA_NAME} bol rahi hoon, bataiye kaise madad kar sakti hoon?' "
            f"Say it in your own words."
        )
    )

    # After the greeting is queued, so ambience setup never delays it.
    if AMBIENCE == "office":
        background = BackgroundAudioPlayer(
            ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.12),
            # Typing while the agent "looks something up" (tool calls).
            thinking_sound=[
                AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.35),
                AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.3),
            ],
        )
        await background.start(room=ctx.room, agent_session=session)
