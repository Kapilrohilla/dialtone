from django.contrib import admin

from .models import Membership, UserPreference, Workspace

admin.site.register(Workspace)
admin.site.register(Membership)
admin.site.register(UserPreference)
