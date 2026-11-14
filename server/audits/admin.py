from django.contrib import admin

from .models import CallAudit


@admin.register(CallAudit)
class CallAuditAdmin(admin.ModelAdmin):
    list_display = ("call", "status", "overall_score", "is_current", "created_at")
    list_filter = ("status", "is_current")
    raw_id_fields = ("call", "agent_version", "workflow_revision", "created_by")
