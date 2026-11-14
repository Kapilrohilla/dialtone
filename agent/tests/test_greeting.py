from greeting import GreetingGate


def gate() -> GreetingGate:
    g = GreetingGate(wait_s=1.0, gap_s=0.8, max_s=5.0)
    g.start(0.0)
    return g


def test_silent_caller_greeted_after_short_wait():
    g = gate()
    assert not g.ready(0.9)
    assert g.ready(1.0)
    assert g.caller_said == ""


def test_waits_for_caller_to_finish_hello():
    g = gate()
    g.caller_spoke(0.3, "hel")
    g.caller_spoke(0.6, "hello")
    g.caller_spoke(1.0, "hello, kaun?")
    assert not g.ready(1.5)
    assert g.ready(1.8)
    assert g.caller_said == "hello, kaun?"


def test_long_talker_greeted_at_max_wait():
    g = gate()
    for i in range(1, 50):
        g.caller_spoke(i * 0.2, "bol raha hoon")
    assert not g.ready(4.9)
    assert g.ready(5.0)


def test_noise_without_text_still_counts_as_speech():
    g = gate()
    g.caller_spoke(0.5, None)
    assert not g.ready(1.2)
    assert g.ready(1.3)
    assert g.caller_said == ""


def test_greeting_instructions_when_caller_was_silent():
    from greeting import greeting_instructions

    text = greeting_instructions("Namaste sir, main Northwind Car Rentals se bol rahi hoon.", "")
    assert text == "Open the call by saying this, close to word for word: Namaste sir, main Northwind Car Rentals se bol rahi hoon."


def test_greeting_instructions_acknowledge_hello_first():
    from greeting import greeting_instructions

    text = greeting_instructions("Namaste sir, main Northwind Car Rentals se bol rahi hoon.", "hello kaun?")
    assert '"hello kaun?"' in text
    assert "Ji, hello sir" in text
    assert text.endswith("Namaste sir, main Northwind Car Rentals se bol rahi hoon.")


OPENING = "Namaste sir, main Maya, Northwind Car Rentals se AI calling assistant bol rahi hoon."


def test_leaving_the_start_step_before_speaking_is_refused_with_the_opening():
    from greeting import start_path_refusal

    refusal = start_path_refusal("start", 0, agent_spoke=False, opening=OPENING)
    assert refusal is not None
    assert OPENING in refusal and "Ji, hello sir" in refusal


def test_start_step_paths_allowed_once_the_agent_has_spoken_or_the_call_moved_on():
    from greeting import start_path_refusal

    assert start_path_refusal("start", 0, agent_spoke=True, opening=OPENING) is None
    # Back on the start step later in the call (a loop): the opening was said long ago.
    assert start_path_refusal("start", 3, agent_spoke=False, opening=OPENING) is None
    assert start_path_refusal("prompt", 0, agent_spoke=False, opening=OPENING) is None
    assert start_path_refusal(None, 0, agent_spoke=False, opening=OPENING) is None
