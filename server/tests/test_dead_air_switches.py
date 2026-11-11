"""Dead-air switches above the agent: one for the account (workspace), one per workflow.

The account switch reaches calls straight away (the runtime adds it when it serves the published snapshot);
the workflow switch is part of what an agent publishes, like the rest of the workflow.
"""
import pytest

from tests.test_publish import make_agent, make_user, make_workflow
from tests.test_runtime_api import get_config, published_agent
from voiceagents.publish import is_outdated, publish
from workflows.models import Workflow
from workspaces.models import Workspace

pytestmark = pytest.mark.django_db


# --- account ----------------------------------------------------------------------------------------


def test_account_switch_defaults_on_and_shows_in_me(member):
    c = member("viewer")
    assert c.get("/api/workspace").json() == {"id": c.get("/api/me").json()["workspace"]["id"], "name": "Northwind Car Rentals",
                                              "slug": "northwind", "dead_air_enabled": True,
                                              "recording_enabled": False}
    assert c.get("/api/me").json()["workspace"]["dead_air_enabled"] is True


def test_admin_turns_the_account_switch_off(member, workspace):
    c = member("admin")
    r = c.patch("/api/workspace", {"dead_air_enabled": False}, format="json")
    assert r.status_code == 200 and r.json()["dead_air_enabled"] is False
    workspace.refresh_from_db()
    assert workspace.dead_air_enabled is False
    assert c.get("/api/me").json()["workspace"]["dead_air_enabled"] is False


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_only_owners_and_admins_change_the_account_switch(member, workspace, role):
    r = member(role).patch("/api/workspace", {"dead_air_enabled": False}, format="json")
    assert r.status_code == 403
    workspace.refresh_from_db()
    assert workspace.dead_air_enabled is True


@pytest.mark.parametrize("value", ["false", 0, None, "no"])
def test_account_switch_takes_true_or_false_only(member, value):
    r = member("owner").patch("/api/workspace", {"dead_air_enabled": value}, format="json")
    assert r.status_code == 400


def test_account_switch_belongs_to_the_members_workspace(member, workspace, other_workspace):
    member("owner").patch("/api/workspace", {"dead_air_enabled": False}, format="json")
    other_workspace.refresh_from_db()
    assert other_workspace.dead_air_enabled is True


def test_runtime_config_carries_the_live_account_switch(client, workspace):
    _, version = published_agent(workspace)
    body = get_config(client).json()
    off = {"enabled": False, "reason": "off"}
    assert body["snapshot"] == {**version.snapshot, "account": {"dead_air_enabled": True, "recording": off}}
    # No republish needed: the next call sees the change.
    Workspace.objects.filter(pk=workspace.pk).update(dead_air_enabled=False)
    assert get_config(client).json()["snapshot"]["account"] == {"dead_air_enabled": False, "recording": off}
    version.refresh_from_db()
    assert "account" not in version.snapshot  # the stored version is untouched


# --- workflow ---------------------------------------------------------------------------------------


def test_workflow_switch_defaults_on_and_saves_without_a_revision(member, workspace):
    c = member("editor")
    wf = make_workflow(workspace)
    got = c.get(f"/api/workflows/{wf.id}").json()
    assert got["dead_air_enabled"] is True
    assert c.get("/api/workflows").json()[0]["dead_air_enabled"] is True
    r = c.patch(f"/api/workflows/{wf.id}", {"dead_air_enabled": False}, format="json")
    assert r.status_code == 200 and r.json()["dead_air_enabled"] is False
    assert r.json()["current_revision"] == 1  # a setting, not a graph edit
    assert Workflow.objects.get(pk=wf.id).dead_air_enabled is False


def test_workflow_switch_takes_true_or_false_only(member, workspace):
    wf = make_workflow(workspace)
    r = member("editor").patch(f"/api/workflows/{wf.id}", {"dead_air_enabled": "off"}, format="json")
    assert r.status_code == 400
    assert Workflow.objects.get(pk=wf.id).dead_air_enabled is True


def test_viewers_cannot_change_the_workflow_switch(member, workspace):
    wf = make_workflow(workspace)
    assert member("viewer").patch(f"/api/workflows/{wf.id}", {"dead_air_enabled": False}, format="json").status_code == 403


def test_workflow_switch_is_published_and_flags_the_agent_outdated(workspace):
    wf = make_workflow(workspace)
    agent = make_agent(workspace, workflow=wf)
    v1 = publish(agent, make_user())
    assert v1.snapshot["workflow"]["dead_air_enabled"] is True
    assert is_outdated(agent) is False

    Workflow.objects.filter(pk=wf.pk).update(dead_air_enabled=False)
    agent.refresh_from_db()
    assert is_outdated(agent) is True
    v2 = publish(agent, make_user("pub2@example.com"))
    assert v2.snapshot["workflow"]["dead_air_enabled"] is False
    agent.refresh_from_db()
    assert is_outdated(agent) is False


def test_snapshots_published_before_the_switch_existed_are_not_outdated(workspace):
    wf = make_workflow(workspace)
    agent = make_agent(workspace, workflow=wf)
    v = publish(agent, make_user())
    del v.snapshot["workflow"]["dead_air_enabled"]
    v.save(update_fields=["snapshot"])
    agent.refresh_from_db()
    assert is_outdated(agent) is False
