from django.urls import path

from . import api, simulate

urlpatterns = [
    path("agents", api.AgentListView.as_view()),
    path("agents/<int:pk>", api.AgentDetailView.as_view()),
    path("agents/<int:pk>/publish", api.AgentPublishView.as_view()),
    path("agents/<int:pk>/unpublish", api.AgentUnpublishView.as_view()),
    path("agents/<int:pk>/duplicate", api.AgentDuplicateView.as_view()),
    path("agents/<int:pk>/archive", api.AgentArchiveView.as_view()),
    path("agents/<int:pk>/restore", api.AgentRestoreView.as_view()),
    path("agents/<int:pk>/versions", api.AgentVersionsView.as_view()),
    path("agents/<int:pk>/simulate", simulate.AgentSimulateView.as_view()),
    path("workflows/<int:pk>/simulate", simulate.WorkflowSimulateView.as_view()),
    path("expressions", api.ExpressionsView.as_view()),
]
