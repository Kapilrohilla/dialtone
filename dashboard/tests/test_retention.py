from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from calls.models import Call, CallEvent, CallReport, TurnLabel
from workspaces.models import IntegrationRequest


def _call(workspace, room, days):
    started = timezone.now() - timedelta(days=days)
    call = Call.objects.create(room=room, workspace=workspace, started_at=started)
    report = CallReport.objects.create(
        call=call, disposition="INTERESTED", data={"summary": "ok", "turns": [{"at_s": 1, "text": "hi"}]}
    )
    TurnLabel.objects.create(report=report, at_s=1.0, caller_text="hi", predicted="happy", label="happy")
    CallEvent.objects.create(call=call, seq=1, type="turn", payload={"text": "hi"}, at=started)
    CallEvent.objects.create(call=call, seq=2, type="mood", payload={"mood": "happy"}, at=started)
    return call


@pytest.mark.django_db
def test_purge_deletes_old_turns_only(workspace):
    old, new = _call(workspace, "old", 91), _call(workspace, "new", 89)
    out = StringIO()
    call_command("purge_old_call_data", stdout=out)
    assert not CallEvent.objects.filter(call=old, type="turn").exists()
    assert CallEvent.objects.filter(call=old, type="mood").exists()
    # R20: the telecaller's label survives; only the caller's words are blanked.
    label = TurnLabel.objects.get(report__call=old)
    assert label.caller_text == "" and label.label == "happy" and label.predicted == "happy"
    old.report.refresh_from_db()
    assert "turns" not in old.report.data
    assert old.report.disposition == "INTERESTED" and old.report.data["summary"] == "ok"
    assert CallEvent.objects.filter(call=new, type="turn").exists()
    assert TurnLabel.objects.get(report__call=new).caller_text == "hi"
    new.report.refresh_from_db()
    assert "turns" in new.report.data


@pytest.mark.django_db
def test_purge_dry_run_changes_nothing(workspace):
    old = _call(workspace, "old", 120)
    out = StringIO()
    call_command("purge_old_call_data", "--dry-run", stdout=out)
    assert CallEvent.objects.filter(call=old, type="turn").exists()
    assert TurnLabel.objects.get(report__call=old).caller_text == "hi"
    old.report.refresh_from_db()
    assert "turns" in old.report.data
    assert "1 turn events" in out.getvalue()


@pytest.mark.django_db
def test_integration_request_saved(member):
    c = member("viewer")
    r = c.post("/api/integrations/requests", {"tool": "HubSpot", "note": "please"}, format="json")
    assert r.status_code == 201
    assert set(r.json()) == {"id", "tool", "note", "created_at"}
    row = IntegrationRequest.objects.get()
    assert row.tool == "HubSpot" and row.user == c.user and row.workspace.slug == "carrum"
    assert c.post("/api/integrations/requests", {"note": "x"}, format="json").status_code == 400
    assert c.post("/api/integrations/requests", {"tool": "x" * 101}, format="json").status_code == 400
    assert c.post("/api/integrations/requests", {"tool": "Zoho"}, format="json").status_code == 201
