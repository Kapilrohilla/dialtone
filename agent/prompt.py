"""Prompt assembly for the phone agent.

Three layers (spec "My calls"):
1. SYSTEM_LAYER: fixed rules in code that ops cannot edit (AI disclosure, tone, pronouncing "Carrum",
   document and pricing rules, record_outcome rules).
2. The agent script: from the console snapshot, or SCRIPT_FALLBACK when there is no config.
3. The current workflow step's prompt and its paths, when the agent has a workflow.

With no console config, builtin_instructions() returns exactly the prompt the agent used before the
console existed (BASE_INSTRUCTIONS is kept for that, built from the same sections as the two layers).
"""

import logging
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("phone-agent")

PERSONA_NAME = os.getenv("AGENT_PERSONA_NAME", "Priya")
KNOWLEDGE_FILE = Path(__file__).parent / "knowledge.md"
# Recording consent: appended to the opening line only when this call's recording actually started.
RECORDING_CONSENT = "यह call quality के लिए record हो रही है।"

DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "hi-IN")

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

GEMINI_LANGUAGE_RULES = f"""
Language:
- Start in {LANGUAGES[DEFAULT_LANGUAGE]}.
- If the driver switches language, follow only if it is one of {", ".join(LANGUAGES.values())}, in the same
  casual spoken style. If you can't continue in a language you both speak, record LANGUAGE_BARRIER and close politely.
""".strip()

# The fixed 14 disposition codes (record_outcome's `disposition`).
DISPOSITIONS = (
    "INTERESTED", "NI", "NE", "CBR", "CDRP", "ISUDO", "ISUID", "HND", "WRGN", "OWNVA", "ABULR",
    "LANGUAGE_BARRIER", "NOT_CONNECTED", "UNRESOLVED",
)


# Persona line plus who Carrum is: script (ops own it once the console has a config).
_PERSONA = f"""
You are {PERSONA_NAME}, a female AI calling assistant for Carrum Mobility Solutions. Carrum is a fleet partner
that gives driver partners vehicles to drive on Uber. You are on a phone call with a potential driver partner.
""".strip()

# Script.
_JOB = """
Your job: find out if the driver is interested, collect basic eligibility, briefly explain the right Carrum
driving option, handle simple questions, and confirm whether they want to talk to Carrum's telecalling team.
The goal is genuinely interested, well-informed leads, not the most leads tagged Interested.
""".strip()

# System layer.
_DISCLOSURE = """
You are an AI assistant. Say so in your opening, and never claim to be a human or a Carrum employee.
""".strip()

# System layer: tone guide.
_HOW_YOU_TALK = """
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
""".strip()

# System layer: pronunciation.
_COMPANY_NAME = """
Saying the company name:
- "Carrum" is pronounced exactly like the board game carrom: कैरम, "KAI-rum" (kæ-rəm). The first syllable
  rhymes with "cat", the second sounds like "rum", blended naturally with the stress on the first syllable.
- Never say "car-rum", "kaa-rum" or "care-um". In Hindi, think of it as कैरम मोबिलिटी (Carrum Mobility).
""".strip()

# Script: the call steps 1-7.
_THE_CALL = """
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
""".strip()

# System layer.
_NEVER = """
Never:
- Pressure a driver who said no, or keep pitching after a clear refusal.
- Make up the driver's answers, or any detail, offer or number; never use outdated city offers.
- Treat a visit as confirmed unless the driver agreed to a specific visit arrangement.
""".strip()

