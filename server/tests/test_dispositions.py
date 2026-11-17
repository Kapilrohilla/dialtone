"""Disposition lists per agent (KAP-46): the lists API, the agent link and snapshot, report ingest, a
person's change with history, the calls filter and the call.disposition webhook."""
import copy
import hashlib
import hmac
import json
from importlib import import_module

import pytest
from django.apps import apps as django_apps

from calls import webhooks
from calls.dispositions import apply_report
from calls.models import Call, CallReport, DispositionChange
from dispositions.lists import LEGACY, legacy_snapshot
from dispositions.models import DispositionList
from tests.test_publish import make_agent, make_user, make_workflow
from tests.test_report import make_report, post
from voiceagents.models import AgentVersion
from voiceagents.publish import PublishError, build_snapshot, is_outdated, publish

pytestmark = pytest.mark.django_db

ITEMS = [
    {"code": "INTERESTED", "name": "Interested", "description": "Wants the loan.", "group": "Interested",
     "fields": []},
    {"code": "CBR", "name": "Call back requested", "description": "Asked to talk later.", "group": "Call back",
     "fields": [{"key": "callback_time", "label": "Callback time", "type": "datetime", "required": True}]},
    {"code": "NOT_CONNECTED", "name": "Not reached", "description": "No answer.", "group": "Not reached",
     "fields": []},
    {"code": "UNRESOLVED", "name": "No clear outcome", "description": "Unclear.", "group": "Dropped", "fields": []},
]


def make_list(workspace, name="Loan leads", items=None, fallback="UNRESOLVED"):
    return DispositionList.objects.create(workspace=workspace, name=name, items=copy.deepcopy(items or ITEMS),
                                          fallback_code=fallback)


def make_version(workspace, lst):
    agent = make_agent(workspace, disposition_list=lst)
    return AgentVersion.objects.create(agent=agent, number=1, snapshot=build_snapshot(agent, 1))


# --- lists API --------------------------------------------------------------------------------------

def test_create_get_patch_list(member, workspace):
    c = member("editor")
    r = c.post("/api/dispositions", {"name": " Loan leads ", "items": ITEMS, "fallback_code": "UNRESOLVED"},
               format="json")
    assert r.status_code == 201, r.data
    body = r.data
    assert body["name"] == "Loan leads" and len(body["items"]) == 4 and body["used_by"] == []
    assert body["not_reached_code"] == "NOT_CONNECTED" and body["dropped_code"] == "UNRESOLVED"
    assert body["updated_by"] == "editor1@example.com"

    items = [{**ITEMS[0], "code": "interested"}, *ITEMS[1:]]  # codes are uppercased
    r = c.patch(f"/api/dispositions/{body['id']}", {"items": items}, format="json")
    assert r.status_code == 200 and r.data["items"][0]["code"] == "INTERESTED"
    rows = c.get("/api/dispositions").data
    assert [row["name"] for row in rows] == ["Loan leads"]


@pytest.mark.parametrize("payload, field", [
    ({"items": ITEMS + [ITEMS[0]]}, "items"),  # duplicate code
    ({"items": [{**ITEMS[0], "group": "Maybe"}]}, "items"),
    ({"items": [{**ITEMS[0], "code": "1BAD"}]}, "items"),
    ({"items": [{**ITEMS[1], "fields": [{"key": "Bad Key", "label": "x", "type": "text"}]}]}, "items"),
    ({"items": []}, "items"),
    ({"fallback_code": "NOPE"}, "fallback_code"),
    ({"name": "  "}, "name"),
])
def test_list_validation(member, workspace, payload, field):
    lst = make_list(workspace)
    r = member("editor").patch(f"/api/dispositions/{lst.pk}", payload, format="json")
    assert r.status_code == 400 and field in r.data


def test_removing_the_fallback_item_is_refused(member, workspace):
    lst = make_list(workspace)
    r = member("editor").patch(f"/api/dispositions/{lst.pk}", {"items": ITEMS[:3]}, format="json")
    assert r.status_code == 400 and "fallback_code" in r.data


def test_viewer_cannot_write_and_lists_are_isolated(member, workspace, other_workspace):
    lst = make_list(workspace)
    theirs = make_list(other_workspace)
    viewer = member("viewer")
    assert viewer.get(f"/api/dispositions/{lst.pk}").status_code == 200
    assert viewer.patch(f"/api/dispositions/{lst.pk}", {"name": "x"}, format="json").status_code == 403
    assert member("editor").get(f"/api/dispositions/{theirs.pk}").status_code == 404


