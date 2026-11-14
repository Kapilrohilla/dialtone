import copy

import pytest

from tests.test_workflow_graph import driver_graph
from workflows import suggest
from workflows.graph import validate
from workflows.suggestions import (
    Invalid, fingerprint, strip_expressions, validate_answer, validate_expression,
)


def answer(**kw):
    p = {"label": "Not sure which licence", "examples": ["पता नहीं", "शायद yellow है", "not sure ji"],
         "reason": "callers often don't know their licence type.", "target": {"step_id": "e3"}}
    p.update(kw)
    return p


def new_step(**kw):
    n = {"name": "Explain licence types", "type": "prompt", "prompt": "[[expr:pause:0.6]] कोई बात नहीं जी।",
         "then": {"step_id": "s3", "label": "Explained licence types"}}
    n.update(kw)
    return {"new_step": n}


def reason(fn, *args, **kw):
    with pytest.raises(Invalid) as e:
        fn(*args, **kw)
    return e.value.reason


# -- answers -------------------------------------------------------------------------------------------

def test_valid_answer_is_cleaned():
    got = validate_answer(answer(label="  Not sure  ", examples=[" a ", "A", "b"]), driver_graph(), "s3")
    assert got == {"label": "Not sure", "examples": ["a", "b"], "reason": answer()["reason"],
                   "target": {"step_id": "e3"}}


def test_answer_label_rules():
    g = driver_graph()
    assert reason(validate_answer, answer(label=" "), g, "s3") == "Path name can't be empty."
    assert reason(validate_answer, answer(label="x" * 61), g, "s3") == "Keep path name to 60 characters."
    assert reason(validate_answer, answer(label="ELIGIBLE "), g, "s3") == \
        "A path with this name already exists. Rename it to accept."
    assert reason(validate_answer, answer(), g, "s3", taken_labels=["not sure which licence"]) == \
        "A path with this name already exists. Rename it to accept."


def test_answer_example_rules():
    g = driver_graph()
    assert reason(validate_answer, answer(examples=[]), g, "s3") == "Add at least one thing the caller might say."
    assert reason(validate_answer, answer(examples="x"), g, "s3") == "Caller phrases must be a list of text."
    assert reason(validate_answer, answer(examples=["a", ""]), g, "s3") == "A caller phrase is empty."
    assert reason(validate_answer, answer(examples=["x" * 41]), g, "s3") == "Keep each caller phrase to 40 characters."
    assert reason(validate_answer, answer(examples=list("abcdef")), g, "s3") == "Use at most 5 caller phrases."


def test_answer_source_and_target_rules():
    g = driver_graph()
    assert reason(validate_answer, answer(), g, "nope") == "The step this came from was removed."
    assert reason(validate_answer, answer(), g, "e1") == "Paths can't leave this kind of step."
    assert reason(validate_answer, answer(), g, "t1") == "Paths can't leave this kind of step."
    assert reason(validate_answer, answer(target={"step_id": "gone"}), g, "s3") == \
        "The step this pointed to was removed."
    assert reason(validate_answer, answer(target={"step_id": "s1"}), g, "s3") == \
        "A path can't lead to the start step."
    assert reason(validate_answer, answer(target={"step_id": "s3"}), g, "s3") == \
        "A path can't lead back to its own step."
    assert reason(validate_answer, answer(target={"step_id": "e2"}), g, "s3") == \
        "This step already goes there. Add the phrases to that path instead."
    assert reason(validate_answer, answer(target=None), g, "s3") == "Choose where this path goes."


def test_answer_with_a_new_step():
    g = driver_graph()
    got = validate_answer(answer(target=new_step()), g, "s3")
    assert got["target"]["new_step"]["then"] == {"step_id": "s3", "label": "Explained licence types"}
    end = validate_answer(answer(target=new_step(type="end", outcome="CBR", then=None)), g, "s3")
    assert end["target"] == {"new_step": {"name": "Explain licence types", "type": "end",
                                          "prompt": "[[expr:pause:0.6]] कोई बात नहीं जी।", "outcome": "CBR"}}
    assert reason(validate_answer, answer(target=new_step(name="Ask city")), g, "s3") == \
        "A step with this name already exists. Rename the new step."
    assert reason(validate_answer, answer(target=new_step(type="collect")), g, "s3") == \
        "A new step must say something or end the call."
    assert reason(validate_answer, answer(target=new_step(type="end", outcome="NOPE")), g, "s3") == \
        "Choose an outcome for the new end step."
    assert reason(validate_answer, answer(target=new_step(then={"step_id": "s1", "label": "x"})), g, "s3") == \
        "A path can't lead to the start step."
    assert reason(validate_answer, answer(target=new_step(prompt="[[expr:nope]] hi")), g, "s3") == \
        'Unknown expression "nope".'
    assert validate_answer(answer(target=new_step(prompt="[[expr:nope]] hi")), g, "s3", {"nope": "x"})