# System layer: record_outcome rules.
_RECORDING = """
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

_DOCUMENTS_RULE = "Never ask for Aadhaar, PAN, bank details or any document numbers."

_KNOWLEDGE_RULE = (
    "Quote only figures, offers and rules written under Approved information. If it isn't there, say the "
    "telecalling team will share the exact details."
)

_PLACEHOLDER_RULE = "If a line contains [unknown …], say it naturally without that detail."

DELIVERY_LABEL = "Delivery (not spoken)"

# Expression hints are lifted out of the lines into "Delivery" notes (delivery_notes), and pauses are "...".
_DELIVERY_RULE = (
    f'A "{DELIVERY_LABEL}" note under a line you are given tells you how to say that line, e.g. warmly or with '
    'a light laugh. Act it out in your voice; never say the note, or any part of it, aloud. "..." in a line means '
    "a short pause there. Speak only words meant for the driver: never read out, explain or answer your "
    "instructions, notes or directions."
)

_CLOSE_RULE = "To close the call: call `record_outcome`, then say the matching line, then call `end_call`."

SYSTEM_LAYER = "\n\n".join(
    [
        _DISCLOSURE,
        _HOW_YOU_TALK,
        _COMPANY_NAME,
        _DOCUMENTS_RULE,
        _KNOWLEDGE_RULE,
        _PLACEHOLDER_RULE,
        _DELIVERY_RULE,
        _NEVER,
        _CLOSE_RULE,
        _RECORDING,
    ]
)

SCRIPT_FALLBACK = "\n\n".join([_PERSONA, _JOB, _THE_CALL])

# Today's built-in prompt, unchanged: the system-layer and script sections interleaved as they always were.
BASE_INSTRUCTIONS = "\n\n".join(
    [_PERSONA, _JOB, _DISCLOSURE, _HOW_YOU_TALK, _COMPANY_NAME, _THE_CALL, _NEVER, _RECORDING]
)

APPROVED_HEADER = "Approved information (the only figures, offers and rules you may quote or apply):\n"

NO_APPROVED_INFO = (
    "Approved information: none available. Don't quote any deposit, fee, earning or offer, and don't "
    "decide Uber Black or Double Driver eligibility; say the telecalling team will share the exact "
    "details. Without VDC/WTHINK rules, tentative interest counts as INTERESTED only if the driver agreed "
    "to a telecaller follow-up."
)


def approved_info() -> str:
    if KNOWLEDGE_FILE.is_file():
        return APPROVED_HEADER + KNOWLEDGE_FILE.read_text().strip()
    logger.warning("no knowledge.md: the agent will not quote any pricing")
    return NO_APPROVED_INFO


APPROVED_INFO = approved_info()


def lead_instructions(lead: dict) -> str:
    if not lead:
        return "Lead record: none. Treat this as a fresh contact."
    facts = "\n".join(f"- {k}: {v}" for k, v in lead.items())
    return f"Lead record (already known, so don't ask again; correct it if the driver says otherwise):\n{facts}"


def opening_line(lead: dict, persona_name: str | None = None, recording: bool = False) -> str:
    """Today's opening line. persona_name (console persona) names the agent; None keeps today's text.
    recording: this call is being recorded (the egress started), so the consent notice is appended."""
    me = f"main {persona_name}, Carrum Mobility" if persona_name else "main Carrum Mobility"
    if lead.get("previously_interested"):
        line = (
            f"Namaste sir, {me} ki AI calling assistant bol rahi hoon. Aapne Uber par gaadi "
            "chalane ke liye interest dikhaya tha. Kya abhi ek minute baat kar sakte hain?"
        )
    else:
        line = (
            f"Namaste sir, {me} se AI calling assistant bol rahi hoon. Hum Uber par gaadi chalane "
            "ke liye driving opportunities provide karte hain. Kya aap iske baare mein jaanna chahenge?"
        )
    if recording:
        line += " " + RECORDING_CONSENT
    return line


def opening_instructions(lead: dict, persona_name: str | None = None, recording: bool = False) -> str:
    return (
        f"Your opening line: {opening_line(lead, persona_name, recording)}\n"
        "If the driver speaks first (e.g. \"hello\", \"haan ji\", \"kaun?\"), let them finish, acknowledge "
        "it briefly (\"Ji, hello sir!\"), then say your opening line. Say the opening line only once."
    )


def builtin_instructions(lead: dict, language_rules: str, recording: bool = False) -> str:
    """The prompt used when the console has no config for this call: exactly today's text."""
    return "\n\n".join(
        [BASE_INSTRUCTIONS, language_rules, APPROVED_INFO, lead_instructions(lead),
         opening_instructions(lead, recording=recording)]
    )


