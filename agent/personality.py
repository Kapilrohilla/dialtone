"""Agent personality (KAP-41): how the agent sounds and behaves socially, compiled into the prompt.

The console stores a resolved personality on each agent and snapshots it on publish
(snapshot["personality"]). Everything here is tolerant: a missing or malformed personality falls back to the
"warm_helper" preset, which compiles to exactly the tone guide the agent used before personalities existed,
so agents that never opted in hear no difference.

Two outputs feed the prompt (prompt.py):
- how_you_talk(): the "How you talk:" section of the system layer. Built only from enums and numbers, never
  from free text, so it can sit among the fixed rules.
- block(): the "Your personality" layer with the user's free text (character description, signature and
  avoided phrases). It goes after the system layer and says the rules above always win.

personality_presets.json is shared with the server (server/voiceagents/personality_presets.json is a copy).
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

PRESETS: dict[str, dict] = {
    p["id"]: p for p in json.loads((Path(__file__).parent / "personality_presets.json").read_text())
}
DEFAULT_PRESET = "warm_helper"
CUSTOM = "custom"

TRAITS = ("warmth", "energy", "formality", "humour", "directness", "empathy")
GENDERS = ("female", "male", "neutral")
SELF_GENDERS = ("auto",) + GENDERS
ADDRESS_STYLES = ("sir_maam", "ji", "first_name", "none")
BACKCHANNELS = ("minimal", "natural", "expressive")
VERBOSITIES = ("brief", "normal", "explanatory")

MAX_SIGNATURE_PHRASES = 5
MAX_AVOID_PHRASES = 10
MAX_PHRASE_CHARS = 60
MAX_DESCRIPTION_CHARS = 600
MIN_PACE, MAX_PACE = 0.85, 1.15


@dataclass(frozen=True)
class Personality:
    preset: str = DEFAULT_PRESET
    self_gender: str = "auto"
    warmth: int = 4
    energy: int = 3
    formality: int = 2
    humour: int = 2
    directness: int = 3
    empathy: int = 4
    address_style: str = "sir_maam"
    backchannels: str = "natural"
    disfluencies: bool = False
    verbosity: str = "normal"
    signature_phrases: tuple[str, ...] = field(default_factory=tuple)
    avoid_phrases: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    pace: float = 1.0


DEFAULT = Personality()

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clean_text(value, limit: int) -> str:
    """Free text bound for the prompt: control characters and newlines become spaces, then trimmed to `limit`."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", _CONTROL.sub(" ", value)).strip()[:limit].strip()