# -- expressions ---------------------------------------------------------------------------------------

def test_expression_may_only_add_tokens():
    g = driver_graph()
    before = g["steps"][0]["prompt"]  # "Namaste! [[expr:happy]] I am calling from Northwind."
    ok = {"before": before, "after": "[[expr:pause:0.6]] " + before, "reason": "warmer"}
    assert validate_expression(ok, g, "s1")["after"] == ok["after"]
    assert reason(validate_expression, {**ok, "after": "Namaste! I am calling from Northwind Car Rentals."}, g, "s1") == \
        "This would change the agent's words."
    assert reason(validate_expression, {**ok, "after": "Namaste! I am calling from Northwind."}, g, "s1") == \
        "This would remove an expression the step already has."
    assert reason(validate_expression, {**ok, "after": before}, g, "s1") == "This adds no expressions."
    assert reason(validate_expression, {**ok, "before": "old words"}, g, "s1") == \
        "The agent's words for this step have changed."
    assert reason(validate_expression, {**ok, "after": "[[expr:pause:11]] " + before}, g, "s1") == \
        "Pause is too long (11 s). Use at most 10 seconds."
    assert reason(validate_expression, {**ok, "after": "[[expr:pause:0.1]] " + before}, g, "s1") == \
        "Pause is too short (0.1 s). Use at least 0.2 seconds."
    assert reason(validate_expression, {**ok, "after": "[[expr:shout]] " + before}, g, "s1") == \
        'Unknown expression "shout".'
    assert reason(validate_expression, ok, g, "gone") == "The step this came from was removed."


def test_strip_expressions():
    assert strip_expressions("[[expr:sad]]  माफ़ कीजिए, [[expr:pause:0.6]] {{lead.city}}") == "माफ़ कीजिए, {{lead.city}}"


def test_fingerprint_tracks_the_step_and_its_paths():
    g = driver_graph()
    fp = fingerprint(g, "s3")
    assert fp == fingerprint(copy.deepcopy(g), "s3") and fingerprint(g, "gone") == ""
    moved = copy.deepcopy(g)
    moved["steps"][2]["position"] = {"x": 500, "y": 9}
    assert fingerprint(moved, "s3") == fp  # moving a card is not a change
    other = copy.deepcopy(g)
    other["steps"][3]["prompt"] = "changed"
    assert fingerprint(other, "s3") == fp  # another step changed
    for change in (lambda x: x["steps"][2].update(prompt="new words"),
                   lambda x: x["paths"][3].update(label="ok"),
                   lambda x: x["paths"][3].update(examples=["haan"])):
        h = copy.deepcopy(g)
        change(h)
        assert fingerprint(h, "s3") != fp


# -- generation ----------------------------------------------------------------------------------------

def test_steps_to_check_whole_workflow_and_step():
    g = driver_graph()
    ids, total = suggest.steps_to_check(g, "workflow", None, ["answers"])
    assert ids == ["s1", "s2", "s3", "s4"] and total == 4
    ids, total = suggest.steps_to_check(g, "workflow", None, ["expressions"])
    assert ids == ["s1", "s4"]
    big = {"steps": [{"id": f"x{i}", "name": f"X{i}", "type": "prompt", "prompt": "hi"} for i in range(25)], "paths": []}
    ids, total = suggest.steps_to_check(big, "workflow", None, ["answers"])
    assert len(ids) == 20 and total == 25
    assert suggest.steps_to_check(g, "step", "s3", ["answers"]) == (["s3"], 1)
    assert suggest.steps_to_check(g, "step", "e1", ["answers"]) == ([], 1)  # nothing to suggest for an end step


