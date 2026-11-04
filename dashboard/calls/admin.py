from django.contrib import admin

from .models import Call


@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
    list_display = ("room", "caller", "started_at", "ended_at", "end_reason")
    search_fields = ("caller", "room")
    date_hierarchy = "started_at"