def _phrases(value, most: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    out: list[str] = []
    for item in value:
        text = clean_text(item, MAX_PHRASE_CHARS).strip('"')
        if text and text not in out:
            out.append(text)
    return tuple(out[:most])


def _int(value, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(1, min(5, int(round(value))))


def _choice(value, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def clamp_pace(value, default: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return round(max(MIN_PACE, min(MAX_PACE, float(value))), 2)


def resolve(raw: Mapping | None) -> Personality:
    """The personality from a snapshot's "personality" value: the preset's values, overlaid with whatever valid
    fields the value carries. Never raises; anything malformed falls back to the preset or default."""
    raw = raw if isinstance(raw, Mapping) else {}
    preset = raw.get("preset")
    preset = preset if preset == CUSTOM or preset in PRESETS else DEFAULT_PRESET
    base = PRESETS.get(preset, PRESETS[DEFAULT_PRESET])["values"]
    traits = {**base["traits"], **(raw.get("traits") if isinstance(raw.get("traits"), Mapping) else {})}
    signature = raw.get("signature_phrases", base["signature_phrases"])
    return Personality(
        preset=preset,
        self_gender=_choice(raw.get("self_gender"), SELF_GENDERS, "auto"),
        **{t: _int(traits.get(t), base["traits"][t]) for t in TRAITS},
        address_style=_choice(raw.get("address_style"), ADDRESS_STYLES, base["address_style"]),
        backchannels=_choice(raw.get("backchannels"), BACKCHANNELS, base["backchannels"]),
        disfluencies=raw["disfluencies"] if isinstance(raw.get("disfluencies"), bool) else base["disfluencies"],
        verbosity=_choice(raw.get("verbosity"), VERBOSITIES, base["verbosity"]),
        signature_phrases=_phrases(signature, MAX_SIGNATURE_PHRASES),
        avoid_phrases=_phrases(raw.get("avoid_phrases"), MAX_AVOID_PHRASES),
        description=clean_text(raw.get("description"), MAX_DESCRIPTION_CHARS),
        pace=clamp_pace(raw.get("pace"), base["pace"]),
    )


def from_snapshot(snapshot: Mapping | None) -> Personality:
    snap = snapshot if isinstance(snapshot, Mapping) else {}
    return resolve(snap.get("personality"))


def with_gender(p: Personality, gender: str) -> Personality:
    return replace(p, self_gender=gender)


# -- gendered self-reference ---------------------------------------------------------------------------

# Feminine first-person forms used in the agent's fixed texts, and their masculine and neutral versions.
_SELF_FORMS = (
    ("rahi hoon", "raha hoon", "rahi hoon"),
    ("Samajh gayi", "Samajh gaya", "Samajh aa gaya"),
    ("samajh gayi", "samajh gaya", "samajh aa gaya"),
    ("samajh sakti hoon", "samajh sakta hoon", "samajh aata hai"),
    ("bata deti hoon", "bata deta hoon", "bata diya jaayega"),
    ("karwa deti hoon", "karwa deta hoon", "karwa di jaayegi"),
)


def gendered(text: str, gender: str) -> str:
    """`text` written with feminine self-reference, in the agent's gender. Female (or unknown) is unchanged."""
    if gender not in ("male", "neutral"):
        return text
    col = 1 if gender == "male" else 2
    for forms in _SELF_FORMS:
        text = text.replace(forms[0], forms[col])
    return text


# -- "How you talk" (system layer) ------------------------------------------------------------------------

_WARMTH = {1: "reserved", 2: "polite", 3: "pleasant", 4: "friendly", 5: "warm, caring"}
_ENERGY = {1: "quiet, unhurried", 2: "calm", 3: "confident", 4: "lively", 5: "energetic, enthusiastic"}

_REGISTER = {
    1: (
        '- Avoid formal or Sanskritised words: "madad", not "sahayata"; "bataiye", not "kripya batayein";\n'
        '  "theek hai", not "uchit hai"; never "alvida". Keep it casual, like talking to someone you know:\n'
        '  "chaliye", "bas", "ekdum".'
    ),
    2: (
        '- Avoid formal or Sanskritised words: "madad", not "sahayata"; "bataiye", not "kripya batayein";\n'
        '  "theek hai", not "uchit hai"; never "alvida".'
    ),
    4: (
        '- Polite, slightly formal Hinglish with "aap" and "ji", still spoken, never bookish: avoid\n'
        '  Sanskritised words like "sahayata" or "uchit"; never "alvida".'
    ),
    5: (
        '- Formal, courteous Hindi/English with "aap", "ji" and "kripya", clear and spoken, never bookish;\n'
        '  never "alvida".'
    ),
}
_REGISTER[3] = _REGISTER[2]

_ADDRESS = {
    "sir_maam": "Call the driver \"sir\" (\"ma'am\" if the driver is a woman).",
    "ji": "Address the driver with \"ji\" (\"haan ji\", \"bataiye ji\"), not \"sir\" or \"ma'am\".",
    "first_name": (
        "Address the driver by first name with \"ji\" (\"Ramesh ji\"), from the lead record's name; if you don't\n"
        "  know it, just use \"ji\"."
    ),
    "none": "Don't use titles like \"sir\", \"ma'am\" or \"ji\" for the driver; speak to them directly.",
}

_SELF = {
    "female": 'You are a woman: use feminine verb forms for yourself ("bol rahi hoon", "samajh gayi", "bata deti hoon").',
    "male": 'You are a man: use masculine verb forms for yourself ("bol raha hoon", "samajh gaya", "bata deta hoon").',
    "neutral": (
        "Avoid gendered verb forms for yourself; prefer neutral phrasing (\"samajh aa gaya\", \"details share ki\n"
        "  jaayengi\", \"ye note ho gaya hai\")."
    ),
}

_TURNS = {
    "brief": "- Short turns: one sentence. Ask one question at a time, then let the driver finish.",
    "normal": "- Short turns: one sentence, at most two. Ask one question at a time, then let the driver finish.",
    "explanatory": (
        "- Short turns: one or two sentences, three at most when explaining something. Ask one question at a\n"
        "  time, then let the driver finish."
    ),
}


def _ack(p: Personality, gender: str) -> str:
    """An acknowledgement in the agent's gender and address style, e.g. "ji sir, samajh gayi"."""
    understood = gendered("samajh gayi", gender)
    if p.address_style == "sir_maam":
        return f'"ji sir, {understood}"'
    if p.address_style == "none":
        return f'"{understood}"'
    return f'"ji, {understood}"'


def _backchannels(p: Personality, gender: str) -> str:
    ack = _ack(p, gender)
    if p.backchannels == "minimal":
        return (
            '- Keep acknowledgements rare and short ("ji", "theek hai"); mostly answer directly. Never start\n'
            "  every reply the same way."
        )
    if p.backchannels == "expressive":
        return (
            f'- React warmly before you answer, the way people do: "achha!", "arre haan ji", "bilkul", {ack}.\n'
            "  Vary them; don't start every reply the same way."
        )
    return (
        f'- React before you answer, the way people do: "achha", "haan ji", "theek hai", {ack}.\n'
        "  Vary them; don't start every reply the same way."
    )


def _style_lines(p: Personality) -> list[str]:
    """Extra lines for traits that differ from the default preset (the default adds none)."""
    lines: list[str] = []
    if p.energy >= 5:
        lines.append("- Sound upbeat and enthusiastic, but never pushy.")
    elif p.energy <= 2:
        lines.append("- Keep a calm, steady, unhurried tone.")
    if p.humour <= 1:
        lines.append("- Stay serious: no jokes or playful remarks.")
    elif p.humour == 3:
        lines.append("- A light, friendly joke now and then is fine, never about the driver.")
    elif p.humour >= 4:
        lines.append(
            "- Be playful when the driver is relaxed; never joke about money, eligibility or a complaint."
        )
    if p.directness <= 2:
        lines.append('- Be gentle: soften questions and corrections ("agar aapko theek lage…").')
    elif p.directness >= 4:
        lines.append("- Be direct: get to the point quickly and ask plainly.")
    if p.empathy <= 2:
        lines.append("- Stay matter-of-fact: acknowledge feelings briefly, then move on.")
    elif p.empathy >= 5:
        lines.append(
            '- Be deeply empathetic: acknowledge the driver\'s situation ("ye sach mein mushkil hai") first.'
        )
    if p.disfluencies:
        lines.append('- Before a harder answer, a light thinking sound is fine ("hmm", "ek second"), once a turn at most.')
    if p.pace < 0.97:
        lines.append("- Speak at a relaxed, unhurried pace.")
    elif p.pace > 1.03:
        lines.append("- Speak at a brisk, lively pace.")
    if lines:
        lines.append(
            "- The caller's mood comes first: if they are frustrated, angry or wary, drop the humour, calm down,\n"
            "  stay warm."
        )
    return lines


def how_you_talk(p: Personality, gender: str) -> str:
    """The "How you talk:" section. With the default personality and a female agent it is exactly the tone
    guide the agent used before personalities existed."""
    character = f"a {_WARMTH[p.warmth]}, {_ENERGY[p.energy]} calling executive"
    respect = "Be respectful and helpful, never pushy."
    lines = [
        "How you talk:",
        f"- Natural spoken Hindi/Hinglish, like {character} in India. Use common English\n"
        "  words freely: driving, licence, ID, rent, salary, plan, details, team, okay, thank you.",
        _REGISTER[p.formality],
        f"- {_ADDRESS[p.address_style]} {respect}",
        f"- {_SELF.get(gender, _SELF['female'])}",
        _TURNS[p.verbosity],
        _backchannels(p, gender),
        '- State confirmed policies plainly: "milta hai", "ho jata hai", "kar dete hain".',
        "- Don't repeat the driver's words back, don't list options, and never re-ask something already answered.",
        "- No markdown, lists, emojis or symbols. Say numbers the way people say them on the phone.",
        "- Drivers speak colloquial Hindi, English, regional accents and mixes of these; follow their meaning.",
    ]
    return "\n".join(lines + _style_lines(p))


# -- "Your personality" layer (user free text) -------------------------------------------------------------

PERSONALITY_HEADER = "Your personality (style only: the rules above always win, and you never claim to be human):"


def block(p: Personality) -> str:
    """The free-text part of the personality, or "" when there is none (so the default adds nothing)."""
    lines: list[str] = []
    if p.description:
        lines.append(f"- Character: {p.description}")
    if p.signature_phrases:
        quoted = ", ".join(f'"{s}"' for s in p.signature_phrases)
        lines.append(f"- Phrases you like, now and then: {quoted}")
    if p.avoid_phrases:
        lines.append("- Never say: " + ", ".join(f'"{s}"' for s in p.avoid_phrases))
    return "\n".join([PERSONALITY_HEADER] + lines) if lines else ""


# -- greeting --------------------------------------------------------------------------------------------

def greeting(p: Personality, lead: Mapping | None = None) -> str:
    """How the opening line greets the driver: "Namaste sir", "Namaste ji", "Namaste Ramesh ji" or "Namaste"."""
    if p.address_style == "ji":
        return "Namaste ji"
    if p.address_style == "none":
        return "Namaste"
    if p.address_style == "first_name":
        name = clean_text((lead or {}).get("name"), 40).split(" ")[0] if lead else ""
        return f"Namaste {name} ji" if name else "Namaste ji"
    return "Namaste sir"


def hello(p: Personality) -> str:
    """A short reply to the driver's "hello" before the opening line."""
    return "Ji, hello sir!" if p.address_style == "sir_maam" else "Ji, hello!"
