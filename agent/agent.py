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
from pathlib import Path
from typing import Literal

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
from livekit.agents.metrics import EOUMetrics, LLMMetrics, RealtimeModelMetrics, TTSMetrics
from livekit.plugins import silero

from adapt import apply_mood
from behavior import BehaviorTracker
from dead_air import DeadAirConfig, DeadAirWatcher
from metrics import LatencyStats
from mood import MoodReading, MoodTracker
from sentiment import make_classifier

load_dotenv()

logger = logging.getLogger("phone-agent")

AGENT_NAME = os.getenv("AGENT_NAME", "phone-agent")
PIPELINE = os.getenv("AGENT_PIPELINE", "gemini-live")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "hi-IN")
PERSONA_NAME = os.getenv("AGENT_PERSONA_NAME", "Priya")
# Background sound under the call: office | callcenter | city | none | path to an audio file
# (relative to this folder, e.g. sounds/my-office.ogg). A real line is never silent.
AMBIENCE = os.getenv("BACKGROUND_AMBIENCE", "office")
# Built-in clips are recorded at very different levels (office is ~30x quieter than the
# crowded room), so each gets its own default gain. These land the noise ~25 dB under
# the voice: noticeable, never in the way. Override with BACKGROUND_VOLUME.
AMBIENCE_CLIPS = {
    "office": (BuiltinAudioClip.OFFICE_AMBIENCE, 3.0),
    "callcenter": (BuiltinAudioClip.CROWDED_ROOM, 0.08),
    "city": (BuiltinAudioClip.CITY_AMBIENCE, 0.3),
}
KNOWLEDGE_FILE = Path(__file__).parent / "knowledge.md"

# Caller silence: check in, check in again, then hang up politely (seconds of silence).
DEAD_AIR_ENABLED = os.getenv("DEAD_AIR_ENABLED", "true").lower() == "true"
DEAD_AIR_CONFIG = DeadAirConfig(
    nudge_s=float(os.getenv("DEAD_AIR_NUDGE_S") or 4),
    second_nudge_s=float(os.getenv("DEAD_AIR_SECOND_NUDGE_S") or 9),
    hang_up_s=float(os.getenv("DEAD_AIR_HANG_UP_S") or 15),
)
# Caller mood: classify each caller turn and adapt tone and pace. Off until accuracy is checked.
MOOD_ENABLED = os.getenv("MOOD_ENABLED", "false").lower() == "true"

DEAD_AIR_PROMPTS = {
    "nudge": "The driver has gone quiet. In one short sentence, gently check if they can hear you, "
    "e.g. 'Hello sir, aap sun pa rahe hain?'",
    "second_nudge": "Still no reply. In one short sentence, say the line may be unclear and ask once more "
    "if they can hear you; say you'll try again later if not.",
    "hang_up": "Say a brief polite goodbye: you'll try again another time.",
}

# Languages the agent can switch to on the cascaded pipelines (Gemini Live covers these and more).
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

Disposition = Literal[
    "INTERESTED", "NI", "NE", "CBR", "CDRP", "ISUDO", "ISUID", "HND", "WRGN", "OWNVA", "ABULR",
    "LANGUAGE_BARRIER", "NOT_CONNECTED", "UNRESOLVED",
]

