"""Call recordings: egress webhooks, the agent report link, the member-only audio endpoint, call detail and
list fields, the runtime switch and the retention purge."""

import os
import time
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as djtz
from livekit import api
from livekit.protocol.egress import EgressInfo, EgressStatus, FileInfo

from calls import views
from calls.models import Call, CallEvent, Recording, recording_relpath
from runtime import api as runtime_api
from tests.helpers import assert_isolated
from tests.test_report import make_report
from tests.test_report import post as post_report
from tests.test_runtime_api import get_config, published_agent
from workspaces.models import Workspace

pytestmark = pytest.mark.django_db

T0 = 1_762_300_000
NS = 1_000_000_000
AUDIO = bytes(range(256)) * 40  # 10 240 bytes


@pytest.fixture
def rec_dir(settings, tmp_path):
    settings.RECORDINGS_DIR = tmp_path / "recordings"
    settings.RECORDINGS_DIR.mkdir()
    return settings.RECORDINGS_DIR


def egress(room="r1", egress_id="EG_1", status=EgressStatus.EGRESS_ACTIVE, filename="", size=0,
           duration_s=0, error="", started=T0):
    info = EgressInfo(egress_id=egress_id, room_name=room, status=status, started_at=started * NS, error=error)
    if filename:
        info.file_results.append(FileInfo(filename=filename, size=size, duration=duration_s * NS,
                                          started_at=(started + 1) * NS))
    if status in (EgressStatus.EGRESS_COMPLETE, EgressStatus.EGRESS_FAILED, EgressStatus.EGRESS_ABORTED):
        info.ended_at = (started + 60) * NS
    return info


def feed(monkeypatch, client, *infos, kind="egress_ended"):
    queue = [api.WebhookEvent(event=kind, egress_info=i) for i in infos]
    monkeypatch.setattr(views.receiver, "receive", lambda body, auth: queue.pop(0))
    for _ in infos:
        r = client.post("/webhook", data="{}", content_type="application/webhook+json", HTTP_AUTHORIZATION="x")
        assert r.status_code == 200


def write_file(rec_dir, rel="2026/11/r1.ogg", data=AUDIO):
    path = rec_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def recorded_call(workspace, rec_dir, room="r1", *, status=Recording.COMPLETE, started=None, write=True):
    call = Call.objects.create(room=room, workspace=workspace, caller="+91 98201 44821",
                               started_at=started or datetime(2026, 11, 7, 9, 2, tzinfo=timezone.utc))
    rel = f"2026/11/{room}.ogg"
    if write:
        write_file(rec_dir, rel)
    Recording.objects.create(call=call, egress_id=f"EG_{room}", status=status, path=rel, duration_ms=134_200,
                             size_bytes=len(AUDIO), started_at=datetime(2026, 11, 7, 9, 2, 11, tzinfo=timezone.utc))
    return call


# --- paths ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected", [
    ("/data/recordings/2026/11/r1.ogg", "2026/11/r1.ogg"),
    ("2026/11/r1.ogg", "2026/11/r1.ogg"),
    ("/data/recordings/../secrets", ""),
    ("/etc/passwd", ""),
    ("", ""),
    ("/data/recordings/", ""),
])
def test_recording_relpath(filename, expected, rec_dir):
    assert recording_relpath(filename) == expected


def test_file_never_leaves_the_recordings_dir(workspace, rec_dir, tmp_path):
    (tmp_path / "secret.ogg").write_bytes(b"x")
    call = Call.objects.create(room="r1", workspace=workspace)
    rec = Recording.objects.create(call=call, status=Recording.COMPLETE, path="../secret.ogg")
    assert rec.file() is None
    os.symlink(tmp_path / "secret.ogg", rec_dir / "link.ogg")
    rec.path = "link.ogg"
    assert rec.file() is None


# --- webhooks ---------------------------------------------------------------------------------------

def test_egress_lifecycle(monkeypatch, client, rec_dir):
    feed(monkeypatch, client, egress(status=EgressStatus.EGRESS_STARTING), kind="egress_started")
    rec = Recording.objects.get(call__room="r1")
    assert rec.status == Recording.STARTING and rec.egress_id == "EG_1"
    feed(monkeypatch, client, egress(status=EgressStatus.EGRESS_ACTIVE), kind="egress_updated")
    rec.refresh_from_db()
    assert rec.status == Recording.RECORDING
    feed(monkeypatch, client, egress(status=EgressStatus.EGRESS_COMPLETE, filename="/data/recordings/2026/11/r1.ogg",
                                     size=4321, duration_s=134))
    rec.refresh_from_db()
    assert rec.status == Recording.COMPLETE and rec.path == "2026/11/r1.ogg"
    assert rec.size_bytes == 4321 and rec.duration_ms == 134_000
    # The file's own start time lines up the transcript.
    assert rec.started_at == datetime.fromtimestamp(T0 + 1, timezone.utc)
    assert rec.ended_at == datetime.fromtimestamp(T0 + 60, timezone.utc)


