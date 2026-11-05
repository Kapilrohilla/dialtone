from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("workspaces.urls")),
    path("api/", include("knowledge.urls")),
    path("api/", include("workflows.urls")),
    path("api/", include("voiceagents.urls")),
    path("api/", include("runtime.urls")),
    path("", include("calls.urls")),
]