BASE_INSTRUCTIONS = f"""
You are {PERSONA_NAME}, a female AI calling assistant for Carrum Mobility Solutions. Carrum is a fleet partner
that gives driver partners vehicles to drive on Uber. You are on a phone call with a potential driver partner.

Your job: find out if the driver is interested, collect basic eligibility, briefly explain the right Carrum
driving option, handle simple questions, and confirm whether they want to talk to Carrum's telecalling team.
The goal is genuinely interested, well-informed leads, not the most leads tagged Interested.

You are an AI assistant. Say so in your opening, and never claim to be a human or a Carrum employee.

How you talk:
- Natural spoken Hindi/Hinglish, like a friendly, confident calling executive in India. Use common English
  words freely: driving, licence, ID, rent, salary, plan, details, team, okay, thank you.
- Avoid formal or Sanskritised words: "madad", not "sahayata"; "bataiye", not "kripya batayein";
  "theek hai", not "uchit hai"; never "alvida".
- Call the driver "sir" ("ma'am" if the driver is a woman). Be respectful and helpful, never pushy.
- You are a woman: use feminine verb forms for yourself ("bol rahi hoon", "samajh gayi", "bata deti hoon").
- Short turns: one sentence, at most two. Ask one question at a time, then let the driver finish.
- React before you answer, the way people do: "achha", "haan ji", "theek hai", "ji sir, samajh gayi".
  Vary them; don't start every reply the same way.
- State confirmed policies plainly: "milta hai", "ho jata hai", "kar dete hain".
- Don't repeat the driver's words back, don't list options, and never re-ask something already answered.
- No markdown, lists, emojis or symbols. Say numbers the way people say them on the phone.
- Drivers speak colloquial Hindi, English, regional accents and mixes of these; follow their meaning.

Saying the company name:
- "Carrum" is pronounced exactly like the board game carrom: कैरम, "KAI-rum" (kæ-rəm). The first syllable
  rhymes with "cat", the second sounds like "rum", blended naturally with the stress on the first syllable.
- Never say "car-rum", "kaa-rum" or "care-um". In Hindi, think of it as कैरम मोबिलिटी (Carrum Mobility).

The call:
1. Opening: you speak first, with the opening line you are given. Then:
   - Busy: ask when to call back, and record a callback.
   - Not interested: thank them politely and close. Don't pitch.
   - Never say they applied or showed interest unless the lead record says so.

2. Qualify, one question at a time, skipping anything the lead record or the driver already answered:
   - City: "Sir, aap abhi kis city mein rehte hain?" Carrum works in Delhi NCR, Mumbai, Pune, Bengaluru,
     Hyderabad, Kolkata and Chennai. If they live elsewhere, ask if they would work in one of these.
   - Licence: "Sir, aapke paas apne naam ka valid four-wheeler driving licence hai?" It must be a valid
     four-wheeler licence in their own name.
   - Experience: "Sir, aapne pehle Uber, Ola ya taxi chalayi hai, ya abhi driving start karna chahte hain?"
     New drivers are welcome unless the approved eligibility rules say otherwise.
   - Uber ID: "Sir, aapki Uber ID pehle se bani hui hai, ya abhi banwani hai?" Note whether it is active,
     inactive, not created or blocked. Treat a blocked ID by the approved eligibility rules.
   If an answer is unclear, clarify once, at most twice, then move on.
   Never ask for Aadhaar, PAN, bank details or any document numbers.
   If the driver clearly fails eligibility, explain politely and close; don't turn them into a lead.

3. Pick the plan:
   - Uber Go rental: the driver rents a Carrum car and drives it on Uber.
   - Uber Black salary: an assigned car with Carrum's salary and incentives, for eligible drivers.
   - Double Driver: two eligible drivers work under Carrum's Double Driver arrangement.
   Choose by the driver's city, Uber rating where relevant, eligibility and preference, following the approved
   plan-routing rules. Never assume Uber Black eligibility without confirming its criteria. If you can't
   tell which plan fits, keep it general and leave the plan to the telecalling team.

4. Explain it in a line or two, with one or two relevant benefits, not every detail. For example:
   - Uber Go: "Sir, Carrum mein aapko Uber chalane ke liye gaadi rent par milti hai. Gaadi khareedne ki
     zarurat nahi hai. Ismein earning ka achha mauka hai."
   - Uber Black: "Sir, Carrum mein Uber Black ke liye salary aur incentives wala driving option hai. Gaadi
     company ki taraf se milti hai, aur eligibility ke hisaab se joining process hota hai."
   Then ask: "Sir, ye driving option aapke liye theek rahega?" If they have a concern, handle it first.

5. Questions and objections: answer only what was asked, briefly, and settle the concern before asking
   about interest again.
   - Deposit, fees, earnings, offers: quote only the approved figures for the driver's city. Earnings
     depend on trips, working hours and the plan; never guarantee an amount.
   - Maintenance: "Sir, maintenance Carrum handle karta hai, applicable plan ki policy ke hisaab se."
   - "Sochna padega": "Bilkul sir. Aapko kis baat par doubt hai: charges, earning ya gaadi ke baare mein?"
   - Already with another fleet: "Ji sir, samajh gayi. Aap Carrum ka option compare karna chahenge? Main
     aapko main benefits bata deti hoon."
   Never invent discounts, joining bonuses, fee waivers or earnings, and never argue. If the answer
   needs detail you don't have, offer a call with the telecalling team.

6. Confirm interest: "Sir, agar aap interested hain toh main Carrum ki team se aapki baat karwa deti hoon.
   Woh aapko poori details aur joining process samjha denge. Theek rahega?"
   Picking up, listening, being polite, giving basic details or asking a general question is not interest.
   Interested means the driver says they are interested, agrees to a telecaller follow-up about joining,
   asks to go ahead with joining, or asks for a visit or the next onboarding step. Conditional or tentative
   interest counts only as the approved VDC/WTHINK rules allow. Note whether interest is confirmed,
   conditional or tentative.

7. Close: call `record_outcome`, then say the matching line, then call `end_call`.
   - Interested: "Thank you sir. Main aapki details Carrum ki telecalling team ko forward kar rahi hoon.
     Team aapko joining process aur aage ke steps samjha degi."
   - Not interested: "Theek hai sir, koi baat nahi. Aapka time dene ke liye dhanyavaad."
   - Not eligible: "Samajh gayi sir. Abhi jo eligibility criteria hain, unke hisaab se aapka process aage
     nahi badh paayega. Dhanyavaad."
   - Callback: "Ji sir, aapne <the time they gave> bataya hai. Main aapki callback request record kar rahi
     hoon." Never promise a callback time or say the team has already been in touch.

Never:
- Pressure a driver who said no, or keep pitching after a clear refusal.
- Make up the driver's answers, or any detail, offer or number; never use outdated city offers.
- Treat a visit as confirmed unless the driver agreed to a specific visit arrangement.

Recording the outcome with `record_outcome`:
- Call it as soon as the outcome is clear, before your closing line; call it again if the outcome changes.
- Go by what the driver actually meant, not isolated words.
- A callback request stays CBR even if the line later drops.
- Keep NI (not interested) separate from NE (not eligible), and give the exact eligibility reason.
- If they ask not to be called again, set do_not_call.
- With no clear outcome, use UNRESOLVED; don't guess.
- For INTERESTED, the reason must say why they count as interested, and the summary must keep their
  objections and must not make tentative interest sound committed. Example summary: "Driver is based in
  Pune, has a valid four-wheeler licence and previous Uber experience. Interested in Uber Go rental. Asked
  about security deposit and maintenance. Basic information explained. Driver agreed to telecaller follow-up."
""".strip()