def test_late_and_repeated_events_never_undo_a_final_status(monkeypatch, client, rec_dir):
    done = egress(status=EgressStatus.EGRESS_COMPLETE, filename="/data/recordings/r1.ogg", size=10, duration_s=5)
    feed(monkeypatch, client, done, egress(status=EgressStatus.EGRESS_ACTIVE), done,
         egress(status=EgressStatus.EGRESS_ABORTED, error="late"))
    rec = Recording.objects.get(call__room="r1")
    assert rec.status == Recording.COMPLETE and rec.error == ""
    assert Recording.objects.count() == 1


def test_failed_egress_stores_the_error(monkeypatch, client, rec_dir):
    feed(monkeypatch, client, egress(status=EgressStatus.EGRESS_FAILED, error="no space left on device"))
    rec = Recording.objects.get(call__room="r1")
    assert rec.status == Recording.FAILED and rec.error == "no space left on device"


def test_complete_without_a_usable_file_is_failed(monkeypatch, client, rec_dir):
    feed(monkeypatch, client, egress(status=EgressStatus.EGRESS_COMPLETE, filename="/elsewhere/x.ogg", size=1))
    assert Recording.objects.get(call__room="r1").status == Recording.FAILED


def test_bad_egress_event_never_fails_the_webhook(monkeypatch, client, rec_dir):
    feed(monkeypatch, client, egress(room=""))  # no room: ignored
    monkeypatch.setattr(Recording, "from_egress", classmethod(lambda cls, info: 1 / 0))
    feed(monkeypatch, client, egress())
    assert not Recording.objects.exists()


# --- agent report -----------------------------------------------------------------------------------

def test_report_links_the_egress_before_webhooks(client, rec_dir):
    report = make_report("r1")
    report["recording"] = {"egress_id": "EG_9", "started_at": T0, "filepath": "/data/recordings/2026/11/r1.ogg"}
    assert post_report(client, report).status_code == 200
    rec = Recording.objects.get(call__room="r1")
    assert rec.egress_id == "EG_9" and rec.status == Recording.STARTING and rec.path == "2026/11/r1.ogg"
    assert rec.started_at == datetime.fromtimestamp(T0, timezone.utc)


def test_report_after_webhooks_changes_nothing(monkeypatch, client, rec_dir):
    feed(monkeypatch, client, egress(egress_id="EG_9", status=EgressStatus.EGRESS_COMPLETE,
                                     filename="/data/recordings/2026/11/r1.ogg", size=10, duration_s=5))
    report = make_report("r1")
    report["recording"] = {"egress_id": "EG_9", "started_at": T0 - 100, "filepath": "/data/recordings/other.ogg"}
    post_report(client, report)
    rec = Recording.objects.get(call__room="r1")
    assert rec.status == Recording.COMPLETE and rec.path == "2026/11/r1.ogg"
    assert rec.started_at == datetime.fromtimestamp(T0 + 1, timezone.utc)


def test_report_with_a_start_error_is_a_failed_recording(client, rec_dir):
    report = make_report("r1")
    report["recording"] = {"egress_id": None, "error": "start timed out"}
    post_report(client, report)
    rec = Recording.objects.get(call__room="r1")
    assert rec.status == Recording.FAILED and rec.error == "start timed out" and rec.egress_id is None
    post_report(client, make_report("r2"))  # no recording key: no row
    assert not Recording.objects.filter(call__room="r2").exists()


# --- call detail and list ---------------------------------------------------------------------------

def test_call_detail_recording_fields(member, workspace, rec_dir):
    recorded_call(workspace, rec_dir)
    body = member("viewer").get("/api/calls/r1").json()
    assert body["recording_url"] == "/api/calls/r1/recording"
    assert body["recording_status"] == "complete" and body["recording_duration_s"] == 134.2
    assert body["recording_started_at"] == "2026-11-07T09:02:11Z"


@pytest.mark.parametrize("status,shown", [
    (Recording.STARTING, "processing"), (Recording.RECORDING, "processing"),
    (Recording.FAILED, "failed"), (Recording.PURGED, "purged"),
])
def test_call_detail_recording_states(member, workspace, rec_dir, status, shown):
    recorded_call(workspace, rec_dir, status=status)
    body = member("viewer").get("/api/calls/r1").json()
    assert body["recording_status"] == shown and body["recording_url"] is None
    assert body["recording_started_at"] is None


