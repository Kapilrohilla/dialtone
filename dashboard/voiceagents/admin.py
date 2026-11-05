from django.contrib import admin

from .models import Agent, AgentVersion

admin.site.register(Agent)
admin.site.register(AgentVersion)
