from django.urls import path

from . import api

urlpatterns = [
    path("api/calls/<str:room>/audit", api.CallAuditView.as_view()),
]
