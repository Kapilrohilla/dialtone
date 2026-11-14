import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from workspaces.models import Membership

User = get_user_model()
PW = "pw-test-12345"


@pytest.fixture
def user(workspace):
    u = User.objects.create_user(username="Asha@Example.com", email="Asha@Example.com", password=PW, first_name="Asha")
    Membership.objects.create(user=u, workspace=workspace, role="owner")
    return u


def test_login_by_email_sets_session(user):
    c = APIClient()
    r = c.post("/api/auth/login", {"email": "asha@example.COM", "password": PW}, format="json")
    assert r.status_code == 200
    assert r.json()["email"].lower() == "asha@example.com"
    assert c.get("/api/me").status_code == 200


def test_login_wrong_password_400_message(user):
    r = APIClient().post("/api/auth/login", {"email": "asha@example.com", "password": "nope"}, format="json")
    assert r.status_code == 400
    assert r.json() == {"detail": "Wrong email or password."}


def test_logout_and_csrf_endpoint(user):
    c = APIClient()
    assert c.get("/api/auth/csrf").status_code == 204
    assert "csrftoken" in c.cookies
    c.force_login(user)
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/me").status_code in (401, 403)


def test_me_shape(member):
    c = member("admin")
    body = c.get("/api/me").json()
    assert set(body) == {"id", "name", "email", "phone", "role", "is_superuser", "workspace", "preferences"}
    assert body["is_superuser"] is False
    assert set(body["workspace"]) == {"id", "name", "slug", "dead_air_enabled", "recording_enabled", "audit_enabled",
                                      "audit_sample_pct", "audit_weights", "audit_instructions",
                                      "audit_fix_auto_apply"}
    assert set(body["preferences"]) == {"appearance", "notify_needs_person", "notify_daily_summary", "time_zone"}
    assert body["role"] == "admin"
    assert body["workspace"]["slug"] == "northwind"


def test_patch_appearance_dark(member):
    c = member()
    r = c.patch("/api/me", {"name": "New Name", "phone": "+911234", "preferences": {"appearance": "dark"}}, format="json")
    assert r.status_code == 200
    body = r.json()
    assert body["preferences"]["appearance"] == "dark"
    assert body["name"] == "New Name" and body["phone"] == "+911234"
    assert c.get("/api/me").json()["preferences"]["appearance"] == "dark"


def test_change_password_validates(member):
    c = member()
    r = c.post("/api/me/password", {"current_password": PW, "new_password": "123"}, format="json")
    assert r.status_code == 400 and r.json()["new_password"]
    r = c.post("/api/me/password", {"current_password": "wrong", "new_password": "a-Better-pw-98765"}, format="json")
    assert r.status_code == 400
    r = c.post("/api/me/password", {"current_password": PW, "new_password": "a-Better-pw-98765"}, format="json")
    assert r.status_code == 204
    # session survives the change
    assert c.get("/api/me").status_code == 200
    c.user.refresh_from_db()
    assert c.user.check_password("a-Better-pw-98765")


def test_team_list(member):
    c = member("viewer")
    rows = c.get("/api/team").json()
    assert set(rows[0]) == {"id", "name", "email", "role", "last_login"}


def test_invite_requires_admin(member):
    r = member("editor").post("/api/team", {"email": "n@example.com", "name": "N", "role": "viewer"}, format="json")
    assert r.status_code == 403


def test_invite_creates_user_and_link(member):
    c = member("admin")
    r = c.post("/api/team", {"email": "new@example.com", "name": "New", "role": "editor"}, format="json")
    assert r.status_code == 201
    assert r.json()["set_password_url"].startswith("/set-password/")
    u = User.objects.get(email="new@example.com")
    assert not u.has_usable_password()
    assert u.memberships.get().role == "editor"
    dup = c.post("/api/team", {"email": "NEW@example.com", "name": "New", "role": "editor"}, format="json")
    assert dup.status_code == 400


def test_set_password_with_invite_token(member):
    c = member("owner")
    url = c.post("/api/team", {"email": "inv@example.com", "name": "Inv", "role": "viewer"}, format="json").json()[
        "set_password_url"
    ]
    _, uid, token = url.strip("/").split("/")
    anon = APIClient()
    body = {"uid": uid, "token": token, "new_password": "a-Better-pw-98765"}
    assert anon.post("/api/auth/set-password", body, format="json").status_code == 204
    assert anon.post("/api/auth/login", {"email": "inv@example.com", "password": "a-Better-pw-98765"}, format="json").status_code == 200
    assert anon.post("/api/auth/set-password", {**body, "new_password": "another-Pw-5566"}, format="json").status_code == 400
    bad = {"uid": uid, "token": "bogus", "new_password": "a-Better-pw-98765"}
    assert anon.post("/api/auth/set-password", bad, format="json").status_code == 400


def test_set_password_validates_password(member):
    c = member("owner")
    url = c.post("/api/team", {"email": "v@example.com", "name": "V", "role": "viewer"}, format="json").json()["set_password_url"]
    _, uid, token = url.strip("/").split("/")
    r = APIClient().post("/api/auth/set-password", {"uid": uid, "token": token, "new_password": "123"}, format="json")
    assert r.status_code == 400


def test_change_role_and_cannot_demote_last_owner(member):
    owner = member("owner")
    r = owner.patch(f"/api/team/{owner.user.id}", {"role": "admin"}, format="json")
    assert r.status_code == 400
    assert owner.user.memberships.get().role == "owner"
    other = member("viewer")
    r = owner.patch(f"/api/team/{other.user.id}", {"role": "editor"}, format="json")
    assert r.status_code == 200 and r.json()["role"] == "editor"
    assert member("editor").patch(f"/api/team/{other.user.id}", {"role": "admin"}, format="json").status_code == 403


def test_team_isolated(member, other_workspace):
    other = User.objects.create_user(username="x@o.com", email="x@o.com", password=PW)
    Membership.objects.create(user=other, workspace=other_workspace, role="owner")
    c = member("owner")
    assert other.id not in [r["id"] for r in c.get("/api/team").json()]
    assert c.patch(f"/api/team/{other.id}", {"role": "viewer"}, format="json").status_code == 404


def test_csrf_required_for_session_post(user):
    c = APIClient(enforce_csrf_checks=True)
    c.force_login(user)
    assert c.post("/api/me/password", {"current_password": PW, "new_password": "a-Better-pw-98765"}, format="json").status_code == 403


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def test_admin_cannot_promote_self_to_owner(member):
    admin = member("admin")
    r = admin.patch(f"/api/team/{admin.user.id}", {"role": "owner"}, format="json")
    assert r.status_code == 403 and r.json() == {"detail": "Only an owner can do that."}


def test_admin_cannot_invite_owner(member):
    r = member("admin").post("/api/team", {"email": "o@example.com", "name": "O", "role": "owner"}, format="json")
    assert r.status_code == 403
    assert not User.objects.filter(email="o@example.com").exists()


def test_admin_cannot_change_owner_role(member):
    owner = member("owner")
    member("owner")  # a second owner so the last-owner guard is not what blocks it
    r = member("admin").patch(f"/api/team/{owner.user.id}", {"role": "viewer"}, format="json")
    assert r.status_code == 403


def test_owner_can_promote_to_owner(member):
    owner = member("owner")
    other = member("admin")
    r = owner.patch(f"/api/team/{other.user.id}", {"role": "owner"}, format="json")
    assert r.status_code == 200 and r.json()["role"] == "owner"


def test_login_throttled(user):
    c = APIClient()
    codes = [c.post("/api/auth/login", {"email": "asha@example.com", "password": "bad"}, format="json").status_code for _ in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429
