from django.urls import re_path

from . import api

urlpatterns = [
    # Matches the other API routes (no trailing slash) and also accepts "instance/".
    re_path(r"^instance/?$", api.InstanceView.as_view()),
    re_path(r"^instance/logo/?$", api.InstanceLogoView.as_view()),
]
