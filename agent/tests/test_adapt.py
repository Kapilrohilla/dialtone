from livekit.plugins import elevenlabs, sarvam

from adapt import apply_mood, set_tts_speed
from tone import mood_message


class FakeAgent:
    def __init__(self) -> None:
        self.instructions_set: list[str] = []

    async def update_instructions(self, instructions: str) -> None:
        self.instructions_set.append(instructions)


async def test_apply_mood_replaces_mood_note():
    agent = FakeAgent()
    await apply_mood(agent, None, "frustrated", "BASE")
    await apply_mood(agent, None, "neutral", "BASE")
    assert agent.instructions_set == [
        "BASE\n\n" + mood_message("frustrated"),
        "BASE\n\n" + mood_message("neutral"),
    ]


async def test_apply_mood_sets_tts_speed():
    tts = sarvam.TTS(api_key="test", target_language_code="hi-IN")
    await apply_mood(FakeAgent(), tts, "confused", "BASE")
    assert tts._opts.pace == 0.9


def test_elevenlabs_speed_keeps_other_settings():
    tts = elevenlabs.TTS(api_key="test", voice_settings=elevenlabs.VoiceSettings(stability=0.3, similarity_boost=0.6))
    assert set_tts_speed(tts, 1.08) is True
    assert tts._opts.voice_settings.stability == 0.3
    assert tts._opts.voice_settings.speed == 1.08


def test_elevenlabs_speed_without_settings_uses_defaults():
    tts = elevenlabs.TTS(api_key="test")
    assert set_tts_speed(tts, 0.9) is True
    vs = tts._opts.voice_settings
    assert (vs.stability, vs.similarity_boost, vs.speed) == (0.5, 0.75, 0.9)


def test_unknown_tts_is_skipped():
    assert set_tts_speed(object(), 0.9) is False
