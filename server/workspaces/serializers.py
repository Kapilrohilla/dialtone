from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Membership, UserPreference

User = get_user_model()
PREF_FIELDS = ["appearance", "notify_needs_person", "notify_daily_summary", "time_zone"]


class StrictBooleanField(serializers.BooleanField):
    """true or false only: DRF's BooleanField would also take "false", 0 or "no"."""

    def to_internal_value(self, data):
        if not isinstance(data, bool):
            raise serializers.ValidationError("Must be true or false.")
        return data


class PreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = PREF_FIELDS


AUDIT_SAMPLE_PCTS = (100, 50, 25, 10)


def workspace_payload(ws):
    from audits.rubric import weights_for

    return {"id": ws.id, "name": ws.name, "slug": ws.slug, "dead_air_enabled": ws.dead_air_enabled,
            "recording_enabled": ws.recording_enabled, "audit_enabled": ws.audit_enabled,
            "audit_sample_pct": ws.audit_sample_pct, "audit_weights": weights_for(ws),
            "audit_instructions": ws.audit_instructions}


class WorkspaceUpdateSerializer(serializers.Serializer):
    dead_air_enabled = StrictBooleanField(required=False)
    recording_enabled = StrictBooleanField(required=False)
    audit_enabled = StrictBooleanField(required=False)
    audit_sample_pct = serializers.ChoiceField(choices=AUDIT_SAMPLE_PCTS, required=False)
    audit_weights = serializers.DictField(required=False)
    audit_instructions = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate_audit_sample_pct(self, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise serializers.ValidationError("Choose 100, 50, 25 or 10.")
        return value

    def validate_audit_weights(self, value):
        from audits.rubric import AREA_KEYS

        out = {}
        for key, weight in value.items():
            if key not in AREA_KEYS:
                raise serializers.ValidationError(f'"{key}" isn\'t a rubric area.')
            if isinstance(weight, bool) or not isinstance(weight, int) or not 0 <= weight <= 100:
                raise serializers.ValidationError("Each weight must be a whole number from 0 to 100.")
            out[key] = weight
        if out and not any(out.values()) and len(out) == len(AREA_KEYS):
            raise serializers.ValidationError("At least one area needs a weight above 0.")
        return out


def me_payload(user, membership):
    pref, _ = UserPreference.objects.get_or_create(user=user)
    ws = membership.workspace
    return {
        "id": user.id,
        "name": user.get_full_name() or user.first_name,
        "email": user.email,
        "phone": pref.phone,
        "role": membership.role,
        "is_superuser": bool(user.is_superuser),  # may edit instance-wide settings (/api/instance)
        "workspace": workspace_payload(ws),
        "preferences": PreferencesSerializer(pref).data,
    }


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


class MeUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False, allow_blank=False)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    preferences = PreferencesSerializer(required=False, partial=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()

    def validate_current_password(self, value):
        if not self.context["user"].check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["user"])
        return value


class SetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField()


class TeamMemberSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="user.id", read_only=True)
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "name", "email", "role", "last_login"]

    def get_name(self, obj):
        return obj.user.get_full_name() or obj.user.first_name


class InviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(choices=[r for r, _ in Membership.ROLES])

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[r for r, _ in Membership.ROLES])


class IntegrationRequestSerializer(serializers.Serializer):
    tool = serializers.CharField(max_length=100)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