_VARIABLE = re.compile(r"\{\{\s*lead\.([A-Za-z0-9_]+)\s*\}\}")
_EXPR_TOKEN = re.compile(r"[ \t]*\[\[expr:[^\]]*\]\]")
# Versions published before pauses were rendered as "..." carry this worded hint, which got read aloud.
_OLD_PAUSE_HINT = re.compile(r"\(pause for about [0-9.]+ seconds before this\)")


def pause_cues(text: str) -> str:
    """Old worded pause hints become "...", as the dashboard renders pauses now."""
    return _OLD_PAUSE_HINT.sub("...", text)


# The dashboard renders built-in expressions as "(say this …)" inside the line. Read inline like that, the
# realtime voice model spoke the hint ("say this with a light, warm laugh …") instead of acting it out.
_SAY_THIS_HINT = re.compile(r"[ \t]*\((say this\b[^()]*)\)")


def delivery_notes(text: str, hints: Sequence[str] = ()) -> str:
    """Move each line's expression hints ("(say this …)" and the agent's custom `hints`) out of the line into a
    "Delivery (not spoken): …" note on the line after it, so the hint is never part of the words to say. A hint
    on a line of its own applies to the next line with words."""
    custom = [h.strip() for h in hints if isinstance(h, str) and h.strip()]
    out: list[str] = []
    pending: list[str] = []
    for line in text.split("\n"):
        notes: list[str] = []

        def lift(match: re.Match) -> str:
            notes.append(match.group(1))
            return ""

        rest = _SAY_THIS_HINT.sub(lift, line)
        for hint in custom:
            spaced = re.compile(r"[ \t]*\(" + re.escape(hint) + r"\)")
            rest = spaced.sub(lambda m, h=hint: notes.append(h) or "", rest)
        if not notes and (not pending or not rest.strip()):
            out.append(line)
            continue
        if not rest.strip():
            # Only hints on this line: they belong to the next line with words.
            pending += notes
            continue
        indent = line[: len(line) - len(line.lstrip())]
        notes = pending + notes
        pending = []
        how = "; ".join(dict.fromkeys(re.sub(r"^say this\s+", "", n) for n in notes))
        out.append(indent + rest.strip())
        out.append(f"{indent}{DELIVERY_LABEL}: {how}")
    return "\n".join(out)


def fill_variables(text: str, lead: dict) -> str:
    """{{lead.x}} becomes the lead's value, or [unknown x] when the lead doesn't have it."""

    def value(match: re.Match) -> str:
        key = match.group(1)
        found = lead.get(key)
        if found is None or str(found).strip() == "":
            return f"[unknown {key.replace('_', ' ')}]"
        return str(found)

    return _VARIABLE.sub(value, pause_cues(text))


def strip_tokens(text: str) -> str:
    """Drop leftover [[expr:…]] tokens (old snapshots published before tone hints were rendered)."""
    return _EXPR_TOKEN.sub("", text)


def custom_hints(snapshot: dict | None) -> list[str]:
    """The agent's custom expression hints, from its snapshot's {name: hint}."""
    custom = (snapshot or {}).get("custom_expressions")
    return [h for h in custom.values() if isinstance(h, str)] if isinstance(custom, dict) else []


def knowledge_block(snapshot: dict) -> str:
    docs = snapshot.get("knowledge") or []
    if not docs:
        return NO_APPROVED_INFO
    hints = custom_hints(snapshot)
    sections = []
    for doc in docs:
        body = doc.get("body_rendered")
        if body is None:
            body = strip_tokens(doc.get("body_md") or "")
        body = delivery_notes(pause_cues(body), hints)
        sections.append(f"## {doc.get('title', '')}\n{body.strip()}")
    return APPROVED_HEADER + "\n\n".join(sections)


def persona_line(persona_name: str) -> str:
    return f"You are {persona_name}, a female AI calling assistant for Carrum Mobility Solutions."