def test_delete_refused_while_used_and_duplicate(member, workspace):
    lst = make_list(workspace)
    agent = make_agent(workspace, name="Loan follow-up", disposition_list=lst)
    c = member("editor")
    r = c.delete(f"/api/dispositions/{lst.pk}")
    assert r.status_code == 409 and "Loan follow-up" in r.data["detail"]
    copy_ = c.post(f"/api/dispositions/{lst.pk}/duplicate").data
    assert copy_["name"] == "Copy of Loan leads" and copy_["items"] == lst.items
    agent.disposition_list = None
    agent.save()
    assert c.delete(f"/api/dispositions/{lst.pk}").status_code == 204


# --- agent link, snapshot, publish ------------------------------------------------------------------

def test_attach_list_to_agent(member, workspace, other_workspace):
    lst = make_list(workspace)
    agent = make_agent(workspace)
    c = member("editor")
    r = c.patch(f"/api/agents/{agent.pk}", {"disposition_list": lst.pk}, format="json")
    assert r.status_code == 200 and r.data["disposition_list"] == lst.pk
    assert c.get(f"/api/dispositions/{lst.pk}").data["used_by"] == [{"id": agent.pk, "name": agent.name}]
    theirs = make_list(other_workspace)
    r = c.patch(f"/api/agents/{agent.pk}", {"disposition_list": theirs.pk}, format="json")
    assert r.status_code == 400 and "disposition_list" in r.data
    r = c.patch(f"/api/agents/{agent.pk}", {"disposition_list": None}, format="json")
    assert r.data["disposition_list"] is None


def test_snapshot_carries_the_list_or_none(workspace):
    lst = make_list(workspace)
    snap = build_snapshot(make_agent(workspace, disposition_list=lst), 1)["dispositions"]
    assert snap["name"] == "Loan leads" and [i["code"] for i in snap["items"]] == [i["code"] for i in ITEMS]
    assert (snap["fallback"], snap["not_reached"], snap["dropped"]) == ("UNRESOLVED", "NOT_CONNECTED", "UNRESOLVED")
    assert build_snapshot(make_agent(workspace, name="No list"), 1)["dispositions"] is None


def test_list_edit_makes_published_agent_outdated(workspace):
    lst = make_list(workspace)
    agent = make_agent(workspace, disposition_list=lst)
    publish(agent, make_user())
    agent.refresh_from_db()
    assert not is_outdated(agent)
    lst.items = [*lst.items, {**ITEMS[0], "code": "NI", "name": "Not interested", "group": "Not interested"}]
    lst.save()
    agent.refresh_from_db()
    assert is_outdated(agent)


def test_old_snapshot_matches_migrated_driver_hiring_list(workspace):
    """Agents published before lists keep running the built-in codes; the migrated list has the same codes, so
    they don't show as having unpublished changes."""
    lst = make_list(workspace, "Driver hiring", LEGACY["items"], LEGACY["fallback_code"])
    agent = make_agent(workspace, disposition_list=lst)
    publish(agent, make_user())
    agent.refresh_from_db()
    version = agent.published_version
    del version.snapshot["dispositions"]
    version.save()
    agent.refresh_from_db()
    assert not is_outdated(agent)


def test_publish_refuses_end_step_outcome_outside_list(workspace):
    lst = make_list(workspace, items=[ITEMS[3]])
    agent = make_agent(workspace, disposition_list=lst, workflow=make_workflow(workspace))
    with pytest.raises(PublishError) as e:
        publish(agent, make_user())
    assert any("isn't in the disposition list" in err for err in e.value.errors)


def test_migration_seeds_driver_hiring_list_and_attaches_it(workspace):
    agent = make_agent(workspace)
    seed = import_module("dispositions.migrations.0002_driver_hiring_list").seed
    seed(django_apps, None)
    agent.refresh_from_db()
    lst = agent.disposition_list
    assert lst.name == "Driver hiring" and len(lst.items) == 14 and lst.fallback_code == "UNRESOLVED"


# --- report ingest ----------------------------------------------------------------------------------

def report_for(version, disposition, **outcome):
    return make_report(room="call-d", agent_version_id=version.pk if version else None, disposition=disposition,
                       outcome={"disposition": disposition, "reason": "said so", **outcome})


