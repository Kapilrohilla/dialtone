from pathlib import Path

import pytest

from voiceagents import voices


@pytest.mark.django_db
def test_voices_endpoint_lists_current_pipeline(member, settings):
    settings.AGENT_PIPELINE = "gemini-live"
    body = member("viewer").get("/api/voices").json()
    assert body["pipeline"] == "gemini-live" and [v["id"] for v in body["voices"]][:2] == ["Kore", "Aoede"]


@pytest.mark.django_db
def test_voices_endpoint_needs_login():
    from rest_framework.test import APIClient

    assert APIClient().get("/api/voices").status_code == 403


@pytest.mark.django_db
def test_agent_rejects_voice_from_other_pipeline(member, settings):
    settings.AGENT_PIPELINE = "gemini-live"
    c = member("editor")
    pk = c.post("/api/agents", {"name": "A"}, format="json").json()["id"]
    r = c.patch(f"/api/agents/{pk}", {"voice_id": "EXAVITQu4vr4xnSDxMaL"}, format="json")
    assert r.status_code == 400 and r.json()["voice_id"] == ["Choose a voice from the list."]
    assert c.patch(f"/api/agents/{pk}", {"voice_id": "Puck"}, format="json").status_code == 200
    settings.AGENT_PIPELINE = "elevenlabs"
    assert c.patch(f"/api/agents/{pk}", {"voice_id": "Xb7hH8MSUJpSbSDYk0k2"}, format="json").status_code == 200


@pytest.mark.django_db
def test_agent_accepts_blank_voice(member):
    c = member("editor")
    pk = c.post("/api/agents", {"name": "A"}, format="json").json()["id"]
    assert c.patch(f"/api/agents/{pk}", {"voice_id": ""}, format="json").status_code == 200


def test_catalog_matches_agent_copy():
    here = Path(__file__).resolve().parents[1] / "voiceagents" / "voices.json"
    there = Path(__file__).resolve().parents[2] / "agent" / "voices.json"
    assert here.read_bytes() == there.read_bytes()


def test_every_sample_file_exists():
    root = Path(__file__).resolve().parents[2] / "console" / "public"
    for v in voices.for_pipeline("gemini-live") + voices.for_pipeline("elevenlabs"):
        if v["sample"]:
            assert (root / v["sample"].lstrip("/")).is_file()
