import json

from django.contrib import admin
from django.utils.html import format_html

from .models import Call, CallReport


class CallReportInline(admin.StackedInline):
    model = CallReport
    can_delete = False
    extra = 0
    max_num = 0
    fields = ("disposition", "final_mood", "worst_mood", "avg_sentiment", "dead_air_nudges",
              "llm_ttft_p50_ms", "received_at", "report_json")
    readonly_fields = fields

    @admin.display(description="Report")
    def report_json(self, obj):
        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(obj.data, indent=2, ensure_ascii=False))

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
    list_display = ("room", "caller", "started_at", "ended_at", "end_reason", "disposition", "final_mood")
    list_filter = ("report__final_mood", "report__disposition")
    search_fields = ("caller", "room")
    date_hierarchy = "started_at"
    inlines = [CallReportInline]
    list_select_related = ("report",)

    @admin.display(ordering="report__disposition")
    def disposition(self, obj):
        return getattr(getattr(obj, "report", None), "disposition", "") or "–"

    @admin.display(ordering="report__final_mood")
    def final_mood(self, obj):
        return getattr(getattr(obj, "report", None), "final_mood", "") or "–"
