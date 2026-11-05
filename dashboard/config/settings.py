"""Django settings for the calls dashboard.

The dashboard listens on the VM's localhost only and is reached with `make tunnel`
(plain HTTP over an SSH tunnel), so HTTPS-only settings are deliberately off.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# LiveKit API (live rooms, trunks, rules) and webhook signature verification.
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880").replace("ws://", "http://").replace("wss://", "https://")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
# Where "Transfer to a person" sends a live caller (sip:... or tel:...); empty = transfer not set up.
HANDOFF_SIP_URI = os.getenv("HANDOFF_SIP_URI", "")
# Where Django's old "/" page sends people: the Next.js console.
CONSOLE_URL = os.getenv("CONSOLE_URL", "http://localhost:3000/")
# The agent container's text simulator (agent/simulate.py) behind "Try it" and "Test call".
AGENT_SIM_URL = os.getenv("AGENT_SIM_URL", "http://127.0.0.1:8790")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "calls",
    "workspaces",
    "voiceagents",
    "knowledge",
    "workflows",
    "runtime",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ASGI_APPLICATION = "config.asgi.application"

# Directory for files the dashboard keeps (recordings, later). The database is PostgreSQL.
DB_DIR = Path(os.getenv("DASHBOARD_DB_DIR", "/data"))

if not os.getenv("POSTGRES_PASSWORD"):
    raise ImproperlyConfigured("POSTGRES_PASSWORD is not set (scripts/init.sh generates it in .env)")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "dashboard"),
        "USER": os.getenv("POSTGRES_USER", "dashboard"),
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/admin/login/"

# The console frontend runs on a different local origin in development.
CSRF_TRUSTED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "workspaces.permissions.IsMember",
    ],
    "DEFAULT_THROTTLE_RATES": {"login": "10/min", "set_password": "10/min"},
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # /app/staticfiles in the container
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
