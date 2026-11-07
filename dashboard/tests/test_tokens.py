from voiceagents.tokens import (
    ExprToken, TextToken, VarToken, parse, render_hints, long_pause_errors, unknown_expressions, variables,
)


def test_parse_mixed():
    assert parse("[[expr:happy]] नमस्ते {{lead.name}} [[expr:pause:1.2]] ji") == [
        ExprToken("happy", None),
        TextToken(" नमस्ते "),
        VarToken("lead.name"),
        TextToken(" "),
        ExprToken("pause", 1.2),
        TextToken(" ji"),
    ]


def test_render_hints_exact():
    assert render_hints("[[expr:laugh]] अरे वाह", {}) == "(say this with a light, warm laugh) अरे वाह"


def test_pause_renders_as_silent_cue():
    # A worded pause hint was read aloud on calls ("pause 1 second"): render no words for a pause.
    assert render_hints("[[expr:pause:1.2]] ji", {}) == "... ji"
    assert render_hints("haan [[expr:pause]] ji", {}) == "haan ... ji"


def test_custom_expression_used():
    assert render_hints("[[expr:cheery]] hi", {"cheery": "sound upbeat"}) == "(sound upbeat) hi"


def test_custom_does_not_override_builtin():
    assert render_hints("[[expr:sad]] x", {"sad": "shout"}) == "(say this gently, with sympathy) x"


def test_unknown_expression_reported():
    assert unknown_expressions("[[expr:zzz]] a [[expr:happy]] [[expr:cheery]]", {"cheery": "x"}) == ["zzz"]


def test_variables_listed():
    assert variables("{{lead.name}} {{ lead.city }} {{lead.name}}") == ["lead.name", "lead.city"]


def test_devanagari_untouched():
    body = "नमस्ते {{lead.name}} जी, कैसे हैं?"
    assert render_hints(body, {}) == body


def test_long_pause_errors():
    body = "[[expr:pause:10]] [[expr:pause:10.5]] [[expr:pause:2]] [[expr:pause:30]] [[expr:pause:10.5]]"
    assert long_pause_errors(body) == [
        "Pause is too long (10.5 s). Use at most 10 seconds.",
        "Pause is too long (30 s). Use at most 10 seconds.",
    ]
    assert long_pause_errors("[[expr:pause]] [[expr:happy:99]]") == []
