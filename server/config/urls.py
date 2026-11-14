from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/", include("instance.urls")),
    path("api/", include("workspaces.urls")),
    path("api/", include("knowledge.urls")),
    path("api/", include("workflows.urls")),
    path("api/", include("voiceagents.urls")),
    path("api/", include("runtime.urls")),
    path("", include("audits.urls")),
    path("", include("calls.urls")),
]
