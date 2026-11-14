import os
import subprocess
import sys
from pathlib import Path

from django.db import connection

DASHBOARD_DIR = Path(__file__).resolve().parent.parent


def test_engine_is_postgres():
    assert connection.vendor == "postgresql"


def test_connection_options():
    from django.conf import settings

    db = settings.DATABASES["default"]
    assert db["CONN_MAX_AGE"] == 60
    assert db["CONN_HEALTH_CHECKS"] is True


def _import_settings(**env):
    full = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=DASHBOARD_DIR, env=full, capture_output=True, text=True,
    )


def test_missing_password_is_improperly_configured():
    result = _import_settings(POSTGRES_PASSWORD="")
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr


def test_defaults_when_only_password_is_set():
    env = {k: v for k, v in os.environ.items() if not k.startswith("POSTGRES_")}
    result = subprocess.run(
        [sys.executable, "-c",
         "from config.settings import DATABASES as d; x=d['default']; "
         "print(x['NAME'], x['USER'], x['HOST'], x['PORT'])"],
        cwd=DASHBOARD_DIR, env={**env, "POSTGRES_PASSWORD": "x"}, capture_output=True, text=True,
    )
    assert result.stdout.split() == ["dashboard", "dashboard", "127.0.0.1", "5432"], result.stderr
