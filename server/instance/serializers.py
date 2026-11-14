from rest_framework import serializers

from .models import PROJECT_NAME_MAX


class InstanceSerializer(serializers.Serializer):
    # trim_whitespace (the default) strips first, so whitespace-only counts as blank.
    project_name = serializers.CharField(max_length=PROJECT_NAME_MAX, allow_blank=False)
