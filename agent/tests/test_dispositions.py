"""Per-agent disposition lists (KAP-46): what the AI reads and what record_outcome accepts."""
import json

import agent
import dispositions
import prompt
import simulate
from report import build_report
from tests.test_runtime_wiring import GRAPH, LEAD, console, snapshot

LOANS = {
    "id": 3, "name": "Loan leads", "fallback": "UNRESOLVED", "not_reached": "NO_ANSWER", "dropped": "UNRESOLVED",
    "items": [
        {"code": "INTERESTED", "name": "Interested", "description": "Wants the loan.", "group": "Interested",
         "fields": [{"key": "amount", "label": "Loan amount", "type": "number", "required": True}]},
        {"code": "LATER", "name": "Call back requested", "description": "Asked to talk later.", "group": "Call back",
         "fields": [{"key": "callback_time", "label": "Callback time", "type": "datetime", "required": False}]},
        {"code": "NO_ANSWER", "name": "Not reached", "description": "No one answered.", "group": "Not reached",
         "fields": []},
        {"code": "UNRESOLVED", "name": "No clear outcome", "description": "Unclear.", "group": "Dropped",
         "fields": []},
    ],
}


def loan_agent(**snap):
    return agent.PhoneAgent(LEAD, agent.GEMINI_LANGUAGE_RULES, console(snapshot(dispositions=LOANS, **snap)))


def test_for_snapshot():
    assert dispositions.for_snapshot(None)["fallback"] == "UNRESOLVED"
    assert dispositions.codes(dispositions.for_snapshot({"script": []})) == list(prompt.DISPOSITIONS)
    assert dispositions.for_snapshot({"dispositions": None}) is None
    assert dispositions.for_snapshot({"dispositions": LOANS})["not_reached"] == "NO_ANSWER"
    assert dispositions.LEGACY["not_reached"] == "NOT_CONNECTED" and dispositions.LEGACY["dropped"] == "CDRP"


def test_parse_fields():
    assert dispositions.parse_fields('{"amount": 50000, "x": ""}') == {"amount": "50000"}
    assert dispositions.parse_fields("amount=50000; callback_time: 6 pm") == {"amount": "50000",
                                                                              "callback_time": "6 pm"}
    assert dispositions.parse_fields("") == {} and dispositions.parse_fields("[1]") == {}


def test_the_ai_reads_only_its_list():
    text = agent.PhoneAgent(LEAD, cfg=console(snapshot(dispositions=LOANS))).instructions
    assert "- LATER: Call back requested. Asked to talk later." in text
    assert "Capture in `fields`: Loan amount as `amount` (required)." in text
    assert "use UNRESOLVED; don't guess" in text
    assert "NOT_CONNECTED" not in text and "stays CBR" not in text
    none = agent.PhoneAgent(LEAD, cfg=console(snapshot(dispositions=None))).instructions
    assert "Dispositions: this agent records none." in none


async def test_record_outcome_takes_only_list_codes_and_required_fields():
    a = loan_agent()
    refused = await a.record_outcome(disposition="CBR", reason="r", summary="s")
    assert refused.startswith("CBR isn't one of your dispositions. Use one of: INTERESTED, LATER")
    assert a.outcome is None
    refused = await a.record_outcome(disposition="INTERESTED", reason="r", summary="s")
    assert refused.startswith("INTERESTED needs Loan amount (`amount`)")
    ok = await a.record_outcome(disposition="interested", reason="r", summary="s", fields='{"amount": "2 lakh"}')
    assert ok == "Recorded. Now say your closing line."
    assert a.outcome["disposition"] == "INTERESTED" and a.outcome["fields"] == {"amount": "2 lakh"}
    await a.record_outcome(disposition="LATER", reason="r", summary="s", callback_time="6 pm")
    assert a.outcome["fields"] == {"callback_time": "6 pm"}


async def test_no_list_records_no_disposition():
    a = agent.PhoneAgent(LEAD, cfg=console(snapshot(dispositions=None)))
    assert await a.record_outcome(disposition="INTERESTED", reason="r", summary="s") == (
        "Recorded. Now say your closing line.")
    assert a.outcome["disposition"] == "" and a.system_code("not_reached") == ""


async def _at_end_step(a):
    for name, args in (("go_to_city", {}), ("go_to_wrap_up", {"value": "Pune"})):
        await next(t for t in a.tools if getattr(t, "id", None) == name)(args)


async def test_end_step_outcome_enforced_only_when_in_the_list():
    a = loan_agent(workflow={"id": 1, "graph": GRAPH})  # the end step ends with INTERESTED, which is in the list
    await _at_end_step(a)
    assert (await a.record_outcome(disposition="LATER", reason="r", summary="s")).startswith("This step ends with")
    no_interested = {**LOANS, "items": LOANS["items"][1:]}
    b = agent.PhoneAgent(LEAD, cfg=console(snapshot(dispositions=no_interested, workflow={"id": 1, "graph": GRAPH})))
    await _at_end_step(b)
    assert await b.record_outcome(disposition="LATER", reason="r", summary="s") == (
        "Recorded. Now say your closing line.")


def test_system_codes_follow_the_list():
    a = loan_agent()
    assert (a.system_code("not_reached"), a.system_code("dropped"), a.system_code("fallback")) == (
        "NO_ANSWER", "UNRESOLVED", "UNRESOLVED")
    assert agent.PhoneAgent.system_outcome({"disposition": "NO_ANSWER"})["set_by"] == "system"


def test_report_carries_the_list_when_asked():
    args = dict(room="r", outcome={"disposition": "LATER"}, mood=None, timeline=[], dead_air=[], latency={},
                behavior=None, turns=None)
    assert "dispositions" not in build_report(**args)
    assert build_report(**args, dispositions=(True, LOANS))["dispositions"] == LOANS
    assert build_report(**args, dispositions=(True, None))["dispositions"] is None


def test_simulation_uses_the_list():
    sim = simulate.Simulation(snapshot(dispositions=LOANS), {}, None)
    schema = sim.record_outcome_schema()["parameters"]["properties"]
    assert schema["disposition"]["enum"] == ["INTERESTED", "LATER", "NO_ANSWER", "UNRESOLVED"]
    assert sim.record_outcome({"disposition": "NI", "reason": "r", "summary": "s"}).startswith("NI isn't one")
    assert sim.record_outcome({"disposition": "LATER", "reason": "r", "summary": "s",
                               "fields": json.dumps({"callback_time": "6 pm"}), "set_by": "system"}) == (
        "Recorded. Now say your closing line.")
    assert sim.outcome["fields"] == {"callback_time": "6 pm"} and "set_by" not in sim.outcome
    none = simulate.Simulation(snapshot(dispositions=None), {}, None)
    none.record_outcome({"disposition": "LATER", "reason": "r", "summary": "s"})
    assert none.outcome["disposition"] == ""
