import copy

from workflow import WorkflowRun


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


def loop_graph():
    return {
        "steps": [step("a", "A", "start"), step("b", "B", "prompt"), step("z", "Z", "end", outcome="NI")],
        "paths": [path("1", "a", "b", "go"), path("2", "b", "a", "back"), path("3", "b", "z", "done")],
    }


def test_driver_onboarding_happy_path():
    run = WorkflowRun(driver_graph())
    assert run.start().name == "Greeting"
    assert [p.name for p in run.paths_from_current()] == ["go_to_ask_city"]
    t = run.take("go_to_ask_city")
    assert t.ok and t.entered.name == "Ask city" and not t.capped
    assert [p.takes_value for p in run.paths_from_current()] == [True, True]
    t = run.take("go_to_ask_licence_and_experience", "Delhi")
    assert t.ok and t.captured == ("city", "Delhi")
    run.take("go_to_explain_the_plan", "yes")
    t = run.take("go_to_end_interested")
    assert t.ok and run.current.type == "end" and run.current.outcome == "INTERESTED"
    assert run.path == ["Greeting", "Ask city", "Ask licence and experience", "Explain the plan",
                        "End: interested"]
    assert run.captured == {"city": "Delhi", "licence": "yes"}


def test_tool_names_slugged_and_unique():
    g = {
        "steps": [step("a", "Start", "start"), step("b", "नमस्ते", "end", outcome="NI"),
                  step("c", "Done!", "end", outcome="NI"), step("d", "done", "end", outcome="NI"),
                  step("e", "x" * 80, "end", outcome="NI")],
        "paths": [path("1", "a", "b", "l1"), path("2", "a", "c", "l2"), path("3", "a", "d", "l3"),
                  path("4", "a", "e", "l4")],
    }
    run = WorkflowRun(g)
    run.start()
    names = [p.name for p in run.paths_from_current()]
    assert names[0] == "go_to_step_b"
    assert names[1] == "go_to_done"
    assert names[2] == "go_to_done_2"
    assert len(names[3]) <= 48 and len(set(names)) == 4
    import re
    assert all(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", n) for n in names)


def test_unknown_path_refused():
    run = WorkflowRun(driver_graph())
    run.start()
    t = run.take("go_to_nowhere")
    assert not t.ok and t.message == "That path isn't available from Greeting."
    assert run.current.name == "Greeting"


def test_collect_requires_value_and_captures():
    run = WorkflowRun(driver_graph())
    run.start()
    run.take("go_to_ask_city")
    t = run.take("go_to_ask_licence_and_experience")
    assert not t.ok and t.message == "Say what the driver answered in `value`."
    assert run.current.name == "Ask city" and run.captured == {}
    t = run.take("go_to_ask_licence_and_experience", "  ")
    assert not t.ok
    t = run.take("go_to_ask_licence_and_experience", "Pune")
    assert t.ok and run.captured == {"city": "Pune"}


def test_visit_cap_forces_close():
    run = WorkflowRun(loop_graph())
    run.start()
    assert run.take("go_to_b").ok  # B1
    assert run.take("go_to_a").ok  # A2
    assert run.take("go_to_b").ok  # B2
    assert run.take("go_to_a").ok  # A3
    assert run.take("go_to_b").ok  # B3
    t = run.take("go_to_a")  # A4 would exceed
    assert t.capped and not t.ok and t.entered is None
    assert "UNRESOLVED" in t.message and "workflow loop limit reached" in t.message
    assert run.current.name == "B"


def test_transition_cap():
    run = WorkflowRun(loop_graph(), max_visits=100, max_transitions=4)
    run.start()
    for tool in ["go_to_b", "go_to_a", "go_to_b", "go_to_a"]:
        assert run.take(tool).ok
    t = run.take("go_to_b")
    assert t.capped and run.current.name == "A"


def test_end_step_has_no_paths():
    run = WorkflowRun(driver_graph())
    run.start()
    run.take("go_to_ask_city")
    run.take("go_to_end_not_in_your_city", "Mumbai")
    assert run.current.type == "end"
    assert run.paths_from_current() == []
    assert not run.take("go_to_ask_city").ok


def test_transfer_leaf_and_fallback_path():
    run = WorkflowRun(driver_graph())
    run.start()
    run.take("go_to_ask_city")
    run.take("go_to_ask_licence_and_experience", "x")
    run.take("go_to_explain_the_plan", "y")
    run.take("go_to_transfer_to_a_telecaller")
    assert run.current.type == "transfer" and run.paths_from_current() == []
    g = driver_graph()
    g["paths"].append(path("p9", "t1", "e4", "transfer failed"))
    run = WorkflowRun(g)
    run.start()
    run.take("go_to_ask_city")
    run.take("go_to_ask_licence_and_experience", "x")
    run.take("go_to_explain_the_plan", "y")
    run.take("go_to_transfer_to_a_telecaller")
    ps = run.paths_from_current()
    assert [p.description for p in ps] == ["transfer failed"] and not ps[0].takes_value
    assert run.take(ps[0].name).entered.name == "Schedule a call back"


def test_graph_without_start_returns_none():
    g = driver_graph()
    g["steps"] = [s for s in g["steps"] if s["type"] != "start"]
    run = WorkflowRun(g)
    assert run.start() is None
    assert run.paths_from_current() == []
    for bad in [None, [], "x", {}, {"steps": "x", "paths": 5}, {"steps": [1, None], "paths": [None]}]:
        r = WorkflowRun(copy.deepcopy(bad))
        assert r.start() is None
        assert not r.take("go_to_x").ok


def test_state_round_trip():
    run = WorkflowRun(driver_graph())
    run.start()
    run.take("go_to_ask_city")
    run.take("go_to_ask_licence_and_experience", "Delhi")
    state = run.to_state()
    assert state["current_step_id"] == "s3" and state["transitions"] == 2
    assert state["visits"] == {"s1": 1, "s2": 1, "s3": 1} and state["captured"] == {"city": "Delhi"}
    again = WorkflowRun.from_state(driver_graph(), state)
    assert again.current.id == "s3" and again.to_state() == state
    assert again.take("go_to_explain_the_plan", "yes").ok
    assert again.captured == {"city": "Delhi", "licence": "yes"}


def test_from_state_none_starts_fresh():
    run = WorkflowRun.from_state(driver_graph(), None)
    assert run.current.name == "Greeting" and run.path == ["Greeting"]
    assert run.to_state()["visits"] == {"s1": 1} and run.to_state()["transitions"] == 0


def test_unhashable_path_endpoints_never_raise():
    g = driver_graph()
    g["paths"] += [{"from": [], "to": "s1", "label": "x"}, {"from": "s1", "to": {}, "label": "y"},
                   {"from": {}, "to": [], "label": "z"}]
    run = WorkflowRun(g)
    run.start()
    assert [p.name for p in run.paths_from_current()] == ["go_to_ask_city"]


def test_tampered_state_never_raises():
    for bad_id in [[], {}, 5, None, "nope"]:
        run = WorkflowRun.from_state(driver_graph(), {"current_step_id": bad_id})
        assert run.current.name == "Greeting"
    for bad in ["x", 5, [], {"current_step_id": "s1", "visits": [1], "transitions": "9", "captured": [1],
                             "path": "abc"}]:
        run = WorkflowRun.from_state(driver_graph(), bad)
        assert run.current is not None and run.take("go_to_ask_city").ok
    run = WorkflowRun.from_state(loop_graph(), {
        "current_step_id": "a", "visits": {"a": -50, "b": True, 3: 1}, "transitions": -10,
        "captured": {"k": 1}, "path": ["A"] + [7] * 5 + ["B"] * 100})
    assert run.visits == {"a": 0, "b": 0} and run.transitions == 0 and run.captured == {}
    assert len(run.path) <= 26 and all(isinstance(x, str) for x in run.path)
    for tool in ["go_to_b", "go_to_a", "go_to_b", "go_to_a", "go_to_b"]:
        assert run.take(tool).ok
    assert run.take("go_to_a").capped
    run = WorkflowRun.from_state(loop_graph(), {"current_step_id": "a", "transitions": True}, max_transitions=2)
    assert run.transitions == 0


def test_duplicate_paths_same_target_single_tool():
    g = driver_graph()
    g["paths"].append(path("p9", "s1", "s2", "again"))
    run = WorkflowRun(g)
    run.start()
    ps = run.paths_from_current()
    assert len(ps) == 1 and ps[0].description == "next"
