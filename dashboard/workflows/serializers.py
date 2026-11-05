from rest_framework import serializers

from .models import Workflow


class WorkflowListSerializer(serializers.ModelSerializer):
    current_revision = serializers.SerializerMethodField()

    class Meta:
        model = Workflow
        fields = ["id", "name", "updated_at", "current_revision"]

    def get_current_revision(self, obj):
        cur = obj.current
        return cur.number if cur else 0


class WorkflowWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    graph = serializers.DictField(required=False)