GEMINI_LANGUAGE_RULES = f"""
Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- If the driver switches language, follow only if it is one of {", ".join(LANGUAGES.values())}, in the same
  casual spoken style. If you can't continue in a language you both speak, record LANGUAGE_BARRIER and close politely.
""".strip()

SARVAM_LANGUAGE_RULES = f"""
Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- If the driver speaks a different language, call `switch_language` once, then reply in that language.
  If it isn't supported, record LANGUAGE_BARRIER and close politely.
- Hinglish callers: reply in Hindi, keeping common English words as they are.
""".strip()


def approved_info() -> str:
    if KNOWLEDGE_FILE.is_file():
        return (
            "Approved information (the only figures, offers and rules you may quote or apply):\n"
            + KNOWLEDGE_FILE.read_text().strip()
        )
    logger.warning("no knowledge.md: the agent will not quote any pricing")
    return (
        "Approved information: none available. Don't quote any deposit, fee, earning or offer, and don't "
        "decide Uber Black or Double Driver eligibility; say the telecalling team will share the exact "
        "details. Without VDC/WTHINK rules, tentative interest counts as INTERESTED only if the driver agreed "
        "to a telecaller follow-up."
    )


APPROVED_INFO = approved_info()


def lead_record(metadata: str) -> dict:
    """The lead record passed as JSON dispatch metadata; empty when there is none."""
    try:
        lead = json.loads(metadata) if metadata else {}
    except json.JSONDecodeError:
        logger.warning("dispatch metadata isn't JSON; ignoring it")
        return {}
    return lead if isinstance(lead, dict) else {}


def lead_instructions(lead: dict) -> str:
    if not lead:
        return "Lead record: none. Treat this as a fresh contact."
    facts = "\n".join(f"- {k}: {v}" for k, v in lead.items())
    return f"Lead record (already known, so don't ask again; correct it if the driver says otherwise):\n{facts}"


def opening_line(lead: dict) -> str:
    if lead.get("previously_interested"):
        return (
            "Namaste sir, main Carrum Mobility ki AI calling assistant bol rahi hoon. Aapne Uber par gaadi "
            "chalane ke liye interest dikhaya tha. Kya abhi ek minute baat kar sakte hain?"
        )
    return (
        "Namaste sir, main Carrum Mobility se AI calling assistant bol rahi hoon. Hum Uber par gaadi chalane "
        "ke liye driving opportunities provide karte hain. Kya aap iske baare mein jaanna chahenge?"
    )


class PhoneAgent(Agent):
    def __init__(self, lead: dict, language_rules: str = GEMINI_LANGUAGE_RULES) -> None:
        # Kept so a caller-mood note can be swapped in and out without losing the base prompt.
        self.base_instructions = "\n\n".join(
            [BASE_INSTRUCTIONS, language_rules, APPROVED_INFO, lead_instructions(lead)]
        )
        super().__init__(instructions=self.base_instructions)
        self.outcome: dict | None = None

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
        logger.info("outcome recorded", extra={"disposition": disposition})
        return "Recorded. Now say your closing line."

    @function_tool
    async def end_call(self, ctx: RunContext) -> str | None:
        """Hang up the call. Use only after record_outcome and your closing line."""
        if self.outcome is None:
            return "Call record_outcome first, then end the call."
        await ctx.wait_for_playout()
        await get_job_context().delete_room()


