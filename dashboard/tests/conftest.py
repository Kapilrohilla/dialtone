import os
import tempfile

# Set up the environment before Django loads config.settings. DJANGO_SETTINGS_MODULE
# lives here rather than in pytest.ini: pytest-django imports settings from the
# ini value before any conftest runs, and settings require DJANGO_SECRET_KEY.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("LIVEKIT_API_KEY", "APItestkey")
os.environ.setdefault("LIVEKIT_API_SECRET", "test-livekit-secret-0123456789abcdef")
os.environ["DASHBOARD_DB_DIR"] = tempfile.mkdtemp(prefix="dashboard-test-")
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

import django  # noqa: E402

django.setup()
