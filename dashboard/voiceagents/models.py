from django.conf import settings as django_settings
from django.db import models
from django.db.models import Q


def default_settings():
    return {
        "mood_adaptation": True,
        "dead_air": {"enabled": True, "nudge_s": 4, "second_nudge_s": 9, "hang_up_s": 15},
    }


class Agent(models.Model):
    DRAFT, PUBLISHED, ARCHIVED = "draft", "published", "archived"
    STATUSES = [(DRAFT, "Draft"), (PUBLISHED, "Published"), (ARCHIVED, "Archived")]

    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="agents")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUSES, default=DRAFT)
    phone_number = models.CharField(max_length=32, blank=True, default="")
    language = models.CharField(max_length=60, default="Hindi + Hinglish")
    persona_name = models.CharField(max_length=60, default="Priya")
    voice_id = models.CharField(max_length=120, blank=True, default="")
    settings = models.JSONField(default=default_settings)
    script = models.JSONField(default=list)  # [{"id", "title", "body"}]
    custom_expressions = models.JSONField(default=dict)  # {name: hint}
    knowledge = models.ManyToManyField("knowledge.KnowledgeDocument", blank=True, related_name="agents")
    workflow = models.ForeignKey(
        "workflows.Workflow", null=True, blank=True, on_delete=models.SET_NULL, related_name="agents"
    )
    # Set while status == published; the version callers get.
    published_version = models.ForeignKey(
        "AgentVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            # Backstop for publish(): at most one published agent per workspace.
            models.UniqueConstraint(
                fields=["workspace"], condition=Q(status="published"), name="one_published_agent_per_workspace"
            ),
        ]

    def __str__(self):
        return self.name


class AgentVersion(models.Model):
    """Immutable snapshot taken on publish; what the runtime serves."""

    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    snapshot = models.JSONField()
    published_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["agent", "number"], name="uniq_agent_version")]

    def __str__(self):
        return f"{self.agent} v{self.number}"
