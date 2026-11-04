from typing import get_args

from mood import Emotion
from tone import TONE_POLICY, ToneDirective, mood_message


def test_every_emotion_has_policy():
    assert set(TONE_POLICY) == set(get_args(Emotion))


def test_message_has_guardrail():
    for e in get_args(Emotion):
        if e != "neutral":
            assert "Never tell the caller" in mood_message(e)


def test_neutral_policy_and_message():
    assert TONE_POLICY["neutral"] == ToneDirective("", 1.0, False)
    assert mood_message("neutral") == (
        "[Caller mood: neutral] Talk normally. This replaces any earlier caller-mood note."
    )


def test_handoff_note_only_when_enabled():
    assert "transfer_to_telecaller" in mood_message("angry", handoff_available=True)
    assert "transfer_to_telecaller" not in mood_message("angry", handoff_available=False)
    # Moods without offer_handoff never mention it.
    assert "transfer_to_telecaller" not in mood_message("confused", handoff_available=True)


def test_tone_guide_covers_every_mood_once():
    from tone import tone_guide

    guide = tone_guide()
    for e in get_args(Emotion):
        if e != "neutral":
            assert TONE_POLICY[e].note in guide
    assert "Never tell the caller" in guide
    assert "transfer_to_telecaller" not in guide
    assert "transfer_to_telecaller" in tone_guide(handoff_available=True)