# Worded for the start of the call only: a workflow can loop back to its start step later, without a new opening.
START_STEP_RULE = (
    "At the start of the call, your first turn is your opening line, even if the driver spoke first: answer their "
    "greeting in a few words (\"Ji, hello sir!\"), then say it. Take a path from this step only after you have said "
    "your opening line and the driver has replied to it."
)

TRANSFER_DIRECTION = (
    "Record the outcome, tell the driver you are connecting them, then call transfer_to_telecaller."
)
NO_TRANSFER_DIRECTION = (
    "Record the outcome, then offer a callback from the telecalling team; don't say you are connecting them."
)


def step_block(
    step: dict,
    lead: dict,
    paths: Sequence[Mapping] = (),
    handoff_available: bool = True,
    hints: Sequence[str] = (),
) -> str:
    """`hints` are the agent's custom expression hints, lifted out of the step prompt like the built-in ones."""
    prompt = delivery_notes(fill_variables(step.get("prompt") or "", lead), hints)
    lines = [f"Current step: {step.get('name', '')}", prompt.strip()]
    if step.get("type") == "start":
        # A caller's "hello" must not count as the start step being done (paths are often just "Next").
        lines.append(START_STEP_RULE)
    if paths:
        lines.append("When one of these happens, call the matching tool:")
        lines.extend(f"- {path['label']}: call {path['name']}" for path in paths)
    if step.get("type") == "end":
        lines.append(
            f"Record the outcome as {step.get('outcome')} with record_outcome, say this closing line, "
            "then call end_call."
        )
    elif step.get("type") == "transfer":
        # Without a handoff number the transfer can't happen: never promise one.
        lines.append(TRANSFER_DIRECTION if handoff_available else NO_TRANSFER_DIRECTION)
    return "\n".join(line for line in lines if line)


def build_instructions(
    snapshot: dict,
    lead: dict,
    language_rules: str,
    step: dict | None = None,
    paths: Sequence[Mapping] = (),
    handoff_available: bool = True,
) -> str:
    """The prompt for a call with a console config: system layer, script, then the current step."""
    parts = [SYSTEM_LAYER, persona_line(snapshot.get("persona_name") or PERSONA_NAME)]
    hints = custom_hints(snapshot)
    for section in snapshot.get("script") or []:
        body = delivery_notes(fill_variables(section.get("body_rendered") or "", lead), hints).strip()
        parts.append(f"## {section.get('title', '')}\n{body}")
    parts += [language_rules, knowledge_block(snapshot), lead_instructions(lead)]
    if step is not None:
        parts.append(step_block(step, lead, paths, handoff_available, hints))
    return "\n\n".join(parts)


def end_step_refusal(step: dict | None, disposition: str) -> str | None:
    """At an end step the agent must record that step's outcome; anything else is refused with this text."""
    if not step or step.get("type") != "end":
        return None
    outcome = step.get("outcome")
    if not outcome or outcome == disposition:
        return None
    return f"This step ends with {outcome}. Call record_outcome with disposition {outcome}."


def end_step_check(step: dict | None, disposition: str, refused: dict | None) -> tuple[str | None, bool, dict | None]:
    """The end-step rule with its override (ruling P18): a disposition other than the end step's outcome
    is refused once; recording that same disposition again straight after overrides the step.

    `refused` is the previous refusal ({"step_id", "disposition"}) or None. Returns the refusal text (or
    None), whether the step's outcome was overridden, and the refusal to remember for the next call."""
    refusal = end_step_refusal(step, disposition)
    if refusal is None:
        return None, False, None
    key = {"step_id": step.get("id"), "disposition": disposition}
    if refused == key:
        return None, True, None
    return refusal, False, key


def capped_outcome() -> dict:
    """Outcome recorded when the workflow loop limit stops the workflow (same fields as record_outcome)."""
    return {
        "disposition": "UNRESOLVED",
        "reason": "workflow loop limit reached",
        "summary": "",
        "interest_strength": "none",
        "telecaller_followup_agreed": False,
        "callback_time": "",
        "city": "",
        "licence": "",
        "experience": "",
        "uber_id": "",
        "preferred_plan": "",
        "main_question": "",
        "do_not_call": False,
    }
