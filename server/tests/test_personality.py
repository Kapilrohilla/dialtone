"""Agent personality (KAP-41): API, validation, presets, publish, outdated detection, clone and audit fixes."""
import json
from pathlib import Path

import pytest

from audits.apply import apply_agent_item
from audits.models import AgentSuggestion, AuditFixRun
from tests.test_agents_api import ready
from tests.test_publish import make_agent, make_user
from voiceagents import personality as P
from voiceagents.models import AgentVersion
from voiceagents.publish import build_snapshot, is_outdated, publish
from voiceagents.suggestions import Invalid, current_settings, validate_settings


def patch(c, pk, personality):
    return c.patch(f"/api/agents/{pk}", {"personality": personality}, format="json")


@pytest.mark.django_db
def test_new_agents_get_the_default_personality(member):
    c = member("editor")
    body = c.get(f"/api/agents/{ready(c)}").json()
    assert body["personality"] == {**P.default_personality(), "resolved_gender": "female"}


@pytest.mark.django_db
def test_choosing_a_preset_sets_its_values_and_keeps_the_agents_own(member):
    c = member("editor")
    pk = ready(c)
    assert patch(c, pk, {"description": "Ex-driver from Delhi", "self_gender": "male"}).status_code == 200
    body = patch(c, pk, {"preset": "friendly_dost"}).json()["personality"]
    dost = P.preset("friendly_dost")["values"]
    assert body["preset"] == "friendly_dost" and body["traits"] == dost["traits"]
    assert body["signature_phrases"] == dost["signature_phrases"] and body["pace"] == dost["pace"]
    assert body["description"] == "Ex-driver from Delhi" and body["self_gender"] == "male"


@pytest.mark.django_db
def test_editing_a_value_makes_it_custom_and_reset_restores_the_preset(member):
    c = member("editor")
    pk = ready(c)
    patch(c, pk, {"preset": "calm_professional"})
    body = patch(c, pk, {"traits": {"humour": 3}}).json()["personality"]
    assert body["preset"] == "custom" and body["traits"]["humour"] == 3
    assert body["traits"]["formality"] == 4  # the rest of the preset's values are kept
    body = patch(c, pk, {"preset": "calm_professional"}).json()["personality"]
    assert body["preset"] == "calm_professional" and body["traits"]["humour"] == 1
    # Survives a reload.
    assert c.get(f"/api/agents/{pk}").json()["personality"]["preset"] == "calm_professional"


@pytest.mark.django_db
@pytest.mark.parametrize("bad, field", [
    ({"traits": {"energy": 6}}, "traits"),
    ({"traits": {"energy": True}}, "traits"),
    ({"signature_phrases": ["a", "b", "c", "d", "e", "f"]}, "signature_phrases"),
    ({"signature_phrases": ["x" * 61]}, "signature_phrases"),
    ({"avoid_phrases": [f"p{i}" for i in range(11)]}, "avoid_phrases"),
    ({"description": "x" * 601}, "description"),
    ({"pace": 1.5}, "pace"),
    ({"pace": "1.0"}, "pace"),
    ({"address_style": "boss"}, "address_style"),
    ({"self_gender": "robot"}, "self_gender"),
    ({"disfluencies": "yes"}, "disfluencies"),
    ({"preset": "pirate"}, "preset"),
])
def test_invalid_values_are_rejected_with_field_errors(member, bad, field):
    c = member("editor")
    pk = ready(c)
    r = patch(c, pk, bad)
    assert r.status_code == 400, r.content
    assert field in r.json()["personality"]
    assert c.get(f"/api/agents/{pk}").json()["personality"]["preset"] == "warm_helper"


@pytest.mark.django_db
def test_phrases_are_cleaned(member):
    c = member("editor")
    pk = ready(c)
    body = patch(c, pk, {"signature_phrases": ['  "koi\ntension  nahi" ', "koi tension nahi"]}).json()
    assert body["personality"]["signature_phrases"] == ["koi tension nahi"]
    assert patch(c, pk, {"signature_phrases": [" "]}).status_code == 400


@pytest.mark.django_db
def test_resolved_gender_follows_the_voice_unless_set(member, settings):
    settings.AGENT_PIPELINE = "gemini-live"
    c = member("editor")
    pk = ready(c)
    c.patch(f"/api/agents/{pk}", {"voice_id": "Puck"}, format="json")
    assert c.get(f"/api/agents/{pk}").json()["personality"]["resolved_gender"] == "male"
    assert patch(c, pk, {"self_gender": "neutral"}).json()["personality"]["resolved_gender"] == "neutral"


@pytest.mark.django_db
def test_presets_endpoint(member):
    body = member("viewer").get("/api/personality-presets").json()
    assert [p["id"] for p in body] == P.PRESET_IDS
    assert all(p["name"] and p["summary"] and p["sample"] and p["values"]["traits"] for p in body)


