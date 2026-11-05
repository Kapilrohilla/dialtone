import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from pathlib import Path

from calls.models import Call, CallReport, TurnLabel

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.django_db


BUILD_LEGACY = """
import os, sys
os.environ["DJANGO_SETTINGS_MODULE"] = "legacy_settings"
import django
django.setup()
from datetime import datetime, timezone
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from calls.models import Call, CallReport, TurnLabel

call_command("migrate", verbosity=0)
c1 = Call.objects.create(id=1, room="room-a", started_at=datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc), caller="+911", end_reason="done")
Call.objects.create(id=2, room="room-b", caller="+912")
report = CallReport.objects.create(id=7, call=c1, disposition="INTERESTED", final_mood="happy", avg_sentiment=0.5,
                                   dead_air_nudges=2, data={"room": "room-a", "turns": [{"x": 1}]})
TurnLabel.objects.create(id=5, report=report, at_s=3.5, caller_text="haan", predicted="happy", label="happy")
g = Group.objects.create(id=4, name="telecallers")
User.objects.create(id=9, username="ops", email="ops@example.com", password="pbkdf2$x").groups.add(g)
"""


@pytest.fixture
def legacy_file(tmp_path):
    """A SQLite file with the old schema, built by Django's own migrations in a subprocess whose settings use SQLite."""
    path = tmp_path / "dashboard.sqlite3"
    (tmp_path / "legacy_settings.py").write_text(
        "from config.settings import *\n"
        f"DATABASES = {{'default': {{'ENGINE': 'django.db.backends.sqlite3', 'NAME': {str(path)!r}}}}}\n"
    )
    env = {**os.environ, "PYTHONPATH": f"{tmp_path}{os.pathsep}{DASHBOARD_DIR}"}
    subprocess.run([sys.executable, "-c", BUILD_LEGACY], cwd=DASHBOARD_DIR, env=env, check=True)
    return path


def test_copy_preserves_ids_and_counts(legacy_file, capsys):
    call_command("copy_from_sqlite", path=str(legacy_file))

    assert list(Call.objects.order_by("id").values_list("id", "room", "caller")) == [(1, "room-a", "+911"), (2, "room-b", "+912")]
    assert Call.objects.get(id=1).started_at == datetime(2026, 10, 1, 9, 30, tzinfo=timezone.utc)
    report = CallReport.objects.get()
    assert (report.id, report.call_id, report.disposition, report.dead_air_nudges) == (7, 1, "INTERESTED", 2)
    assert report.data == {"room": "room-a", "turns": [{"x": 1}]}
    label = TurnLabel.objects.get()
    assert (label.id, label.report_id, label.at_s, label.label) == (5, 7, 3.5, "happy")
    assert User.objects.get(id=9).groups.get().name == "telecallers"
    out = capsys.readouterr().out
    assert "calls: 2" in out and "reports: 1" in out and "turn labels: 1" in out

    assert Call.objects.create(room="room-c").id == 3  # sequences were reset
    assert CallReport.objects.create(call=Call.objects.get(id=2), data={}).id == 8


def test_copy_refuses_non_empty_target_unless_forced(legacy_file):
    Call.objects.create(room="existing")
    with pytest.raises(CommandError, match="--force"):
        call_command("copy_from_sqlite", path=str(legacy_file))
    assert Call.objects.count() == 1

    call_command("copy_from_sqlite", path=str(legacy_file), force=True)
    assert set(Call.objects.values_list("room", flat=True)) == {"existing", "room-a", "room-b"}


def test_copy_missing_file(tmp_path):
    with pytest.raises(CommandError, match="not found"):
        call_command("copy_from_sqlite", path=str(tmp_path / "nope.sqlite3"))


def test_source_is_left_untouched(legacy_file):
    before = legacy_file.read_bytes()
    call_command("copy_from_sqlite", path=str(legacy_file))
    assert legacy_file.read_bytes() == before


