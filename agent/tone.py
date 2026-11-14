"""Tone policy: turns a caller mood into a prompt note, a TTS speed and a handoff hint."""

from dataclasses import dataclass

from mood import Emotion


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
        "Caller sounds wary. Be transparent: you are the company's AI assistant and never ask for "
        "documents or money. Answer their doubt before anything else.",
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


HANDOFF_NOTE = "If they agree to speak to a person now, call record_outcome, then transfer_to_telecaller."


def mood_message(emotion: Emotion, handoff_available: bool = False) -> str:
    """The system note telling the LLM how to adjust. Each one replaces the previous one."""
    if emotion == "neutral":
        return "[Caller mood: neutral] Talk normally. This replaces any earlier caller-mood note."
    directive = TONE_POLICY[emotion]
    handoff = f" {HANDOFF_NOTE}" if directive.offer_handoff and handoff_available else ""
    return (
        f"[Caller mood: {emotion}] {directive.note}{handoff} Never tell the caller you can tell how they feel. "
        "This replaces any earlier caller-mood note."
    )


def tone_guide(handoff_available: bool = False) -> str:
    """The whole tone policy as one block for the starting instructions, for models that hear the
    caller's voice themselves (Gemini Live) and so get no mid-call mood notes."""
    lines = ["Adapting to the caller: listen to how they sound as well as what they say."]
    for emotion, directive in TONE_POLICY.items():
        if emotion == "neutral":
            continue
        handoff = f" {HANDOFF_NOTE}" if directive.offer_handoff and handoff_available else ""
        lines.append(f"- {emotion}: {directive.note}{handoff}")
    lines.append("Never tell the caller you can tell how they feel. Otherwise, talk normally.")
    return "\n".join(lines)
