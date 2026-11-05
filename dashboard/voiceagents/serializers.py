import re

from rest_framework import serializers

from calls.numbers import strip_nul

from .models import Agent, AgentVersion, default_settings
from .publish import is_outdated
from .tokens import BUILTIN_EXPRESSIONS

EXPR_NAME_RE = re.compile(r"^[a-z_]{1,32}$")  # same alphabet the token parser accepts
MAX_SECTIONS = 100
MAX_CUSTOM_EXPRESSIONS = 50


def display_name(user):
    return (user.first_name or user.email or user.username) if user else None


class AgentListSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()
    is_outdated = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = ["id", "name", "description", "status", "phone_number", "updated_at", "updated_by_name",
                  "is_outdated"]

    def get_updated_by_name(self, obj):
        return display_name(obj.updated_by)

    def get_is_outdated(self, obj):
        return is_outdated(obj)


class AgentListItemSerializer(AgentListSerializer):
    """A row of GET /api/agents; the queryset must annotate `calls_this_week`."""

    calls_this_week = serializers.IntegerField(read_only=True)

    class Meta(AgentListSerializer.Meta):
        fields = AgentListSerializer.Meta.fields + ["calls_this_week"]


class AgentDetailSerializer(AgentListSerializer):
    knowledge = serializers.SerializerMethodField()
    workflow = serializers.PrimaryKeyRelatedField(read_only=True)
    published_version = serializers.SerializerMethodField()

    class Meta(AgentListSerializer.Meta):
        fields = AgentListSerializer.Meta.fields + [
            "language", "persona_name", "voice_id", "settings", "script", "custom_expressions",
            "knowledge", "workflow", "published_version", "created_at",
        ]

    def get_knowledge(self, obj):
        return sorted(obj.knowledge.values_list("id", flat=True))

    def get_published_version(self, obj):
        return obj.published_version.number if obj.published_version_id else None


class AgentVersionSerializer(serializers.ModelSerializer):
    published_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AgentVersion
        fields = ["number", "published_by_name", "published_at"]

    def get_published_by_name(self, obj):
        return display_name(obj.published_by)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if not isinstance(data, bool):
            raise serializers.ValidationError("Must be true or false.")
        return data


class StrictIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, int):
            raise serializers.ValidationError("Must be a whole number of seconds.")
        return super().to_internal_value(data)


class DeadAirSerializer(serializers.Serializer):
    enabled = StrictBooleanField()
    nudge_s = StrictIntegerField(min_value=1, max_value=300)
    second_nudge_s = StrictIntegerField(min_value=1, max_value=300)
    hang_up_s = StrictIntegerField(min_value=1, max_value=600)

    def validate(self, d):
        if not d["nudge_s"] < d["second_nudge_s"] < d["hang_up_s"]:
            raise serializers.ValidationError(
                "Dead-air timings must increase: first check-in, then second check-in, then hang up."
            )
        return d


class SettingsSerializer(serializers.Serializer):
    mood_adaptation = StrictBooleanField()
    dead_air = DeadAirSerializer()


def merge_settings(current, incoming):
    """Deep-merge a partial settings payload over the current settings and validate the result."""
    if not isinstance(incoming, dict):
        raise serializers.ValidationError({"settings": ["Settings must be an object."]})
    base = default_settings()
    if isinstance(current, dict):
        base.update({k: v for k, v in current.items() if k in base})
        if isinstance(current.get("dead_air"), dict):
            base["dead_air"] = {**default_settings()["dead_air"], **current["dead_air"]}
    for key, value in incoming.items():
        if key == "dead_air" and isinstance(value, dict):
            base["dead_air"] = {**base["dead_air"], **value}
        else:
            base[key] = value
    s = SettingsSerializer(data=base)
    if not s.is_valid():
        raise serializers.ValidationError({"settings": s.errors})
    return {"mood_adaptation": s.validated_data["mood_adaptation"], "dead_air": dict(s.validated_data["dead_air"])}


class AgentWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    phone_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    language = serializers.CharField(max_length=60, required=False)
    persona_name = serializers.CharField(max_length=60, required=False)
    voice_id = serializers.CharField(max_length=120, required=False, allow_blank=True)
    settings = serializers.JSONField(required=False)
    script = serializers.JSONField(required=False)
    custom_expressions = serializers.JSONField(required=False)
    knowledge = serializers.ListField(child=serializers.IntegerField(), required=False, max_length=200)
    workflow = serializers.IntegerField(required=False, allow_null=True)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A name is required.")
        return value

    def validate_script(self, value):
        value = strip_nul(value)  # Postgres jsonb rejects NUL; strip it like other free text
        if not isinstance(value, list):
            raise serializers.ValidationError("The script must be a list of sections.")
        if len(value) > MAX_SECTIONS:
            raise serializers.ValidationError(f"A script can have at most {MAX_SECTIONS} sections.")
        out, ids = [], set()
        for s in value:
            if not (isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]
                    and isinstance(s.get("title"), str) and isinstance(s.get("body"), str)):
                raise serializers.ValidationError("Every section needs an id, a title and a body, all text.")
            if len(s["title"]) > 200:
                raise serializers.ValidationError("Section titles can be at most 200 characters.")
            if s["id"] in ids:
                raise serializers.ValidationError(f'Two sections share the id "{s["id"]}".')
            ids.add(s["id"])
            out.append({"id": s["id"], "title": s["title"], "body": s["body"]})
        return out

    def validate_custom_expressions(self, value):
        value = strip_nul(value)
        if not isinstance(value, dict):
            raise serializers.ValidationError("Custom expressions must be an object of name to hint.")
        if len(value) > MAX_CUSTOM_EXPRESSIONS:
            raise serializers.ValidationError(f"At most {MAX_CUSTOM_EXPRESSIONS} custom expressions.")
        out = {}
        for name, hint in value.items():
            if not EXPR_NAME_RE.match(name):
                raise serializers.ValidationError(
                    f'"{name}" is not a valid expression name: use lowercase letters and underscores.'
                )
            if name in BUILTIN_EXPRESSIONS:
                raise serializers.ValidationError(f'"{name}" is a built-in expression; pick another name.')
            if not isinstance(hint, str) or not hint.strip() or len(hint) > 200:
                raise serializers.ValidationError(f'Expression "{name}" needs a hint of up to 200 characters.')
            out[name] = hint.strip()
        return out
