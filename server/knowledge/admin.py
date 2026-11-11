from django.contrib import admin

from .models import KnowledgeDocument, KnowledgeRevision

admin.site.register(KnowledgeDocument)
admin.site.register(KnowledgeRevision)
