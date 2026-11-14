from django.urls import path, re_path

from . import api, fixes_api

urlpatterns = [
    path("api/calls/<str:room>/audit", api.CallAuditView.as_view()),
    path("api/calls/<str:room>/audit/fixes", fixes_api.CallFixesView.as_view()),
    path("api/agents/<int:pk>/audit-fixes", fixes_api.AgentFixesView.as_view()),
    path("api/audit-fixes/<int:run_id>", fixes_api.FixRunView.as_view()),
    re_path(r"^api/audit-fixes/(?P<run_id>\d+)/(?P<target>agent|workflow)/(?P<item_id>\d+)$",
            fixes_api.FixItemView.as_view()),
    re_path(r"^api/audit-fixes/(?P<run_id>\d+)/(?P<target>agent|workflow)/(?P<item_id>\d+)/accept$",
            fixes_api.AcceptFixView.as_view()),
]
