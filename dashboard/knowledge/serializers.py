from rest_framework import serializers

from .models import KnowledgeDocument, KnowledgeRevision


class KnowledgeListSerializer(serializers.ModelSerializer):
    current_revision = serializers.SerializerMethodField()
    used_by = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeDocument
        fields = ["id", "title", "updated_at", "current_revision", "used_by"]

    def get_current_revision(self, obj):
        cur = obj.current
        return cur.number if cur else 0

    def get_used_by(self, obj):
        """Non-archived agents linking this document (annotated by the list view)."""
        count = getattr(obj, "used_by_count", None)
        if count is None:
            count = obj.agents.exclude(status="archived").count()
        return count


class KnowledgeDetailSerializer(KnowledgeListSerializer):
    body_md = serializers.SerializerMethodField()

    class Meta(KnowledgeListSerializer.Meta):
        fields = KnowledgeListSerializer.Meta.fields + ["body_md"]

    def get_body_md(self, obj):
        cur = obj.current
        return cur.body_md if cur else ""


class KnowledgeWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    body_md = serializers.CharField(allow_blank=True, required=False, trim_whitespace=False)


class RevisionSerializer(serializers.ModelSerializer):
    edited_by = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeRevision
        fields = ["number", "edited_by", "created_at"]

    def get_edited_by(self, obj):
        u = obj.edited_by
        return (u.get_full_name() or u.email or u.username) if u else None


class RevisionDetailSerializer(RevisionSerializer):
    class Meta(RevisionSerializer.Meta):
        fields = RevisionSerializer.Meta.fields + ["body_md"]