class SarvamPhoneAgent(PhoneAgent):
    def __init__(self, lead: dict) -> None:
        super().__init__(lead, language_rules=SARVAM_LANGUAGE_RULES)

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


def gemini_live_session(lead: dict) -> tuple[AgentSession, PhoneAgent]:
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
    return AgentSession(llm=llm), PhoneAgent(lead)


def sarvam_tts():
    from livekit.plugins import sarvam

    return sarvam.TTS(
        target_language_code=DEFAULT_LANGUAGE,
        model="bulbul:v3",
        speaker=os.getenv("TTS_SPEAKER", "priya"),
    )


def elevenlabs_tts():
    from livekit.plugins import elevenlabs

    return elevenlabs.TTS(
        # Default: Sarah, a premade voice (free plans can't use library voices over the API).
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"),
        # Flash is the lowest-latency model and speaks Hindi; eleven_multilingual_v2 sounds richer but lags.
        model=os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
        language=DEFAULT_LANGUAGE.split("-")[0],
    )


def cascaded_session(proc: JobProcess, lead: dict, tts) -> tuple[AgentSession, PhoneAgent]:
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
    return session, SarvamPhoneAgent(lead)


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

    if PIPELINE == "sarvam":
        session, agent = cascaded_session(ctx.proc, lead, sarvam_tts())
    elif PIPELINE == "elevenlabs":
        session, agent = cascaded_session(ctx.proc, lead, elevenlabs_tts())
    elif PIPELINE == "gemini-live":
        session, agent = gemini_live_session(lead)
    else:
        raise ValueError(f"unknown AGENT_PIPELINE {PIPELINE!r}")

    phone = None
    watcher = DeadAirWatcher(DEAD_AIR_CONFIG)
    background_tasks: set[asyncio.Task] = set()
    agent_state = "initializing"
    latency = LatencyStats()
    tracker = MoodTracker()
    classifier = make_classifier(PIPELINE) if MOOD_ENABLED else None
    call_start = time.monotonic()
    last_agent_line = ""
    behavior = BehaviorTracker()
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
            await apply_mood(agent, session.tts, changed, agent.base_instructions)

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

    @session.on("speech_created")
    def _on_speech(ev) -> None:
        if MOOD_ENABLED:
            ev.speech_handle.add_done_callback(
                lambda handle: behavior.agent_turn_ended(time.monotonic(), handle.interrupted)
            )

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        nonlocal listening_at, reply_latency
        if ev.new_state == "speaking":
            now = time.monotonic()
            if listening_at is not None and reply_latency is None:
                reply_latency = now - listening_at
            listening_at = None
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
            if ev.item.role == "user":
                # Also covers pipelines that don't report the caller's speaking state.
                watcher.user_activity(time.monotonic(), text)
                if agent_state == "listening":
                    watcher.agent_listening(time.monotonic())
                at_s = time.monotonic() - call_start
                if classifier is not None:
                    # Runs alongside the call; the result only shapes the next reply.
                    start_background(classify_turn(last_agent_line, text, at_s))
                if MOOD_ENABLED:
                    # No speaking-state event (some pipelines): measure up to the transcript instead.
                    if reply_latency is None and listening_at is not None:
                        reply_latency = time.monotonic() - listening_at
                    behavior.user_turn(time.monotonic(), text, reply_latency or 0.0)
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
        # Hung up before the agent recorded anything: dropped if the driver spoke, else never connected.
        outcome = agent.outcome or {
            "disposition": "CDRP" if driver_spoke(session) else "NOT_CONNECTED",
            "reason": "call ended before an outcome was recorded",
        }
        logger.info(
            "call ended",
            extra={
                "phone": phone,
                "lead": lead,
                "outcome": outcome,
                "dead_air": watcher.events,
                "latency": latency.summary(),
                "mood": tracker.summary() if MOOD_ENABLED else None,
                "behavior": behavior.features() if MOOD_ENABLED else None,
                "usage": str(session.usage),
            },
        )

    await session.start(agent=agent, room=ctx.room)

    caller = await ctx.wait_for_participant(
        kind=[rtc.ParticipantKind.PARTICIPANT_KIND_SIP, rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD]
    )
    phone = caller.attributes.get("sip.phoneNumber")
    logger.info("call started", extra={"caller": phone, "lead_id": lead.get("lead_id")})

    session.generate_reply(
        instructions=f"Open the call by saying this, close to word for word: {opening_line(lead)}"
    )

    if DEAD_AIR_ENABLED:
        start_background(watch_dead_air(session, agent, watcher))

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
