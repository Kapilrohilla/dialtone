from rest_framework import serializers

from calls.numbers import strip_nul
from workspaces.serializers import StrictBooleanField

from .models import Workflow


class WorkflowListSerializer(serializers.ModelSerializer):
    current_revision = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = ["id", "name", "updated_at", "current_revision", "dead_air_enabled"]

    def get_current_revision(self, obj):
        cur = obj.current
        return cur.number if cur else 0


class WorkflowWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    graph = serializers.DictField(required=False)
    dead_air_enabled = StrictBooleanField(required=False)

    def validate_graph(self, value):
        return strip_nul(value)  # Postgres jsonb rejects NUL; the graph is checked for errors after saving