def test_drafts_from_keeps_only_valid_items():
    g = driver_graph()
    data = {
        "answers": [
            {"step_id": "s3", "label": "Not sure", "examples": ["पता नहीं", "x" * 50], "reason": "r",
             "target_step_id": "e3"},
            {"step_id": "s3", "label": "not sure", "examples": ["a"], "reason": "dup label", "target_step_id": "e4"},
            {"step_id": "s3", "label": "Applied", "examples": ["apply किया है"], "reason": "r",
             "new_step": {"name": "Licence applied", "type": "end", "prompt": "ठीक है", "outcome": "CBR"}},
            {"step_id": "s3", "label": "Applied 2", "examples": ["a"], "reason": "r",
             "new_step": {"name": "licence applied", "type": "end", "prompt": "", "outcome": "CBR"}},
            {"step_id": "s2", "label": "Not in batch", "examples": ["a"], "reason": "r", "target_step_id": "s4"},
            {"step_id": "e1", "label": "From an end", "examples": ["a"], "reason": "r", "target_step_id": "s4"},
            "garbage",
        ],
        "expressions": [
            {"step_id": "s4", "after": "[[expr:happy]] Here is the plan.", "reason": "warm"},
            {"step_id": "s4", "after": "[[expr:sad]] Here is the plan.", "reason": "second for the step"},
            {"step_id": "s3", "after": "anything", "reason": "s3 says nothing"},
        ],
    }
    items = suggest.drafts_from(data, g, ["s3", "s4", "e1"], ["answers", "expressions"], {}, {}, set())
    assert [(k, sid, p.get("label") or p.get("after")) for k, sid, p in items] == [
        ("answer", "s3", "Not sure"), ("answer", "s3", "Applied"), ("expression", "s4", "[[expr:happy]] Here is the plan.")]
    assert items[0][2]["examples"] == ["पता नहीं"]
    assert items[1][2]["target"]["new_step"]["outcome"] == "CBR"
    assert items[2][2]["before"] == "Here is the plan."
    only_answers = suggest.drafts_from(data, g, ["s3", "s4"], ["answers"], {}, {}, set())
    assert all(k == "answer" for k, _, _ in only_answers)


def test_at_most_five_answers_per_step():
    g = driver_graph()
    data = {"answers": [{"step_id": "s3", "label": f"A{i}", "examples": ["a"], "reason": "r",
                         "target_step_id": t} for i, t in enumerate(["e1", "e3", "e4", "t1", "s2", "x"])],
            "expressions": []}
    data["answers"] += [{"step_id": "s3", "label": f"B{i}", "examples": ["a"], "reason": "r",
                         "new_step": {"name": f"N{i}", "type": "end", "prompt": "", "outcome": "NI"}} for i in range(3)]
    assert len(suggest.drafts_from(data, g, ["s3"], ["answers"], {}, {}, set())) == 5


def test_accepting_every_answer_keeps_the_graph_valid():
    """Mirrors the console's applySuggestion: accepted answers make a graph that passes graph.validate."""
    g = driver_graph()
    data = {"answers": [
        {"step_id": "s3", "label": "Not sure", "examples": ["पता नहीं"], "reason": "r",
         "new_step": {"name": "Explain licence types", "type": "prompt", "prompt": "[[expr:pause:0.6]] ठीक है",
                      "then_step_id": "s3", "then_label": "Explained"}},
        {"step_id": "s3", "label": "Applied", "examples": ["apply किया है"], "reason": "r", "target_step_id": "e4"},
    ], "expressions": []}
    for i, (_, sid, p) in enumerate(suggest.drafts_from(data, g, ["s3"], ["answers"], {}, {}, set())):
        target = p["target"]
        if "new_step" in target:
            n = target["new_step"]
            nid = f"new{i}"
            g["steps"].append({"id": nid, "name": n["name"], "type": n["type"], "prompt": n["prompt"]})
            g["paths"].append({"id": f"pn{i}", "from": nid, "to": n["then"]["step_id"], "label": n["then"]["label"]})
            to = nid
        else:
            to = target["step_id"]
        g["paths"].append({"id": f"pa{i}", "from": sid, "to": to, "label": p["label"], "examples": p["examples"]})
    assert validate(g, set()) == []
