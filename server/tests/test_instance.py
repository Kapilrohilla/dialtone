import importlib

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import ProtectedError
from rest_framework.test import APIClient

from instance.models import InstanceSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser():
    user = get_user_model().objects.create_superuser(username="root", email="root@example.com", password="pw-1234567")
    client = APIClient()
    client.force_login(user)
    client.user = user
    return client


def test_migration_seeds_the_single_row():
    assert list(InstanceSettings.objects.values_list("pk", "project_name")) == [(1, "Dialtone")]


DEFAULTS = {"project_name": "Dialtone", "theme": "saffron", "logo_url": None}


def test_anyone_can_read(member):
    assert APIClient().get("/api/instance").json() == DEFAULTS
    assert APIClient().get("/api/instance/").json() == DEFAULTS
    assert member("viewer").get("/api/instance").json() == DEFAULTS


def test_anonymous_patch_is_403():
    r = APIClient(enforce_csrf_checks=True).patch("/api/instance", {"project_name": "X"}, format="json")
    assert r.status_code == 403
    assert InstanceSettings.load().project_name == "Dialtone"


@pytest.mark.parametrize("role", ["owner", "admin", "editor"])
def test_workspace_roles_cannot_patch(member, role):
    r = member(role).patch("/api/instance", {"project_name": "X"}, format="json")
    assert r.status_code == 403
    assert InstanceSettings.load().project_name == "Dialtone"


def test_superuser_can_update(superuser):
    r = superuser.patch("/api/instance", {"project_name": "  Acme Voice  "}, format="json")
    assert r.status_code == 200, r.content
    assert r.json() == {**DEFAULTS, "project_name": "Acme Voice"}
    row = InstanceSettings.objects.get()
    assert row.project_name == "Acme Voice" and row.updated_by == superuser.user and row.updated_at
    assert APIClient().get("/api/instance").json() == {**DEFAULTS, "project_name": "Acme Voice"}


@pytest.mark.parametrize("name", ["", "   ", "x" * 61, None])
def test_invalid_names_rejected(superuser, name):
    r = superuser.patch("/api/instance", {"project_name": name}, format="json")
    assert r.status_code == 400, r.content
    assert "project_name" in r.json()
    assert InstanceSettings.load().project_name == "Dialtone"


def test_sixty_chars_allowed(superuser):
    assert superuser.patch("/api/instance", {"project_name": "x" * 60}, format="json").status_code == 200


def test_missing_field_rejected(superuser):
    assert superuser.patch("/api/instance", {}, format="json").status_code == 400


@pytest.mark.parametrize("theme", ["ocean", "forest", "saffron"])
def test_superuser_can_set_theme(superuser, theme):
    InstanceSettings.objects.update(project_name="Kept")
    r = superuser.patch("/api/instance", {"theme": theme}, format="json")
    assert r.status_code == 200, r.content
    assert r.json() == {**DEFAULTS, "project_name": "Kept", "theme": theme}
    assert APIClient().get("/api/instance").json()["theme"] == theme


def test_name_and_theme_together(superuser):
    r = superuser.patch("/api/instance", {"project_name": "Acme", "theme": "ocean"}, format="json")
    assert r.status_code == 200 and r.json() == {**DEFAULTS, "project_name": "Acme", "theme": "ocean"}


@pytest.mark.parametrize("theme", ["", "sunset", "OCEAN", None])
def test_unknown_theme_rejected(superuser, theme):
    r = superuser.patch("/api/instance", {"theme": theme}, format="json")
    assert r.status_code == 400 and "theme" in r.json()
    assert InstanceSettings.load().theme == "saffron"


@pytest.mark.parametrize("role", ["owner", "admin", "editor", "viewer"])
def test_workspace_roles_cannot_set_theme(member, role):
    assert member(role).patch("/api/instance", {"theme": "ocean"}, format="json").status_code == 403
    assert InstanceSettings.load().theme == "saffron"


def test_singleton():
    InstanceSettings(project_name="Other").save()  # always row 1
    assert InstanceSettings.objects.count() == 1 and InstanceSettings.load().project_name == "Other"
    with pytest.raises(ProtectedError):
        InstanceSettings.load().delete()
    InstanceSettings.objects.all().delete()  # bulk delete bypasses delete(); load() brings it back
    assert InstanceSettings.load().pk == 1


@pytest.mark.parametrize("env, expected", [
    ("  Acme  ", "Acme"), ("", "Dialtone"), ("   ", "Dialtone"), ("x" * 61, "Dialtone"), (None, "Dialtone"),
])
def test_seed_migration_reads_env(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("DIALTONE_PROJECT_NAME", raising=False)
    else:
        monkeypatch.setenv("DIALTONE_PROJECT_NAME", env)
    InstanceSettings.objects.all().delete()
    migration = importlib.import_module("instance.migrations.0001_initial")
    apps = MigrationExecutor(connection).loader.project_state(("instance", "0001_initial")).apps
    migration.seed_instance_settings(apps, None)
    assert InstanceSettings.objects.get().project_name == expected


def test_me_includes_is_superuser(member):
    c = member("owner")
    assert c.get("/api/me").json()["is_superuser"] is False
    c.user.is_superuser = True
    c.user.save()
    assert c.get("/api/me").json()["is_superuser"] is True


def test_schema_endpoint_is_public():
    r = APIClient().get("/api/schema/", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert r.status_code == 200
    assert b"Dialtone API" in r.content and b"/api/instance" in r.content
