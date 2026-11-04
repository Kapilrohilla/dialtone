from behavior import BehaviorTracker


def test_rushed_after_two_interruptions_in_three():
    b = BehaviorTracker()
    b.agent_turn_ended(1, interrupted=True)
    b.agent_turn_ended(2, interrupted=False)
    b.agent_turn_ended(3, interrupted=True)
    reading = b.poll(4)
    assert reading is not None
    assert reading.emotion == "rushed"
    assert reading.source == "behavior"
    assert reading.sentiment == 0
    assert reading.confidence == 0.7
    assert reading.at_s == 4
    assert b.poll(5) is None


def test_disengaged_needs_short_and_slow():
    b = BehaviorTracker()
    for i, word in enumerate(["haan", "ok", "ji"]):
        b.user_turn(i, word, reply_latency_s=3)
    reading = b.poll(3)
    assert reading is not None
    assert reading.emotion == "disengaged"

    quick = BehaviorTracker()
    for i, word in enumerate(["haan", "ok", "ji"]):
        quick.user_turn(i, word, reply_latency_s=0.5)
    assert quick.poll(3) is None


def test_features():
    b = BehaviorTracker()
    assert b.features() == {
        "interruptions": 0,
        "agent_turns": 0,
        "median_reply_latency_s": None,
        "median_reply_words": None,
    }
    b.agent_turn_ended(1, interrupted=True)
    b.agent_turn_ended(2, interrupted=False)
    b.agent_turn_ended(3, interrupted=False)
    b.user_turn(1.5, "haan ji bolo", reply_latency_s=1.0)
    b.user_turn(2.5, "nahi", reply_latency_s=2.0)
    b.user_turn(3.5, "abhi time nahi hai baad mein", reply_latency_s=4.0)
    assert b.features() == {
        "interruptions": 1,
        "agent_turns": 3,
        "median_reply_latency_s": 2.0,
        "median_reply_words": 3,
    }


def test_reply_latency_not_trusted_on_gemini():
    from behavior import reply_latency_reliable

    assert reply_latency_reliable("gemini-live") is False
    assert reply_latency_reliable("sarvam") is True
