from django.conf import settings
from django.db import models

from .lists import system_codes


class DispositionList(models.Model):
    """A set of outcomes the AI picks one of at the end of a call; one list per agent (Agent.disposition_list)."""

    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="disposition_lists")
    name = models.CharField(max_length=80)
    # [{"code", "name", "description", "group", "fields": [{"key", "label", "type", "required"}]}], in order.
    items = models.JSONField(default=list)
    fallback_code = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name

    @property
    def system_codes(self) -> dict:
        return system_codes(self.items, self.fallback_code)
