"""Applies a caller mood to the live call: a tone note in the instructions, and the speaking pace."""

import dataclasses
import logging

from livekit.agents.utils import is_given
from livekit.plugins import elevenlabs, sarvam

from mood import Emotion
from tone import TONE_POLICY, mood_message

logger = logging.getLogger("phone-agent")

# ElevenLabs' own defaults, used when the voice has no settings of its own yet.
ELEVENLABS_DEFAULT_STABILITY = 0.5
ELEVENLABS_DEFAULT_SIMILARITY = 0.75


async def apply_mood(
    agent, tts, emotion: Emotion, base_instructions: str, handoff_available: bool = False
) -> None:
    """Replace the mood note in the agent's instructions and, where the TTS allows, set its pace.

    Uses update_instructions rather than a system message in the chat history: Gemini Live drops
    system messages from history but takes instruction updates mid-session without reconnecting,
    and replacing the note keeps old notes from piling up.
    """
    note = mood_message(emotion, handoff_available=handoff_available)
    await agent.update_instructions(f"{base_instructions}\n\n{note}")
    if tts is not None:
        set_tts_speed(tts, TONE_POLICY[emotion].tts_speed)


def set_tts_speed(tts, speed: float) -> bool:
    """Set the speaking pace on TTS engines that support it. Returns False for any other engine."""
    if isinstance(tts, sarvam.TTS):
        tts.update_options(pace=speed)
        return True
    if isinstance(tts, elevenlabs.TTS):
        current = tts._opts.voice_settings
        if is_given(current):
            settings = dataclasses.replace(current, speed=speed)
        else:
            settings = elevenlabs.VoiceSettings(
                stability=ELEVENLABS_DEFAULT_STABILITY,
                similarity_boost=ELEVENLABS_DEFAULT_SIMILARITY,
                speed=speed,
            )
        tts.update_options(voice_settings=settings)
        return True
    return False
