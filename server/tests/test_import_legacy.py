import sqlite3
from datetime import datetime, timezone

import pytest
from django.core.management import call_command

from calls.models import Call

pytestmark = pytest.mark.django_db

# Schema of the aiohttp dashboard's /data/calls.db.
LEGACY_SCHEMA = """CREATE TABLE calls (
    room            TEXT PRIMARY KEY,
    started_at      INTEGER,
    answered_at     INTEGER,
    ended_at        INTEGER,
    caller          TEXT,
    called          TEXT,
    sip_call_id     TEXT,
    agent_joined_at INTEGER,
    end_reason      TEXT
)"""


@pytest.fixture
def legacy_db(tmp_path):
    path = tmp_path / "calls.db"
    conn = sqlite3.connect(path)
    conn.execute(LEGACY_SCHEMA)
    conn.executemany(
        "INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("room-a", 1_762_300_000, 1_762_300_001, 1_762_300_090, "+919111111111", "+918000000000",
             "SCL_a", 1_762_300_002, "api_delete"),
            ("room-b", 1_762_310_000, None, None, "+919222222222", None, None, None, None),
        ],
    )
    conn.commit()
    conn.close()
    return path


def test_import_copies_rows(legacy_db):
    call_command("import_legacy_calls", "--path", str(legacy_db))
    assert Call.objects.count() == 2
    a = Call.objects.get(room="room-a")
    assert a.caller == "+919111111111"
    assert a.started_at == datetime.fromtimestamp(1_762_300_000, timezone.utc)
    assert a.ended_at == datetime.fromtimestamp(1_762_300_090, timezone.utc)
    assert a.end_reason == "api_delete"
    b = Call.objects.get(room="room-b")
    assert b.caller == "+919222222222"
    assert b.answered_at is None and b.called == "" and b.end_reason == ""


def test_import_idempotent(legacy_db):
    call_command("import_legacy_calls", "--path", str(legacy_db))
    call_command("import_legacy_calls", "--path", str(legacy_db))
    assert Call.objects.count() == 2


def test_import_assigns_the_workspace(legacy_db, workspace, member, capsys):
    call_command("import_legacy_calls", "--path", str(legacy_db))
    assert set(Call.objects.values_list("workspace_id", flat=True)) == {workspace.id}
    assert "assigned to a workspace: 2" in capsys.readouterr().out
    rooms = {r["room"] for r in member("viewer").get("/api/calls").json()["results"]}
    assert rooms == {"room-a", "room-b"}
