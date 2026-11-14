from django.contrib import admin

from .models import Workflow, WorkflowRevision, WorkflowSuggestion, WorkflowSuggestionSet

admin.site.register(Workflow)
admin.site.register(WorkflowRevision)
admin.site.register(WorkflowSuggestionSet)
admin.site.register(WorkflowSuggestion)
