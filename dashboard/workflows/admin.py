from django.contrib import admin

from .models import Workflow, WorkflowRevision

admin.site.register(Workflow)
admin.site.register(WorkflowRevision)
