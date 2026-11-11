from django.urls import path

from . import api

urlpatterns = [
    path("knowledge", api.KnowledgeListView.as_view()),
    path("knowledge/upload", api.KnowledgeUploadView.as_view()),
    path("knowledge/<int:pk>", api.KnowledgeDetailView.as_view()),
    path("knowledge/<int:pk>/revisions", api.RevisionListView.as_view()),
    path("knowledge/<int:pk>/revisions/<int:number>", api.RevisionDetailView.as_view()),
]