def test_report_sets_ai_disposition_with_fields(client, workspace):
    version = make_version(workspace, make_list(workspace))
    assert post(client, report_for(version, "CBR", callback_time="today 6 pm")).status_code == 200
    call = Call.objects.get(room="call-d")
    assert (call.disposition_code, call.disposition_group, call.disposition_source) == ("CBR", "Call back", "ai")
    assert call.disposition_fields == {"callback_time": "today 6 pm"} and call.needs_person
    assert list(call.disposition_changes.values_list("source", "code")) == [("ai", "CBR")]


def test_code_outside_the_list_stores_the_fallback(client, workspace):
    version = make_version(workspace, make_list(workspace))
    post(client, report_for(version, "NI"))
    call = Call.objects.get(room="call-d")
    assert (call.disposition_code, call.disposition_source) == ("UNRESOLVED", "system")
    assert call.disposition_reason == "The AI picked NI, which isn't in the list."


def test_system_set_code(client, workspace):
    version = make_version(workspace, make_list(workspace))
    post(client, report_for(version, "NOT_CONNECTED", set_by="system"))
    assert Call.objects.get(room="call-d").disposition_source == "system"


def test_no_list_means_no_disposition(client, workspace):
    version = make_version(workspace, None)
    post(client, report_for(version, "INTERESTED"))
    call = Call.objects.get(room="call-d")
    assert call.disposition_code == "" and not call.disposition_changes.exists()


def test_voice_test_report_uses_the_list_it_ran_with(client, workspace):
    lst = build_snapshot(make_agent(workspace, disposition_list=make_list(workspace)), 0)["dispositions"]
    post(client, {**report_for(None, "INTERESTED"), "dispositions": lst})
    assert Call.objects.get(room="call-d").disposition_code == "INTERESTED"
    post(client, {**report_for(None, "INTERESTED"), "room": "call-e", "dispositions": None})
    assert Call.objects.get(room="call-e").disposition_code == ""


def test_old_version_without_list_uses_builtin_codes(client, workspace):
    agent = make_agent(workspace)
    version = AgentVersion.objects.create(agent=agent, number=1, snapshot={"name": "old"})
    post(client, report_for(version, "NE"))
    call = Call.objects.get(room="call-d")
    assert (call.disposition_code, call.disposition_name, call.disposition_group) == (
        "NE", "Not eligible", "Not interested")


# --- a person's change ------------------------------------------------------------------------------

def test_person_changes_disposition_and_history_is_kept(client, member, workspace):
    version = make_version(workspace, make_list(workspace))
    post(client, report_for(version, "INTERESTED"))
    editor = member("editor")
    url = "/api/calls/call-d/disposition"
    r = editor.post(url, {"code": "CBR", "fields": {}, "note": ""}, format="json")
    assert r.status_code == 400 and r.data["fields"] == {"callback_time": "Required."}
    r = editor.post(url, {"code": "ZZZ"}, format="json")
    assert r.status_code == 400 and "code" in r.data
    assert member("viewer").post(url, {"code": "CBR"}, format="json").status_code == 403

    r = editor.post(url, {"code": "CBR", "fields": {"callback_time": "2026-11-17T18:00"}, "note": "Busy now"},
                    format="json")
    assert r.status_code == 200, r.data
    d = r.data["disposition"]
    assert (d["code"], d["source"], d["set_by"]) == ("CBR", "user", "editor1@example.com")
    assert d["fields"] == [{"key": "callback_time", "label": "Callback time", "type": "datetime",
                            "value": "2026-11-17T18:00"}]
    assert [(h["source"], h["code"], h["note"]) for h in r.data["disposition_history"]] == [
        ("ai", "INTERESTED", "said so"), ("user", "CBR", "Busy now")]
    assert [i["code"] for i in r.data["disposition_options"]["items"]] == [i["code"] for i in ITEMS]

    # A re-sent report never overwrites a person's change.
    post(client, report_for(version, "INTERESTED"))
    assert Call.objects.get(room="call-d").disposition_code == "CBR"


def test_change_refused_without_a_list(client, member, workspace):
    version = make_version(workspace, None)
    post(client, report_for(version, "INTERESTED"))
    r = member("editor").post("/api/calls/call-d/disposition", {"code": "INTERESTED"}, format="json")
    assert r.status_code == 400
    assert member("editor").get("/api/calls/call-d").data["disposition_options"] is None