def test_dry_run_counts_but_writes_nothing(legacy_file, capsys):
    call_command("copy_from_sqlite", path=str(legacy_file), dry_run=True)
    assert "calls: 2" in capsys.readouterr().out
    assert Call.objects.count() == 0 and User.objects.filter(username="ops").count() == 0
    assert not (legacy_file.parent / ".copied-to-postgres").exists()


def test_if_needed_copies_once_and_writes_marker(legacy_file):
    call_command("copy_from_sqlite", path=str(legacy_file), if_needed=True)
    assert Call.objects.count() == 2
    assert (legacy_file.parent / ".copied-to-postgres").exists()

    Call.objects.create(room="new-after-cutover")
    call_command("copy_from_sqlite", path=str(legacy_file), if_needed=True)  # no-op
    assert Call.objects.count() == 3


def test_if_needed_skips_with_warning_when_target_has_calls(legacy_file, capsys, caplog):
    Call.objects.create(id=1, room="live-call")
    call_command("copy_from_sqlite", path=str(legacy_file), if_needed=True)
    assert list(Call.objects.values_list("room", flat=True)) == ["live-call"]
    assert "WARNING" in capsys.readouterr().err
    assert any(r.levelname == "WARNING" for r in caplog.records)
    assert not (legacy_file.parent / ".copied-to-postgres").exists()


def test_if_needed_without_sqlite_file_does_nothing(tmp_path):
    call_command("copy_from_sqlite", path=str(tmp_path / "none.sqlite3"), if_needed=True)
    assert Call.objects.count() == 0


# --- the real pre-workspace schema (calls at 0003, no workspaces/voiceagents/knowledge/workflows) -----

BUILD_OLD_SCHEMA = """
import os
os.environ["DJANGO_SETTINGS_MODULE"] = "legacy_settings"
import django
django.setup()
from django.core.management import call_command
from django.db import connection

for app in ("contenttypes", "auth", "sessions", "admin"):
    call_command("migrate", app, verbosity=0)
call_command("migrate", "calls", "0003", verbosity=0)
with connection.cursor() as cur:
    cur.execute("INSERT INTO calls_call (id, room, caller, called, sip_call_id, end_reason, started_at) "
                "VALUES (1, 'old-a', '+911', '+918000000000', '', 'done', '2026-10-01 09:30:00')")
    cur.execute("INSERT INTO calls_call (id, room, caller, called, sip_call_id, end_reason) "
                "VALUES (2, 'old-b', '+912', '', '', '')")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {r[0] for r in cur.fetchall()}
assert "workspaces_workspace" not in tables and "voiceagents_agent" not in tables, tables
"""


@pytest.fixture
def old_schema_file(tmp_path):
    path = tmp_path / "dashboard.sqlite3"
    (tmp_path / "legacy_settings.py").write_text(
        "from config.settings import *\n"
        f"DATABASES = {{'default': {{'ENGINE': 'django.db.backends.sqlite3', 'NAME': {str(path)!r}}}}}\n"
    )
    env = {**os.environ, "PYTHONPATH": f"{tmp_path}{os.pathsep}{DASHBOARD_DIR}"}
    subprocess.run([sys.executable, "-c", BUILD_OLD_SCHEMA], cwd=DASHBOARD_DIR, env=env, check=True)
    return path


def test_copy_from_old_schema_assigns_the_workspace(old_schema_file, workspace, member, capsys):
    call_command("copy_from_sqlite", path=str(old_schema_file))

    assert set(Call.objects.values_list("room", "workspace_id")) == {("old-a", workspace.id), ("old-b", workspace.id)}
    assert "assigned to a workspace: 2" in capsys.readouterr().out
    rooms = {r["room"] for r in member("viewer").get("/api/calls").json()["results"]}
    assert rooms == {"old-a", "old-b"}


def test_dry_run_from_old_schema_reports_the_assignment(old_schema_file, workspace, capsys):
    call_command("copy_from_sqlite", path=str(old_schema_file), dry_run=True)
    assert "assigned to a workspace: 2" in capsys.readouterr().out
    assert Call.objects.count() == 0
