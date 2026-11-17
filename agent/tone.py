"""Tone policy: turns a caller mood into a prompt note, a TTS speed and a handoff hint.

The agent's personality (personality.py) is the baseline; a caller's mood wins over it. For frustrated, angry and
wary callers the note says to drop humour and keep energy low, and the mood's TTS speed multiplies the
personality's baseline pace (effective_speed)."""

from dataclasses import dataclass

from mood import Emotion
from personality import gendered


@dataclass(frozen=True)
class ToneDirective:
    note: str
    tts_speed: float
    offer_handoff: bool


TONE_POLICY: dict[Emotion, ToneDirective] = {
    "neutral": ToneDirective("", 1.0, False),
    "interested": ToneDirective(
        "Caller sounds interested. Move toward confirming interest and the telecaller follow-up; "
        "don't over-explain.",
        1.0,
        False,
    ),
    "confused": ToneDirective(
        "Caller sounds confused. Slow down, use simpler words, one point at a time, and check they "
        "understood before moving on.",
        0.9,
        False,
    ),
    "frustrated": ToneDirective(
        'Caller sounds frustrated. Acknowledge briefly ("samajh sakti hoon sir"), keep replies to '
        "one short sentence, stop pitching, offer a callback or the telecalling team.",
        0.92,
        True,
    ),
    "rushed": ToneDirective(
        "Caller seems short on time. Ask only what is essential, or offer a callback at a time "
        "that suits them.",
        1.08,
        False,
    ),
    "suspicious": ToneDirective(
        "Caller sounds wary. Be transparent about who you are calling for and never ask for documents "
        "or money; if they ask whether you're an AI, say so honestly. Answer their doubt before anything else.",
        0.95,
        False,
    ),
    "angry": ToneDirective(
        "Caller sounds angry. Apologise once, don't argue or pitch, offer to end the call or "
        "connect them to the team; if they ask not to be called, set do_not_call.",
        0.9,
        True,
    ),
    "disengaged": ToneDirective(
        "Caller seems disengaged. Ask one short direct question to check if this is a good time; "
        "if not, offer a callback.",
        1.0,
        False,
    ),
}


# Moods where the caller's state overrides the personality's humour and energy (KAP-41).
CALMING_MOODS = ("frustrated", "angry", "suspicious")
PRECEDENCE_NOTE = "Drop any humour or playfulness and keep your energy low, but stay warm."

MIN_SPEED, MAX_SPEED = 0.8, 1.2


def effective_speed(pace: float, emotion: Emotion) -> float:
    """The TTS speed for the agent's baseline `pace` and the caller's mood, clamped to 0.8-1.2."""
    speed = pace * TONE_POLICY[emotion].tts_speed
    return round(max(MIN_SPEED, min(MAX_SPEED, speed)), 3)


def _note(emotion: Emotion, gender: str) -> str:
    note = gendered(TONE_POLICY[emotion].note, gender)
    return f"{note} {PRECEDENCE_NOTE}" if emotion in CALMING_MOODS else note


HANDOFF_NOTE = "If they agree to speak to a person now, call record_outcome, then transfer_to_telecaller."


def mood_message(emotion: Emotion, handoff_available: bool = False, gender: str = "female") -> str:
    """The system note telling the LLM how to adjust. Each one replaces the previous one. `gender` is the
    agent's (prompt.Identity.gender), for the example phrases it speaks."""
    if emotion == "neutral":
        return "[Caller mood: neutral] Talk normally. This replaces any earlier caller-mood note."
    directive = TONE_POLICY[emotion]
    handoff = f" {HANDOFF_NOTE}" if directive.offer_handoff and handoff_available else ""
    return (
        f"[Caller mood: {emotion}] {_note(emotion, gender)}{handoff} Never tell the caller you can tell how they feel. "
        "This replaces any earlier caller-mood note."
    )


def tone_guide(handoff_available: bool = False, gender: str = "female") -> str:
    """The whole tone policy as one block for the starting instructions, for models that hear the
    caller's voice themselves (Gemini Live) and so get no mid-call mood notes."""
    lines = ["Adapting to the caller: listen to how they sound as well as what they say."]
    for emotion, directive in TONE_POLICY.items():
        if emotion == "neutral":
            continue
        handoff = f" {HANDOFF_NOTE}" if directive.offer_handoff and handoff_available else ""
        lines.append(f"- {emotion}: {_note(emotion, gender)}{handoff}")
    lines.append("Never tell the caller you can tell how they feel. Otherwise, talk normally.")
    return "\n".join(lines)