def test_calls_filter_by_disposition_code_and_none(member, workspace):
    version = make_version(workspace, make_list(workspace))
    for room, code in (("a", "INTERESTED"), ("b", "CBR")):
        call = Call.objects.create(room=room, workspace=workspace, agent_version=version)
        data = {"room": room, "disposition": code, "outcome": {"callback_time": "6 pm"}}
        CallReport.objects.create(call=call, disposition=code, data=data)
        apply_report(call, data)
    Call.objects.create(room="c", workspace=workspace)
    c = member("viewer")
    rooms = lambda **q: sorted(r["room"] for r in c.get("/api/calls", q).data["results"])  # noqa: E731
    assert rooms(disposition="cbr") == ["b"]
    assert rooms(disposition="none") == ["c"]
    assert rooms(outcome="Interested") == ["a"]


# --- webhook ----------------------------------------------------------------------------------------

def test_webhook_secret_is_made_and_shown_to_admins_only(member, workspace):
    admin = member("admin")
    r = admin.patch("/api/workspace", {"webhook_url": "https://hooks.example.com/d"}, format="json")
    assert r.status_code == 200 and r.data["webhook_url"] == "https://hooks.example.com/d"
    assert len(r.data["webhook_secret"]) == 64
    assert member("editor").get("/api/workspace").data["webhook_secret"] == ""
    assert member("editor").patch("/api/workspace", {"webhook_url": ""}, format="json").status_code == 403
    assert admin.patch("/api/workspace", {"webhook_url": "ftp://x"}, format="json").status_code == 400


def test_disposition_change_sends_signed_webhook(client, workspace, monkeypatch, django_capture_on_commit_callbacks):
    workspace.webhook_url, workspace.webhook_secret = "https://hooks.example.com/d", "s3cret"
    workspace.save()
    sent = []

    class FakeThread:
        def __init__(self, target, args, **kw):
            self.target, self.args = target, args

        def start(self):
            sent.append(self.args)

    monkeypatch.setattr(webhooks.threading, "Thread", FakeThread)
    version = make_version(workspace, make_list(workspace))
    with django_capture_on_commit_callbacks(execute=True):
        post(client, report_for(version, "CBR", callback_time="6 pm"))
    assert len(sent) == 1
    url, secret, body = sent[0]
    event = json.loads(body)
    assert url == "https://hooks.example.com/d" and event["event"] == "call.disposition"
    assert event["disposition"]["code"] == "CBR" and event["disposition"]["source"] == "ai"
    assert event["disposition"]["fields"] == {"callback_time": "6 pm"} and event["previous_code"] is None
    expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert webhooks.sign(secret, body) == expected


def test_no_webhook_without_url(client, workspace, monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(webhooks.threading, "Thread", lambda **kw: pytest.fail("no webhook expected"))
    version = make_version(workspace, make_list(workspace))
    with django_capture_on_commit_callbacks(execute=True):
        post(client, report_for(version, "INTERESTED"))
    assert DispositionChange.objects.count() == 1


def test_legacy_snapshot_matches_default_list():
    assert [i["code"] for i in legacy_snapshot()["items"]] == [i["code"] for i in LEGACY["items"]]
    assert legacy_snapshot()["not_reached"] == "NOT_CONNECTED" and legacy_snapshot()["dropped"] == "CDRP"


def test_workflow_end_step_may_use_a_list_code(workspace):
    from tests.test_workflow_graph import driver_graph
    from workflows.api import validate_for

    graph = driver_graph()
    end = next(s for s in graph["steps"] if s["type"] == "end")
    end["outcome"] = "LOAN_OK"
    wf = make_workflow(workspace, graph)
    assert any("unknown outcome" in e for e in validate_for(wf, graph))
    make_list(workspace, items=[*ITEMS, {**ITEMS[0], "code": "LOAN_OK"}])
    assert not any("unknown outcome" in e for e in validate_for(wf, graph))


def test_malformed_list_snapshot_does_not_break_ingest(client, workspace):
    agent = make_agent(workspace)
    snap = {"dispositions": {"name": "x", "items": ["junk", {"code": "OK", "group": "Interested"}]}}
    version = AgentVersion.objects.create(agent=agent, number=1, snapshot=snap)
    assert post(client, report_for(version, "NOPE")).status_code == 200
    call = Call.objects.get(room="call-d")
    assert (call.disposition_code, call.disposition_source) == ("OK", "system")


def test_webhook_url_hidden_from_non_admins(member, workspace):
    workspace.webhook_url, workspace.webhook_secret = "https://hooks.example.com/d", "s3cret"
    workspace.save()
    assert member("editor").get("/api/workspace").data["webhook_url"] == ""
    assert member("admin").get("/api/workspace").data["webhook_url"] == "https://hooks.example.com/d"
