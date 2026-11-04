from django.urls import path

from . import views

# Same paths as the aiohttp dashboard: LiveKit posts to /webhook (docker-compose.yml).
urlpatterns = [
    path("", views.index, name="index"),
    path("api/state", views.state, name="state"),
    path("webhook", views.webhook, name="webhook"),
    path("api/report", views.report_ingest, name="report_ingest"),
    path("api/report/<str:room>", views.report_detail, name="report_detail"),
]
