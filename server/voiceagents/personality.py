"""Agent personality (KAP-41): validation, partial updates and the preset catalogue.

The server only stores and snapshots the personality; the agent worker compiles it into the prompt
(agent/personality.py). personality_presets.json is shared with the worker (agent/personality_presets.json is a
copy; a test keeps them equal).

A stored personality is always fully resolved: every field present, so a later change to a preset never changes
an agent or a published version. An empty value ({}, what the migration backfills) means the default preset.
"""
import copy
import json
import re
from pathlib import Path

from rest_framework import serializers

from calls.numbers import strip_nul

from . import voices

PRESETS: list[dict] = json.loads((Path(__file__).parent / "personality_presets.json").read_text())
PRESET_IDS = [p["id"] for p in PRESETS]
DEFAULT_PRESET = "warm_helper"
CUSTOM = "custom"

TRAITS = ("warmth", "energy", "formality", "humour", "directness", "empathy")
SELF_GENDERS = ("auto", "female", "male", "neutral")
ADDRESS_STYLES = ("sir_maam", "ji", "first_name", "none")
BACKCHANNELS = ("minimal", "natural", "expressive")
VERBOSITIES = ("brief", "normal", "explanatory")
# The fields a preset sets; self_gender, avoid_phrases and description are the agent's own and survive a preset.
PRESET_FIELDS = ("traits", "address_style", "backchannels", "disfluencies", "verbosity", "pace", "signature_phrases")

MAX_SIGNATURE_PHRASES = 5
MAX_AVOID_PHRASES = 10
MAX_PHRASE_CHARS = 60
MAX_DESCRIPTION_CHARS = 600
MIN_PACE, MAX_PACE = 0.85, 1.15

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def preset(preset_id: str) -> dict | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)


def default_personality() -> dict:
    values = copy.deepcopy(preset(DEFAULT_PRESET)["values"])
    return {"preset": DEFAULT_PRESET, "self_gender": "auto", **values, "avoid_phrases": [], "description": ""}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _CONTROL.sub(" ", strip_nul(text))).strip()


class PhraseField(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("Each phrase must be text.")
        return super().to_internal_value(_clean(data).strip('"'))


class TraitsSerializer(serializers.Serializer):
    warmth = serializers.IntegerField(min_value=1, max_value=5)
    energy = serializers.IntegerField(min_value=1, max_value=5)
    formality = serializers.IntegerField(min_value=1, max_value=5)
    humour = serializers.IntegerField(min_value=1, max_value=5)
    directness = serializers.IntegerField(min_value=1, max_value=5)
    empathy = serializers.IntegerField(min_value=1, max_value=5)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            for key in TRAITS:
                if isinstance(data.get(key), bool) or not isinstance(data.get(key, 0), int):
                    raise serializers.ValidationError({key: ["Must be a whole number from 1 to 5."]})
        return super().to_internal_value(data)


class PersonalitySerializer(serializers.Serializer):
    preset = serializers.ChoiceField(choices=PRESET_IDS + [CUSTOM])
    self_gender = serializers.ChoiceField(choices=SELF_GENDERS)
    traits = TraitsSerializer()
    address_style = serializers.ChoiceField(choices=ADDRESS_STYLES)
    backchannels = serializers.ChoiceField(choices=BACKCHANNELS)
    disfluencies = serializers.BooleanField()
    verbosity = serializers.ChoiceField(choices=VERBOSITIES)
    signature_phrases = serializers.ListField(
        child=PhraseField(max_length=MAX_PHRASE_CHARS, allow_blank=False), max_length=MAX_SIGNATURE_PHRASES)
    avoid_phrases = serializers.ListField(
        child=PhraseField(max_length=MAX_PHRASE_CHARS, allow_blank=False), max_length=MAX_AVOID_PHRASES)
    description = serializers.CharField(max_length=MAX_DESCRIPTION_CHARS, allow_blank=True, trim_whitespace=True)
    pace = serializers.FloatField(min_value=MIN_PACE, max_value=MAX_PACE)

    def validate_disfluencies(self, value):
        if not isinstance(self.initial_data.get("disfluencies"), bool):
            raise serializers.ValidationError("Must be true or false.")
        return value

    def validate_pace(self, value):
        if isinstance(self.initial_data.get("pace"), (bool, str)):
            raise serializers.ValidationError("Must be a number.")
        return value

    def validate_description(self, value):
        return strip_nul(value).replace("\x00", "")


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _matches(values: dict, preset_id: str) -> bool:
    p = preset(preset_id)
    return p is not None and all(values.get(f) == p["values"][f] for f in PRESET_FIELDS)


def resolve(stored) -> dict:
    """A stored (or snapshotted) personality with every field present; {} or anything malformed is the
    default. Lenient: used on reads, where a bad value must never break the page or a publish."""
    base = default_personality()
    if not isinstance(stored, dict) or not stored:
        return base
    try:
        return _apply(base, stored)
    except serializers.ValidationError:
        return base


def merge(current, incoming) -> dict:
    """Apply a partial personality update over the current one and validate the result.

    Choosing a preset (``{"preset": "friendly_dost"}``) sets that preset's values; other fields in the same
    update are applied on top. Changing any preset value makes the personality "custom" unless the result still
    matches its preset exactly. ``{"preset": "custom"}`` alone keeps the values. Raises ValidationError keyed by
    "personality"."""
    if not isinstance(incoming, dict):
        raise serializers.ValidationError({"personality": ["Personality must be an object."]})
    return _apply(resolve(current), incoming)


def _apply(base: dict, incoming: dict) -> dict:
    chosen = incoming.get("preset")
    if isinstance(chosen, str) and chosen != CUSTOM and preset(chosen) is not None:
        base.update(copy.deepcopy(preset(chosen)["values"]))
        base["preset"] = chosen
    elif chosen is not None and chosen != CUSTOM:
        raise serializers.ValidationError({"personality": {"preset": ["Choose a preset from the list."]}})
    for key, value in incoming.items():
        if key == "preset":
            continue
        if key == "traits" and isinstance(value, dict):
            base["traits"] = {**base["traits"], **value}
        else:
            base[key] = value
    s = PersonalitySerializer(data=base)
    if not s.is_valid():
        raise serializers.ValidationError({"personality": s.errors})
    out = dict(s.validated_data)
    out["traits"] = dict(out["traits"])
    out["signature_phrases"] = _dedupe(out["signature_phrases"])
    out["avoid_phrases"] = _dedupe(out["avoid_phrases"])
    out["pace"] = round(out["pace"], 2)
    if out["preset"] != CUSTOM and not _matches(out, out["preset"]):
        out["preset"] = CUSTOM
    return out


def resolved_gender(personality: dict, voice_id: str, pipeline: str) -> str:
    """The gender the agent speaks as: its own setting, or with "auto" the chosen voice's (female when the
    voice isn't in the catalog, like the worker's default voices)."""
    chosen = personality.get("self_gender")
    if chosen in ("female", "male", "neutral"):
        return chosen
    catalog = voices.for_pipeline(pipeline)
    voice = next((v for v in catalog if v["id"] == voice_id), None) or (catalog[0] if catalog else None)
    return voice.get("gender", "female") if voice else "female"


def presets_payload() -> list[dict]:
    return copy.deepcopy(PRESETS)
