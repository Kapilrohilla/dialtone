from django.core.exceptions import PermissionDenied
from rest_framework import permissions

from .models import Membership

EDIT_ROLES = {Membership.EDITOR, Membership.ADMIN, Membership.OWNER}
TEAM_ROLES = {Membership.ADMIN, Membership.OWNER}


def _membership(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    cached = getattr(request, "_membership_cache", False)
    if cached is False:
        cached = Membership.objects.select_related("workspace").filter(user=user).first()
        request._membership_cache = cached
    return cached


def workspace_for(request):
    """The requester's single workspace; PermissionDenied if they belong to none."""
    membership = _membership(request)
    if membership is None:
        raise PermissionDenied("No workspace membership")
    return membership.workspace


class IsMember(permissions.BasePermission):
    def has_permission(self, request, view):
        return _membership(request) is not None


class CanEdit(permissions.BasePermission):
    def has_permission(self, request, view):
        m = _membership(request)
        return m is not None and m.role in EDIT_ROLES


class CanManageTeam(permissions.BasePermission):
    def has_permission(self, request, view):
        m = _membership(request)
        return m is not None and m.role in TEAM_ROLES


class WorkspaceScopedMixin:
    """For viewsets whose model has a `workspace` FK."""

    def get_queryset(self):
        return super().get_queryset().filter(workspace=workspace_for(self.request))

    def perform_create(self, serializer):
        serializer.save(workspace=workspace_for(self.request))
