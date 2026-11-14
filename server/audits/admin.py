from django.contrib import admin

from .models import AgentSuggestion, AuditFixRun, CallAudit


@admin.register(CallAudit)
class CallAuditAdmin(admin.ModelAdmin):
    list_display = ("call", "status", "overall_score", "is_current", "created_at")
    list_filter = ("status", "is_current")
    raw_id_fields = ("call", "agent_version", "workflow_revision", "created_by")


@admin.register(AuditFixRun)
class AuditFixRunAdmin(admin.ModelAdmin):
    list_display = ("id", "agent", "scope", "status", "auto_applied", "created_at")
    list_filter = ("status", "scope")
    raw_id_fields = ("workspace", "agent", "agent_version", "workflow_revision", "call", "created_by")


@admin.register(AgentSuggestion)
class AgentSuggestionAdmin(admin.ModelAdmin):
    list_display = ("id", "agent", "kind", "status", "auto_applied")
    list_filter = ("kind", "status")
    raw_id_fields = ("run", "agent", "decided_by", "included_in")
