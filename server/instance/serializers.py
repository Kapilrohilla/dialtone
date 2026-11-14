from rest_framework import serializers

from .models import PROJECT_NAME_MAX, THEME_CHOICES


class InstanceSerializer(serializers.Serializer):
    """GET: everything. PATCH: any of project_name and theme (at least one). The logo has its own endpoint."""

    # trim_whitespace (the default) strips first, so whitespace-only counts as blank.
    project_name = serializers.CharField(max_length=PROJECT_NAME_MAX, allow_blank=False, required=False)
    theme = serializers.ChoiceField(choices=THEME_CHOICES, required=False)
    logo_url = serializers.CharField(read_only=True, allow_null=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Send project_name or theme.")
        return attrs


class LogoUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="PNG, SVG or JPG, square, up to 1 MB.")
