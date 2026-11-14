from django.urls import path

from . import api

urlpatterns = [
    path("runtime/config", api.config, name="runtime_config"),
    path("runtime/events", api.events, name="runtime_events"),
]
