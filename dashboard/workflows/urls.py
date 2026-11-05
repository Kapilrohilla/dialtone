from django.urls import path

from . import api

urlpatterns = [
    path("workflows", api.WorkflowListView.as_view()),
    path("workflows/<int:pk>", api.WorkflowDetailView.as_view()),
    path("workflows/<int:pk>/validate", api.WorkflowValidateView.as_view()),
]
