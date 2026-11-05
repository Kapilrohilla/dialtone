from django.contrib import admin

from .models import Agent, AgentVersion

admin.site.register(Agent)


@admin.register(AgentVersion)
class AgentVersionAdmin(admin.ModelAdmin):
    """Versions are immutable snapshots of what callers heard: view only."""

    list_display = ["agent", "number", "published_by", "published_at"]
    readonly_fields = ["agent", "number", "snapshot", "published_by", "published_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