def test_preset_catalog_matches_the_agent_copy():
    here = Path(__file__).resolve().parents[1] / "voiceagents" / "personality_presets.json"
    there = Path(__file__).resolve().parents[2] / "agent" / "personality_presets.json"
    assert json.loads(here.read_text()) == json.loads(there.read_text())


def test_every_preset_is_its_own_match():
    for p in P.PRESETS:
        assert P.merge({}, {"preset": p["id"]})["preset"] == p["id"]


@pytest.mark.django_db
def test_publish_snapshots_the_resolved_personality_and_flags_changes(workspace):
    user = make_user()
    agent = make_agent(workspace, personality={})
    version = publish(agent, user)
    assert version.snapshot["personality"] == P.default_personality()
    agent.refresh_from_db()
    assert is_outdated(agent) is False
    agent.personality = P.merge(agent.personality, {"traits": {"energy": 5}})
    agent.save()
    assert is_outdated(agent) is True
    publish(agent, user)
    agent.refresh_from_db()
    assert agent.published_version.snapshot["personality"]["traits"]["energy"] == 5
    assert is_outdated(agent) is False


@pytest.mark.django_db
def test_versions_from_before_personalities_are_not_outdated(workspace):
    agent = make_agent(workspace)
    publish(agent, make_user())
    agent.refresh_from_db()
    snap = dict(agent.published_version.snapshot)
    snap.pop("personality")
    AgentVersion.objects.filter(pk=agent.published_version_id).update(snapshot=snap)
    agent.refresh_from_db()
    assert is_outdated(agent) is False


@pytest.mark.django_db
def test_duplicate_copies_the_personality(member):
    c = member("editor")
    pk = ready(c)
    patch(c, pk, {"preset": "upbeat_sales", "avoid_phrases": ["sahayata"]})
    copy_ = c.post(f"/api/agents/{pk}/duplicate").json()
    assert copy_["personality"]["preset"] == "upbeat_sales"
    assert copy_["personality"]["avoid_phrases"] == ["sahayata"]


@pytest.mark.django_db
def test_draft_snapshot_carries_the_personality_for_tests_and_the_simulator(workspace):
    agent = make_agent(workspace, personality=P.merge({}, {"preset": "empathetic_support"}))
    assert build_snapshot(agent, 0)["personality"]["preset"] == "empathetic_support"


@pytest.mark.django_db
def test_audit_fixes_can_change_the_personality(workspace):
    agent = make_agent(workspace, personality=P.merge({}, {"preset": "upbeat_sales"}))
    current = current_settings(agent)
    assert current["personality_energy"] == 5 and current["personality_verbosity"] == "normal"
    out = validate_settings({"changes": {"personality_energy": "3", "personality_verbosity": "brief"},
                             "before": {"personality_energy": 5, "personality_verbosity": "normal"}}, agent)
    assert out["changes"] == {"personality_energy": 3, "personality_verbosity": "brief"}
    with pytest.raises(Invalid, match="1 to 5"):
        validate_settings({"changes": {"personality_humour": 9}, "before": {"personality_humour": 3}}, agent)

    user = make_user()
    run = AuditFixRun.objects.create(workspace=workspace, agent=agent, scope="call")
    item = AgentSuggestion.objects.create(run=run, agent=agent, kind=AgentSuggestion.SETTINGS, payload=out)
    apply_agent_item(item, user)
    agent.refresh_from_db()
    assert agent.personality["traits"]["energy"] == 3 and agent.personality["verbosity"] == "brief"
    assert agent.personality["preset"] == "custom"
    assert agent.personality["traits"]["warmth"] == 4  # untouched values stay


@pytest.mark.django_db
def test_call_detail_shows_the_versions_personality(member, workspace):
    from calls.models import Call

    agent = make_agent(workspace, personality=P.merge({}, {"preset": "friendly_dost"}))
    version = publish(agent, make_user())
    old = AgentVersion.objects.create(agent=agent, number=99, snapshot={"name": "old"})
    custom = AgentVersion.objects.create(agent=agent, number=100, snapshot={"personality": {"preset": "custom"}})
    for room, v in (("p1", version), ("p0", old), ("p2", custom), ("p3", None)):
        Call.objects.create(room=room, workspace=workspace, agent_version=v)
    c = member("viewer")
    assert c.get("/api/calls/p1").json()["agent_personality"] == "Friendly Dost"
    assert c.get("/api/calls/p2").json()["agent_personality"] == "Custom"
    assert c.get("/api/calls/p0").json()["agent_personality"] is None
    assert c.get("/api/calls/p3").json()["agent_personality"] is None
