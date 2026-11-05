from django.urls import path

from . import api

urlpatterns = [
    path("auth/csrf", api.CsrfView.as_view()),
    path("auth/login", api.LoginView.as_view()),
    path("auth/logout", api.LogoutView.as_view()),
    path("auth/set-password", api.SetPasswordView.as_view()),
    path("me", api.MeView.as_view()),
    path("me/password", api.MePasswordView.as_view()),
    path("team", api.TeamView.as_view()),
    path("team/<int:pk>", api.TeamMemberView.as_view()),
]
