from django.urls import path

from . import api, views

# Same paths as the aiohttp dashboard: LiveKit posts to /webhook (docker-compose.yml).
urlpatterns = [
    path("", views.index, name="index"),
    path("api/state", views.state, name="state"),
    path("webhook", views.webhook, name="webhook"),
    path("api/report", views.report_ingest, name="report_ingest"),
    path("api/report/<str:room>", views.report_detail, name="report_detail"),
]

# Console API (Task 8). export.csv comes before <room> so it isn't read as a room name.
urlpatterns += [
    path("api/calls", api.CallListView.as_view()),
    path("api/calls/export.csv", api.CallExportView.as_view()),
    path("api/calls/<str:room>", api.CallDetailView.as_view()),
    path("api/calls/<str:room>/needs-person", api.NeedsPersonView.as_view()),
    path("api/live", api.LiveListView.as_view()),
    path("api/live/<str:room>/transfer", api.LiveTransferView.as_view()),
    path("api/live/<str:room>/end", api.LiveEndView.as_view()),
    path("api/dashboard", api.DashboardView.as_view()),
    path("api/phone-numbers", api.PhoneNumbersView.as_view()),
]
