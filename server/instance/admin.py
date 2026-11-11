from django.contrib import admin

from .models import InstanceSettings


@admin.register(InstanceSettings)
class InstanceSettingsAdmin(admin.ModelAdmin):
    list_display = ["project_name", "updated_by", "updated_at"]
    readonly_fields = ["updated_by", "updated_at"]

    def has_add_permission(self, request):
        return not InstanceSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
