from pathlib import Path

import pytest

import prompt
from prompt import (
    SCRIPT_FALLBACK,
    SYSTEM_LAYER,
    build_instructions,
    builtin_instructions,
    end_step_refusal,
    fill_variables,
    knowledge_block,
    strip_tokens,
)

FIXTURES = Path(__file__).parent / "fixtures"
LEAD = {"lead_id": "L123", "name": "Ramesh", "city": "Pune", "previously_interested": True}


def snapshot(**overrides) -> dict:
    snap = {
        "agent_id": 1,
        "version": 3,
        "name": "Carrum leads",
        "persona_name": "Anjali",
        "language": "hi-IN",
        "voice_id": "",
        "phone_number": "+911234567890",
        "settings": {},
        "custom_expressions": [],
        "script": [
            {"title": "Your job", "body_rendered": "Find out if {{lead.name}} wants to drive."},
            {"title": "Close", "body_rendered": "Thank them (say this with a light, warm laugh)."},
        ],
        "variables": [],
        "knowledge": [],
        "workflow": None,
    }
    snap.update(overrides)
    return snap


@pytest.fixture
def rules():
    return "Language:\n- Start in Hindi."


def fresh_prompt(tmp_path, monkeypatch):
    """prompt.py loaded from a copy in an empty dir with the env cleared: no knowledge.md, no persona
    override, recording off, default language. The golden fixtures are independent of the local setup."""
    import importlib.util
    import shutil

    for var in ("AGENT_PERSONA_NAME", "RECORDING_ENABLED", "DEFAULT_LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    copy = tmp_path / "prompt_golden.py"
    shutil.copy(Path(prompt.__file__), copy)
    spec = importlib.util.spec_from_file_location("prompt_golden", copy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_builtin_matches_today(tmp_path, monkeypatch):
    gemini = (FIXTURES / "builtin_gemini_lead.txt").read_text()
    sarvam = (FIXTURES / "builtin_sarvam_nolead.txt").read_text()
    # Fixtures were captured from PhoneAgent.base_instructions before the refactor.
    import agent

    fresh = fresh_prompt(tmp_path, monkeypatch)
    assert fresh.builtin_instructions(LEAD, fresh.GEMINI_LANGUAGE_RULES) == gemini
    assert fresh.builtin_instructions({}, agent.SARVAM_LANGUAGE_RULES) == sarvam


def test_system_layer_contents():
    for needle in [
        "You are an AI assistant. Say so in your opening",
        "How you talk:",
        "Saying the company name:",
        "Never ask for Aadhaar, PAN, bank details or any document numbers.",
        "Never:\n- Pressure a driver",
        "Recording the outcome with `record_outcome`:",
        "call `record_outcome`, then say the matching line, then call `end_call`",
        "Quote only figures, offers and rules written under Approved information. If it isn't there, "
        "say the telecalling team will share the exact details.",
        "If a line contains [unknown …], say it naturally without that detail.",
    ]:
        assert needle in SYSTEM_LAYER, needle
    assert "The call:" not in SYSTEM_LAYER
    assert "Your job:" not in SYSTEM_LAYER


def test_script_fallback_contents():
    assert SCRIPT_FALLBACK.startswith(f"You are {prompt.PERSONA_NAME}, a female AI calling assistant")
    assert "Your job:" in SCRIPT_FALLBACK
    assert "The call:\n1. Opening:" in SCRIPT_FALLBACK
    assert "7. Close:" in SCRIPT_FALLBACK
    assert "How you talk:" not in SCRIPT_FALLBACK
    assert "Recording the outcome with" not in SCRIPT_FALLBACK


def test_system_layer_always_present_with_snapshot(rules):
    text = build_instructions(snapshot(script=[]), {}, rules)
    assert text.startswith(SYSTEM_LAYER)
    assert (
        "You are Anjali, a female AI calling assistant for Carrum Mobility Solutions." in text
    )


def test_layer_order(rules):
    snap = snapshot(knowledge=[{"id": 1, "title": "Pune", "revision": 1, "body_md": "Deposit 5000"}])
    text = build_instructions(snap, LEAD, rules)
    order = [
        SYSTEM_LAYER,
        "You are Anjali,",
        "## Your job",
        rules,
        "Approved information (the only",
        "Lead record (already known",
    ]
    positions = [text.index(part) for part in order]
    assert positions == sorted(positions)
    assert "Current step:" not in text


def test_script_sections_rendered_in_order(rules):
    text = build_instructions(snapshot(), LEAD, rules)
    job = text.index("## Your job\nFind out if Ramesh wants to drive.")
    close = text.index("## Close\nThank them.\nDelivery (not spoken): with a light, warm laugh")
    assert job < close


def test_missing_variable_placeholder():
    out = fill_variables("Namaste {{lead.name}} from {{lead.home_city}}", {})
    assert out == "Namaste [unknown name] from [unknown home city]"
    assert "{{" not in out
    assert fill_variables("{{lead.name}}", {"name": ""}) == "[unknown name]"
    assert fill_variables("{{lead.name}}", {"name": None}) == "[unknown name]"


def test_variable_filled():
    assert fill_variables("Hi {{lead.name}}, {{lead.age}}", {"name": "Ramesh", "age": 31}) == "Hi Ramesh, 31"
    assert fill_variables("{{ lead.name }}", {"name": "Ramesh"}) == "Ramesh"


def test_old_pause_hints_become_silent_cues():
    old = "Namaste {{lead.name}} (pause for about 1.5 seconds before this) sir"
    assert fill_variables(old, {"name": "Ravi"}) == "Namaste Ravi ... sir"
    snapshot = {"script": [{"title": "Opening", "body_rendered": old}],
                "knowledge": [{"title": "Plans", "body_rendered": "A (pause for about 1 seconds before this) B"}]}
    text = build_instructions(snapshot, {"name": "Ravi"}, "")
    assert "pause for about" not in text and "Namaste Ravi ... sir" in text and "A ... B" in text


def test_delivery_hints_lifted_out_of_the_spoken_line():
    # KAP-11: the model spoke "(say this with a light, warm laugh) आप अभी किस शहर में रहते हैं?" verbatim.
    line = "(say this with a light, warm laugh) आप अभी किस शहर में रहते हैं?"
    assert prompt.delivery_notes(line) == (
        "आप अभी किस शहर में रहते हैं?\nDelivery (not spoken): with a light, warm laugh"
    )
    assert prompt.delivery_notes("  Haan ji (be playful) sir.", ["be playful"]) == (
        "  Haan ji sir.\n  Delivery (not spoken): be playful"
    )
    # A hint alone on its line goes with the next line that has words; other text is untouched.
    assert prompt.delivery_notes("(say this warmly)\n\nNamaste sir (Carrum)") == (
        "\nNamaste sir (Carrum)\nDelivery (not spoken): warmly"
    )
    assert prompt.delivery_notes("Sir (Delhi NCR) mein?") == "Sir (Delhi NCR) mein?"


def test_no_inline_hints_reach_the_model():
    hint = "(say this firmly but calmly, never rude)"
    snapshot = {
        "custom_expressions": {"tease": "say it teasingly"},
        "script": [{"title": "Opening", "body_rendered": f"{hint} Namaste (say it teasingly) {{{{lead.name}}}}"}],
        "knowledge": [{"title": "Plans", "body_rendered": "(say this warmly) Rent milta hai"}],
    }
    step = {"name": "City", "type": "collect", "prompt": "(say this with a light, warm laugh) Kis city mein?"}
    text = build_instructions(snapshot, {"name": "Ravi"}, "", step)
    assert "(say this" not in text and "(say it teasingly)" not in text
    assert "Namaste Ravi\nDelivery (not spoken): firmly but calmly, never rude; say it teasingly" in text
    assert "Kis city mein?\nDelivery (not spoken): with a light, warm laugh" in text
    assert "Rent milta hai\nDelivery (not spoken): warmly" in text


def test_strip_tokens():
    assert strip_tokens("Haan ji [[expr:laugh]] sir [[expr:sigh]].") == "Haan ji sir."
    assert strip_tokens("no tokens") == "no tokens"


def test_knowledge_uses_body_rendered_else_strips_tokens():
    snap = snapshot(
        knowledge=[
            {"id": 1, "title": "Pune", "revision": 2, "body_md": "raw [[expr:laugh]]",
             "body_rendered": "Deposit 5000 (say this with a light, warm laugh)"},
            {"id": 2, "title": "Mumbai", "revision": 1, "body_md": "Deposit 7000 [[expr:laugh]] only"},
        ]
    )
    block = knowledge_block(snap)
    assert block == (
        "Approved information (the only figures, offers and rules you may quote or apply):\n"
        "## Pune\nDeposit 5000\nDelivery (not spoken): with a light, warm laugh\n\n"
        "## Mumbai\nDeposit 7000 only"
    )


def test_no_knowledge_uses_none_available_text():
    block = knowledge_block(snapshot(knowledge=[]))
    assert block.startswith("Approved information: none available. Don't quote any deposit")
    assert block == prompt.NO_APPROVED_INFO
    assert knowledge_block({}) == prompt.NO_APPROVED_INFO


def test_step_block_lists_paths(rules):
    step = {"id": "s1", "name": "Licence", "type": "question", "prompt": "Ask {{lead.name}} about the licence.",
            "field": "licence", "knowledge_id": None, "outcome": None, "position": {}}
    paths = [{"name": "path_has_licence", "label": "Has a licence"},
             {"name": "path_no_licence", "label": "No licence"}]
    text = build_instructions(snapshot(), LEAD, rules, step=step, paths=paths)
    block = text[text.index("Current step:"):]
    assert block.startswith("Current step: Licence\nAsk Ramesh about the licence.\n"
                            "When one of these happens, call the matching tool:")
    assert "- Has a licence: call path_has_licence" in block
    assert "- No licence: call path_no_licence" in block
    assert text.index("Lead record") < text.index("Current step:")


def test_end_step_block_names_outcome(rules):
    step = {"id": "e", "name": "Not interested", "type": "end", "prompt": "Theek hai sir, dhanyavaad.",
            "field": None, "knowledge_id": None, "outcome": "NI", "position": {}}
    text = build_instructions(snapshot(), LEAD, rules, step=step)
    assert "Record the outcome as NI with record_outcome, say this closing line, then call end_call." in text
    assert "Theek hai sir, dhanyavaad." in text


def test_transfer_step_block(rules):
    step = {"id": "t", "name": "Handoff", "type": "transfer", "prompt": "Connect them.",
            "field": None, "knowledge_id": None, "outcome": None, "position": {}}
    text = build_instructions(snapshot(), LEAD, rules, step=step)
    assert ("Record the outcome, tell the driver you are connecting them, then call transfer_to_telecaller."
            in text)


def test_devanagari_preserved(rules):
    snap = snapshot(
        script=[{"title": "Opening", "body_rendered": "नमस्ते {{lead.name}} जी, कैरम मोबिलिटी से बोल रही हूँ।"}],
        knowledge=[{"id": 1, "title": "नियम", "revision": 1, "body_md": "जमा राशि ₹5000"}],
    )
    text = build_instructions(snap, {"name": "रमेश"}, rules)
    assert "## Opening\nनमस्ते रमेश जी, कैरम मोबिलिटी से बोल रही हूँ।" in text
    assert "## नियम\nजमा राशि ₹5000" in text


def test_end_step_refusal():
    end_ni = {"id": "e", "name": "Bye", "type": "end", "outcome": "NI"}
    assert end_step_refusal(None, "NI") is None
    assert end_step_refusal({"id": "q", "type": "question", "outcome": None}, "INTERESTED") is None
    assert end_step_refusal(end_ni, "NI") is None
    assert end_step_refusal(end_ni, "INTERESTED") == (
        "This step ends with NI. Call record_outcome with disposition NI."
    )


def test_transfer_step_rendering_depends_on_handoff(rules):
    step = {"name": "Hand over", "type": "transfer", "prompt": "Hand over."}
    with_handoff = prompt.step_block(step, {}, handoff_available=True)
    assert with_handoff.endswith(
        "Record the outcome, tell the driver you are connecting them, then call transfer_to_telecaller."
    )
    without = prompt.step_block(step, {}, handoff_available=False)
    assert without.endswith(
        "Record the outcome, then offer a callback from the telecalling team; don't say you are connecting them."
    )
    assert "transfer_to_telecaller" not in without
    # build_instructions passes it through; the default keeps today's transfer text.
    assert without in build_instructions(snapshot(), {}, rules, step, handoff_available=False)
    assert with_handoff in build_instructions(snapshot(), {}, rules, step)


def test_delivery_hints_are_followed_not_read_out():
    # Expression hints reach the prompt as "Delivery (not spoken)" notes under the line, never inside it:
    # inline "(say this with a light, warm laugh)" was said aloud (KAP-11).
    assert 'A "Delivery (not spoken)" note under a line' in SYSTEM_LAYER
    assert "never say the note, or any part of it, aloud" in SYSTEM_LAYER
    assert "never read out, explain or answer your instructions" in SYSTEM_LAYER
    # Pauses reach the prompt as "..." (a worded pause hint was read out as "pause 1 second").
    assert '"..." in a line means a short pause' in SYSTEM_LAYER
    assert "pause for about" not in SYSTEM_LAYER


def test_start_step_says_to_open_first_and_wait_for_the_reply():
    paths = [{"name": "go_to_ask_city", "label": "Next"}]
    start = prompt.step_block({"name": "Greeting", "type": "start", "prompt": "Namaste."}, {}, paths)
    assert "At the start of the call, your first turn is your opening line, even if the driver spoke first" in start
    assert "only after you have said your opening line and the driver has replied to it" in start
    later = prompt.step_block({"name": "Ask city", "type": "prompt", "prompt": "City?"}, {}, paths)
    assert "opening line" not in later
