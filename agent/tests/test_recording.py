"""Call recording: when a call is recorded, the egress start (timeout, failure, late start), the consent line
following the real recording, and the report field."""

import asyncio
from types import SimpleNamespace

import pytest
from livekit import api

import agent
import prompt
import recording
from console_config import Config
from recording import RecordingHandle, recording_path, recording_wanted, report_field, start_recording
from report import build_report

CONSENT = prompt.DEFAULT_CONSENT_LINE


@pytest.fixture(autouse=True)
def default_consent(monkeypatch):
    # Independent of the local .env: the default consent line.
    monkeypatch.delenv("AGENT_CONSENT_LINE", raising=False)
ON = {"account": {"recording": {"enabled": True, "reason": None}}}


@pytest.fixture(autouse=True)
def master_switch_on(monkeypatch):
    monkeypatch.setenv("RECORDING_ENABLED", "true")


# --- whether to record ------------------------------------------------------------------------------

def test_records_a_phone_call_with_the_account_switch_on():
    assert recording_wanted("console", ON, is_call=True) == (True, "")


def test_records_a_browser_voice_test_with_the_account_switch_on():
    assert recording_wanted("draft", ON, is_call=True) == (True, "")


@pytest.mark.parametrize("source,snapshot,phone,reason", [
    ("console", ON, False, "not_a_call"),  # neither a SIP caller nor a voice test
    ("cache", ON, True, "no_live_config"),  # cached config: the setting isn't known now
    ("builtin", None, True, "no_live_config"),
    ("draft", {"account": {"recording": {"enabled": False, "reason": "off"}}}, True, "off"),
    ("draft", {}, True, "off"),  # older dashboard: the draft carries no account switch
    ("console", {"account": {"recording": {"enabled": False, "reason": "off"}}}, True, "off"),
    ("console", {"account": {"recording": {"enabled": False, "reason": "disk_low"}}}, True, "disk_low"),
    ("console", {"account": {"dead_air_enabled": True}}, True, "off"),  # older dashboard
    ("console", {"account": {"recording": {"enabled": "yes"}}}, True, "off"),
    ("console", {}, True, "off"),
])
def test_not_recorded(source, snapshot, phone, reason):
    assert recording_wanted(source, snapshot, phone) == (False, reason)


@pytest.mark.parametrize("value", ["false", "", "no"])
def test_master_switch_off_wins(monkeypatch, value):
    monkeypatch.setenv("RECORDING_ENABLED", value)
    assert recording_wanted("console", ON, True) == (False, "kill_switch")
    monkeypatch.delenv("RECORDING_ENABLED")
    assert recording_wanted("console", ON, True) == (False, "kill_switch")


def test_recording_path():
    # 2025-11-07 09:02 UTC
    assert recording_path("call-_+919820144821_aBc", 1_762_506_120) == \
        "/data/recordings/2025/11/call-__919820144821_aBc.ogg"
    assert recording_path("../..", 1_762_506_120).endswith("/call.ogg")


def test_egress_request_is_audio_only_ogg():
    req = recording.egress_request("r1", "/data/recordings/x.ogg")
    assert req.room_name == "r1" and req.audio_only
    out = req.file_outputs[0]
    assert out.file_type == api.EncodedFileType.OGG and out.filepath == "/data/recordings/x.ogg"
    assert out.disable_manifest and req.advanced.audio_bitrate == 32


# --- starting the egress ----------------------------------------------------------------------------

class FakeEgress:
    def __init__(self, delay=0.0, error=None):
        self.delay, self.error, self.stopped, self.requests = delay, error, [], []

    async def start_room_composite_egress(self, req):
        self.requests.append(req)
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return api.EgressInfo(egress_id="EG_1", room_name=req.room_name)

    async def stop_egress(self, req):
        self.stopped.append(req.egress_id)


def lk(egress):
    return SimpleNamespace(egress=egress)


async def test_start_returns_a_handle():
    egress = FakeEgress()
    handle, error = await start_recording(lk(egress), "r1")
    assert error is None and handle.egress_id == "EG_1"
    assert handle.filepath.startswith("/data/recordings/") and handle.filepath.endswith("/r1.ogg")
    assert egress.requests[0].room_name == "r1" and egress.stopped == []


async def test_start_failure_means_no_recording():
    handle, error = await start_recording(lk(FakeEgress(error=RuntimeError("no egress available"))), "r1")
    assert handle is None and "no egress available" in error


async def test_slow_start_is_failed_and_stopped_once_it_starts():
    egress = FakeEgress(delay=0.2)
    handle, error = await start_recording(lk(egress), "r1", timeout_s=0.05)
    assert handle is None and "took over" in error
    await asyncio.sleep(0.3)
    assert egress.stopped == ["EG_1"]  # recorded without consent otherwise


def test_report_field():
    handle = RecordingHandle("EG_1", 1_762_506_120.5, "/data/recordings/2025/11/r1.ogg")
    assert report_field(handle, None) == {"egress_id": "EG_1", "started_at": 1_762_506_120.5,
                                          "filepath": "/data/recordings/2025/11/r1.ogg", "error": None}
    assert report_field(None, "boom") == {"egress_id": None, "started_at": None, "filepath": None, "error": "boom"}
    assert report_field(None, None) is None
    base = dict(room="r1", outcome={}, mood=None, timeline=[], dead_air=[], latency={}, behavior=None, turns=None)
    assert build_report(**base, recording=report_field(handle, None))["recording"]["egress_id"] == "EG_1"
    assert "recording" not in build_report(**base)


# --- consent follows the real recording -------------------------------------------------------------

@pytest.mark.parametrize("cfg", [
    Config("builtin", None, None),
    Config("console", {"agent_id": 1, "version": 1, "name": "x", "persona_name": "Maya", "settings": {},
                       "script": [{"title": "Job", "body_rendered": "Qualify."}], "knowledge": [],
                       "workflow": None}, 3),
])
def test_consent_only_when_recorded(cfg):
    recorded = agent.PhoneAgent({}, agent.GEMINI_LANGUAGE_RULES, cfg, recording=True)
    assert recorded.opening.endswith(" " + CONSENT) and CONSENT in recorded.base_instructions
    plain = agent.PhoneAgent({}, agent.GEMINI_LANGUAGE_RULES, cfg)
    assert CONSENT not in plain.opening and CONSENT not in plain.base_instructions


def test_consent_kept_when_the_console_config_is_unusable():
    # The recording is running either way, so the built-in fallback must still say so.
    bad = Config("console", {"persona_name": 5, "workflow": {"graph": "not a graph"}, "script": None}, 3)
    a = agent.PhoneAgent({}, agent.GEMINI_LANGUAGE_RULES, bad, recording=True)
    assert a.opening.endswith(" " + CONSENT)
