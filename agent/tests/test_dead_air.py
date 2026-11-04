from dead_air import DeadAirConfig, DeadAirWatcher


def watcher() -> DeadAirWatcher:
    return DeadAirWatcher(DeadAirConfig())


def test_nudges_then_hangs_up():
    w = watcher()
    w.agent_listening(0)
    assert w.poll(3.9) is None
    assert w.poll(4.0) == "nudge"
    assert w.poll(5) is None
    assert w.poll(9) == "second_nudge"
    assert w.poll(15) == "hang_up"
    assert w.poll(20) is None


def test_agent_speech_pauses_but_does_not_reset():
    w = watcher()
    w.agent_listening(0)
    assert w.poll(4) == "nudge"
    w.agent_busy(4)
    w.agent_listening(7)
    assert w.poll(11.9) is None
    assert w.poll(12) == "second_nudge"  # 4 s + 5 s of silence = 9


def test_user_activity_resets():
    w = watcher()
    w.agent_listening(0)
    assert w.poll(4) == "nudge"
    w.user_activity(5)
    w.agent_listening(6)
    assert w.poll(9.9) is None
    assert w.poll(10) == "nudge"


def test_hold_phrase_triples_thresholds_once():
    w = watcher()
    w.user_activity(0, "Haan ek minute ruko")
    w.agent_listening(0)
    assert w.poll(11.9) is None
    assert w.poll(12) == "nudge"
    assert w.poll(45) == "hang_up"
    w.user_activity(50)
    w.agent_listening(50)
    assert w.poll(54) == "nudge"


def test_no_silence_counted_before_first_listening():
    assert watcher().poll(100) is None


def test_events_recorded():
    w = watcher()
    w.agent_listening(0)
    w.poll(4)
    assert w.events == [{"action": "nudge", "silence_s": 4.0}]