def test_call_detail_without_recording_and_missing_file(member, workspace, rec_dir):
    Call.objects.create(room="plain", workspace=workspace)
    recorded_call(workspace, rec_dir, room="gone", write=False)
    c = member("viewer")
    plain = c.get("/api/calls/plain").json()
    assert plain["recording_status"] == "none" and plain["recording_url"] is None
    gone = c.get("/api/calls/gone").json()
    assert gone["recording_status"] == "failed" and gone["recording_url"] is None


def test_stuck_recording_settles_from_the_file(member, workspace, rec_dir):
    call = recorded_call(workspace, rec_dir, status=Recording.RECORDING)
    Call.objects.filter(pk=call.pk).update(ended_at=djtz.now() - timedelta(minutes=5))
    c = member("viewer")
    assert c.get("/api/calls/r1").json()["recording_status"] == "processing"  # too soon to settle
    Call.objects.filter(pk=call.pk).update(ended_at=djtz.now() - timedelta(minutes=11))
    assert c.get("/api/calls/r1").json()["recording_status"] == "complete"
    (rec_dir / "2026/11/r1.ogg").unlink()
    recorded_call(workspace, rec_dir, room="r2", status=Recording.STARTING, write=False)
    Call.objects.filter(room="r2").update(ended_at=djtz.now() - timedelta(hours=1))
    assert c.get("/api/calls/r2").json()["recording_status"] == "failed"


def test_calls_list_has_recording_without_extra_queries(member, workspace, rec_dir):
    for i in range(8):
        recorded_call(workspace, rec_dir, room=f"r{i}", status=Recording.COMPLETE if i % 2 else Recording.FAILED,
                      started=datetime(2026, 11, 7, 9, i, tzinfo=timezone.utc))
    Call.objects.create(room="plain", workspace=workspace, started_at=datetime(2026, 11, 7, 8, tzinfo=timezone.utc))
    c = member("viewer")
    rows = c.get("/api/calls").json()["results"]
    assert {r["room"]: r["has_recording"] for r in rows} == {
        **{f"r{i}": bool(i % 2) for i in range(8)}, "plain": False}
    assert {r["room"]: r["recording_status"] for r in rows} == {
        **{f"r{i}": "complete" if i % 2 else "failed" for i in range(8)}, "plain": "none"}
    with CaptureQueriesContext(connection) as ctx:
        c.get("/api/calls")
    assert len(ctx.captured_queries) <= 6


# --- audio endpoint ---------------------------------------------------------------------------------

def body_of(response):
    return b"".join(response.streaming_content) if response.streaming else response.content


def test_recording_full_and_headers(member, workspace, rec_dir):
    recorded_call(workspace, rec_dir)
    r = member("viewer").get("/api/calls/r1/recording")
    assert r.status_code == 200 and body_of(r) == AUDIO
    assert r["Content-Type"] == "audio/ogg" and r["Content-Length"] == str(len(AUDIO))
    assert r["Accept-Ranges"] == "bytes" and r["Cache-Control"] == "private, no-store"
    assert r["Content-Disposition"] == 'inline; filename="919820144821-2026-11-07-1432.ogg"'
    d = member("viewer").get("/api/calls/r1/recording?download=1")
    assert d["Content-Disposition"].startswith("attachment;")


@pytest.mark.parametrize("header,start,end", [
    ("bytes=1000-", 1000, len(AUDIO) - 1),
    ("bytes=0-99", 0, 99),
    ("bytes=-100", len(AUDIO) - 100, len(AUDIO) - 1),
    ("bytes=10000-99999", 10000, len(AUDIO) - 1),
])
def test_recording_range(member, workspace, rec_dir, header, start, end):
    recorded_call(workspace, rec_dir)
    r = member("viewer").get("/api/calls/r1/recording", HTTP_RANGE=header)
    assert r.status_code == 206
    assert r["Content-Range"] == f"bytes {start}-{end}/{len(AUDIO)}"
    assert body_of(r) == AUDIO[start:end + 1] and r["Content-Length"] == str(end - start + 1)


@pytest.mark.parametrize("header", ["bytes=20000-", "bytes=50-10", "bytes=-0"])
def test_recording_unsatisfiable_range(member, workspace, rec_dir, header):
    recorded_call(workspace, rec_dir)
    r = member("viewer").get("/api/calls/r1/recording", HTTP_RANGE=header)
    assert r.status_code == 416 and r["Content-Range"] == f"bytes */{len(AUDIO)}"


