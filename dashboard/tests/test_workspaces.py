import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets

from workspaces.models import Membership, UserPreference, Workspace
from workspaces.permissions import CanEdit, CanManageTeam, WorkspaceScopedMixin, workspace_for

pytestmark = pytest.mark.django_db


def test_data_migration_creates_carrum():
    ws = Workspace.objects.get(slug="carrum")
    assert ws.name == "Carrum Mobility"
    assert Workspace.objects.filter(slug="carrum").count() == 1


def _request(user):
    request = APIRequestFactory().get("/x")
    request.user = user
    return request


def test_workspace_for_returns_membership_workspace(member, workspace):
    client = member("viewer")
    assert workspace_for(_request(client.user)) == workspace


def test_workspace_for_raises_without_membership():
    user = get_user_model().objects.create_user(username="x", password="pw")
    with pytest.raises(PermissionDenied):
        workspace_for(_request(user))


def test_user_without_membership_is_denied():
    class Ping(APIView):
        def get(self, request):
            return Response({"ok": True})

    user = get_user_model().objects.create_user(username="nomember", password="pw")
    request = APIRequestFactory().get("/ping")
    force_authenticate(request, user=user)
    assert Ping.as_view()(request).status_code == 403


def test_member_is_allowed_through_default_permissions(member):
    class Ping(APIView):
        def get(self, request):
            return Response({"ok": True})

    client = member("viewer")
    request = APIRequestFactory().get("/ping")
    force_authenticate(request, user=client.user)
    assert Ping.as_view()(request).status_code == 200


@pytest.mark.parametrize("role,can_edit,can_manage", [
    ("viewer", False, False), ("editor", True, False), ("admin", True, True), ("owner", True, True),
])
def test_role_permissions(member, role, can_edit, can_manage):
    request = _request(member(role).user)
    assert CanEdit().has_permission(request, None) is can_edit
    assert CanManageTeam().has_permission(request, None) is can_manage


def test_scoped_mixin_excludes_other_workspace(member, workspace, other_workspace):
    client = member("editor")
    outsider = get_user_model().objects.create_user(username="out", password="pw")
    Membership.objects.create(user=outsider, workspace=other_workspace, role="viewer")

    class V(WorkspaceScopedMixin, viewsets.ReadOnlyModelViewSet):
        queryset = Membership.objects.all()

    view = V()
    view.request = _request(client.user)
    users = {m.user_id for m in view.get_queryset()}
    assert users == {client.user.id}
    assert outsider.id not in users


def test_scoped_mixin_perform_create_sets_workspace(member, workspace):
    client = member("editor")
    new_user = get_user_model().objects.create_user(username="n", password="pw")

    class S:
        def save(self, **kw):
            self.kw = kw

    class V(WorkspaceScopedMixin, viewsets.ModelViewSet):
        queryset = Membership.objects.all()

    view = V()
    view.request = _request(client.user)
    s = S()
    view.perform_create(s)
    assert s.kw == {"workspace": workspace}


def test_membership_unique_per_workspace(member, workspace):
    from django.db import IntegrityError

    client = member("viewer")
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=client.user, workspace=workspace, role="admin")


def test_user_preference_defaults():
    user = get_user_model().objects.create_user(username="p", password="pw")
    pref = UserPreference.objects.create(user=user)
    assert (pref.appearance, pref.notify_needs_person, pref.notify_daily_summary, pref.time_zone, pref.phone) == (
        "system", True, False, "Asia/Kolkata", "")
