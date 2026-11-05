import os
import tempfile

# Set up the environment before Django loads config.settings. DJANGO_SETTINGS_MODULE
# lives here rather than in pytest.ini: pytest-django imports settings from the
# ini value before any conftest runs, and settings require DJANGO_SECRET_KEY.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("LIVEKIT_API_KEY", "APItestkey")
os.environ.setdefault("LIVEKIT_API_SECRET", "test-livekit-secret-0123456789abcdef")
os.environ["DASHBOARD_DB_DIR"] = tempfile.mkdtemp(prefix="dashboard-test-")
# Tests run on PostgreSQL (`make test-db` starts one on 127.0.0.1:55432); pytest-django
# creates and drops test_<POSTGRES_DB> on it.
os.environ["POSTGRES_HOST"] = os.getenv("TEST_POSTGRES_HOST", "127.0.0.1")
os.environ["POSTGRES_PORT"] = os.getenv("TEST_POSTGRES_PORT", "55432")
os.environ["POSTGRES_USER"] = os.getenv("TEST_POSTGRES_USER", "postgres")
os.environ["POSTGRES_PASSWORD"] = os.getenv("TEST_POSTGRES_PASSWORD", "postgres")
os.environ["POSTGRES_DB"] = "dashboard"
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

import django  # noqa: E402

django.setup()


import pytest  # noqa: E402


@pytest.fixture
def workspace(db):
    from workspaces.models import Workspace

    return Workspace.objects.get_or_create(slug="carrum", defaults={"name": "Carrum Mobility"})[0]


@pytest.fixture
def other_workspace(db):
    from workspaces.models import Workspace

    return Workspace.objects.create(slug="other", name="Other Co")


@pytest.fixture
def member(workspace):
    """Factory: member(role="editor") -> logged-in APIClient that belongs to `workspace`."""
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    from workspaces.models import Membership

    counter = {"n": 0}

    def make(role="editor"):
        counter["n"] += 1
        email = f"{role}{counter['n']}@example.com"
        user = get_user_model().objects.create_user(username=email, email=email, password="pw-test-12345")
        Membership.objects.create(user=user, workspace=workspace, role=role)
        client = APIClient()
        client.force_login(user)
        client.user = user
        return client

    return make