def test_recording_ignores_unparseable_ranges(member, workspace, rec_dir):
    recorded_call(workspace, rec_dir)
    r = member("viewer").get("/api/calls/r1/recording", HTTP_RANGE="bytes=0-1,5-9")
    assert r.status_code == 200 and body_of(r) == AUDIO


def test_recording_head(member, workspace, rec_dir):
    recorded_call(workspace, rec_dir)
    r = member("viewer").head("/api/calls/r1/recording")
    assert r.status_code == 200 and r["Content-Length"] == str(len(AUDIO)) and body_of(r) == b""


def test_recording_access(client, member, workspace, other_workspace, rec_dir):
    recorded_call(workspace, rec_dir, room="ours")
    recorded_call(other_workspace, rec_dir, room="theirs")
    recorded_call(workspace, rec_dir, room="failed", status=Recording.FAILED)
    recorded_call(workspace, rec_dir, room="gone", write=False)
    Call.objects.create(room="plain", workspace=workspace)
    assert client.get("/api/calls/ours/recording").status_code in (401, 403)
    c = member("viewer")
    assert c.get("/api/calls/ours/recording").status_code == 200
    assert_isolated(c, "/api/calls/theirs/recording")
    for room in ("failed", "gone", "plain", "nope"):
        assert c.get(f"/api/calls/{room}/recording").status_code == 404, room


# --- runtime switch and workspace setting -----------------------------------------------------------

def test_runtime_recording_setting(client, workspace, rec_dir, settings, monkeypatch):
    published_agent(workspace)

    def recording():
        return get_config(client).json()["snapshot"]["account"]["recording"]

    assert recording() == {"enabled": False, "reason": "off"}
    Workspace.objects.filter(pk=workspace.pk).update(recording_enabled=True)
    assert recording() == {"enabled": True, "reason": None}
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(runtime_api.shutil, "disk_usage", lambda p: Usage(10, 9, settings.RECORDING_MIN_FREE_BYTES - 1))
    assert recording() == {"enabled": False, "reason": "disk_low"}


def test_owner_turns_recording_on_viewer_cannot(member, workspace):
    assert member("viewer").patch("/api/workspace", {"recording_enabled": True}, format="json").status_code == 403
    r = member("owner").patch("/api/workspace", {"recording_enabled": True}, format="json")
    assert r.status_code == 200 and r.json()["recording_enabled"] is True
    workspace.refresh_from_db()
    assert workspace.recording_enabled is True and workspace.dead_air_enabled is True
    assert member("owner").patch("/api/workspace", {"recording_enabled": "yes"}, format="json").status_code == 400


# --- retention --------------------------------------------------------------------------------------

def test_purge_recordings_and_orphans(workspace, rec_dir):
    now = djtz.now()
    old = recorded_call(workspace, rec_dir, room="old", started=now - timedelta(days=91))
    new = recorded_call(workspace, rec_dir, room="new", started=now - timedelta(days=89))
    stale = write_file(rec_dir, "2026/01/orphan.ogg")
    fresh = write_file(rec_dir, "2026/11/in-progress.ogg")
    day_ago = time.time() - 25 * 3600
    os.utime(stale, (day_ago, day_ago))
    os.utime(rec_dir / "2026/11/new.ogg", (day_ago, day_ago))  # old mtime, but a row points at it

    out = StringIO()
    call_command("purge_old_call_data", "--dry-run", stdout=out)
    assert "Would delete 1 recordings" in out.getvalue() and "would delete 1 orphaned" in out.getvalue()
    assert (rec_dir / "2026/11/old.ogg").exists() and stale.exists()
    assert Recording.objects.get(call=old).status == Recording.COMPLETE

    out = StringIO()
    call_command("purge_old_call_data", stdout=out)
    assert "Deleted 1 recordings" in out.getvalue() and "deleted 1 orphaned" in out.getvalue()
    rec = Recording.objects.get(call=old)
    assert rec.status == Recording.PURGED and rec.path == ""
    assert not (rec_dir / "2026/11/old.ogg").exists() and not stale.exists()
    assert fresh.exists() and (rec_dir / "2026/11/new.ogg").exists()
    assert Recording.objects.get(call=new).status == Recording.COMPLETE
    # Transcript purge still runs alongside.
    CallEvent.objects.create(call=old, seq=1, type="turn", payload={"text": "hi"}, at=now - timedelta(days=91))
    call_command("purge_old_call_data", stdout=StringIO())
    assert not CallEvent.objects.filter(call=old).exists()
