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
