import copy

from workflows.graph import validate


def step(id, name, type, **kw):
    s = {"id": id, "name": name, "type": type, "prompt": "", "field": None, "knowledge_id": None,
         "outcome": None, "position": {"x": 0, "y": 0}}
    s.update(kw)
    return s


def path(id, a, b, label):
    return {"id": id, "from": a, "to": b, "label": label}


def driver_graph():
    return {
        "steps": [
            step("s1", "Greeting", "start", prompt="Namaste! [[expr:happy]] I am calling from Carrum."),
            step("s2", "Ask city", "collect", field="city"),
            step("s3", "Ask licence and experience", "collect", field="licence"),
            step("s4", "Explain the plan", "prompt", prompt="Here is the plan."),
            step("e1", "End: not in your city", "end", outcome="NE"),
            step("e2", "End: not eligible", "end", outcome="NE"),
            step("e3", "End: interested", "end", outcome="INTERESTED"),
            step("e4", "Schedule a call back", "end", outcome="CBR"),
            step("t1", "Transfer to a telecaller", "transfer"),
        ],
        "paths": [
            path("p1", "s1", "s2", "next"),
            path("p2", "s2", "s3", "in city"),
            path("p3", "s2", "e1", "other city"),
            path("p4", "s3", "s4", "eligible"),
            path("p5", "s3", "e2", "not eligible"),
            path("p6", "s4", "e3", "interested"),
            path("p7", "s4", "e4", "call me later"),
            path("p8", "s4", "t1", "talk to a person"),
        ],
    }


def test_valid_driver_onboarding_graph():
    assert validate(driver_graph(), set()) == []


def test_two_starts():
    g = driver_graph()
    g["steps"].append(step("s9", "Second hello", "start"))
    g["paths"].append(path("p9", "s9", "s2", "next"))
    assert 'A workflow needs exactly one start step; found 2.' in validate(g, set())


def test_no_start():
    g = driver_graph()
    g["steps"] = [s for s in g["steps"] if s["type"] != "start"]
    g["paths"] = [p for p in g["paths"] if p["from"] != "s1"]
    assert 'A workflow needs exactly one start step; found 0.' in validate(g, set())


def test_duplicate_ids():
    g = driver_graph()
    g["steps"].append(step("s2", "Another", "end", outcome="NI"))
    assert 'Two steps share the id "s2". Step ids must be unique.' in validate(g, set())


def test_dangling_path():
    g = driver_graph()
    g["paths"].append(path("p9", "s4", "nope", "extra"))
    assert 'The path "extra" leaving "Explain the plan" points to a step that does not exist.' in validate(g, set())


def test_dead_end_step():
    g = driver_graph()
    g["paths"] = [p for p in g["paths"] if p["from"] != "s4"]
    errs = validate(g, set())
    assert 'Step "Explain the plan" has no way out. Add a path or make it an end step.' in errs


def test_transfer_may_have_no_paths():
    assert not any("Transfer" in e for e in validate(driver_graph(), set()))


def test_transfer_with_invalid_outcome():
    g = driver_graph()
    g["steps"][-1]["outcome"] = "BOGUS"
    assert 'Step "Transfer to a telecaller" has an unknown outcome "BOGUS".' in validate(g, set())


def test_end_without_outcome():
    g = driver_graph()
    g["steps"][4]["outcome"] = None
    assert 'End step "End: not in your city" needs an outcome.' in validate(g, set())


def test_end_with_unknown_outcome():
    g = driver_graph()
    g["steps"][4]["outcome"] = "MAYBE"
    assert 'End step "End: not in your city" has an unknown outcome "MAYBE".' in validate(g, set())


def test_end_with_outgoing_path():
    g = driver_graph()
    g["paths"].append(path("p9", "e3", "s2", "again"))
    assert 'End step "End: interested" cannot have paths leaving it.' in validate(g, set())


def test_unreachable_step():
    g = driver_graph()
    g["steps"].append(step("s9", "Lonely step", "end", outcome="NI"))
    assert 'Step "Lonely step" can never be reached from the start step.' in validate(g, set())


def test_bad_collect_field():
    g = driver_graph()
    g["steps"][1]["field"] = "City Name"
    msg = ('Step "Ask city" needs a field name: lowercase letters, digits and underscores, '
           'starting with a letter (up to 32 characters).')
    assert msg in validate(g, set())
    g["steps"][1]["field"] = None
    assert msg in validate(g, set())


def test_unknown_expression_in_prompt():
    g = driver_graph()
    g["steps"][0]["prompt"] = "Hello [[expr:shout]]"
    assert 'Step "Greeting" uses an unknown expression "shout".' in validate(g, set())
    assert validate(g, set(), {"shout": "loudly"}) == []


def test_long_pause_in_prompt():
    g = driver_graph()
    g["steps"][0]["prompt"] = "Hello [[expr:pause:12]]"
    assert 'Step "Greeting": Pause is too long (12 s). Use at most 10 seconds.' in validate(g, set())
    g["steps"][0]["prompt"] = "Hello [[expr:pause:10]]"
    assert validate(g, set()) == []


def test_missing_knowledge_id():
    g = driver_graph()
    g["steps"].append(step("k1", "Look up FAQ", "knowledge", knowledge_id=99))
    g["paths"] += [path("p9", "s4", "k1", "question"), path("p10", "k1", "e3", "done")]
    assert 'Step "Look up FAQ" refers to a knowledge document that does not exist.' in validate(g, {1})
    assert validate(g, {99}) == []


def test_knowledge_step_without_document():
    g = driver_graph()
    g["steps"].append(step("k1", "Look up FAQ", "knowledge"))
    g["paths"] += [path("p9", "s4", "k1", "question"), path("p10", "k1", "e3", "done")]
    assert 'Step "Look up FAQ" needs a knowledge document.' in validate(g, set())


def test_path_labels():
    g = driver_graph()
    g["paths"][2]["label"] = " "
    g["paths"][1]["label"] = "dup"
    g["paths"][2]["from"] = "s2"
    g["paths"].append(path("p9", "s2", "e2", "dup"))
    errs = validate(g, set())
    assert 'A path leaving "Ask city" has no label.' in errs
    assert 'Step "Ask city" has two paths labelled "dup". Labels must be different.' in errs


def test_malformed_input_never_raises():
    for bad in [None, [], "x", {}, {"steps": "x"}, {"steps": [1, None], "paths": 5},
                {"steps": [{"name": "no id"}], "paths": []},
                {"steps": [{"id": "a", "type": "wat"}], "paths": [None, {"from": "a"}]},
                {"steps": [{"id": ["l"], "type": "start"}], "paths": []}]:
        errs = validate(copy.deepcopy(bad), set())
        assert errs and all(isinstance(e, str) for e in errs)


def test_unhashable_and_nonstring_values_never_raise():
    def g(**kw):
        return {"steps": [step("a", "A", "start"), step("b", "B", "end", outcome="NI"), step("c", "C", "collect"),
                          step("k", "K", "knowledge"), step("t", "T", "transfer")], "paths": []}, kw
    for field, vals in [("type", [[], {}, 5]), ("outcome", [[], {}, 5]), ("knowledge_id", [[], {}, "1", True]),
                        ("name", [[], {}, None, 5]), ("field", [[], {}, 5]), ("prompt", [[], {}, 5])]:
        for v in vals:
            for i in range(5):
                graph, _ = g()
                graph["steps"][i][field] = v
                graph["paths"] = [{"id": "p", "from": "a", "to": "b", "label": v}, {"from": v, "to": v, "label": v}]
                errs = validate(graph, {1})
                assert errs and all(isinstance(e, str) for e in errs)


def test_unknown_type_and_missing_id_messages():
    errs = validate({"steps": [{"id": "a", "name": "Odd", "type": "wat"}, {"name": "No id", "type": "end"}],
                     "paths": []}, set())
    assert 'Step "Odd" has an unknown type "wat".' in errs
    assert 'A step is missing its id.' in errs
