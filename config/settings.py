"""Django settings for the data.gov.uk Explorer.

Environment config lives in .env, loaded here via python-dotenv. The env
var names (DATABASE_URL, APP_ENV, BASIC_AUTH_*, LLM_*) are generic and
double as the Django additions SECRET_KEY and DEBUG.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _db_config_from_url(url: str) -> dict:
    """Parse DATABASE_URL (postgresql://...) into Django's DATABASES dict.

    Empty host/port/user/password stay as "" so Django falls back to libpq
    defaults (local socket, current OS user).
    """
    p = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": p.path[1:],
        "USER": p.username or "",
        "PASSWORD": p.password or "",
        "HOST": p.hostname or "",
        "PORT": p.port or "",
    }


SECRET_KEY = os.getenv("SECRET_KEY") or "dev-insecure-secret-key-change-me"

DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

# No host check by default; ALLOWED_HOSTS is opt-in via env.
ALLOWED_HOSTS = [h for h in os.getenv("ALLOWED_HOSTS", "*").split(",") if h]


INSTALLED_APPS = [
    # Uses WhiteNoise for dev /static/ too (see MIDDLEWARE), so its
    # Cache-Control settings below apply under runserver. Must precede
    # django.contrib.staticfiles so this command wins.
    "whitenoise.runserver_nostatic",
    # Stock Django static files — templates reference assets via
    # {{ static(...) }}.
    "django.contrib.staticfiles",
    "explorer",
]

MIDDLEWARE = [
    # Gates everything in production (APP_ENV=production); missing
    # BASIC_AUTH_USER/PASS there is a startup error, not a silent no-op.
    # /health is exempt (see explorer/middleware.py).
    "explorer.middleware.BasicAuthMiddleware",
    # Renders templates/404.html for every 404 in both DEBUG modes (Django's
    # DEBUG technical 404 would otherwise replace it).
    "explorer.middleware.NotFoundMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serves collectstatic output in production; passes through to the
    # staticfiles handler in dev. Missing static renders 404.html.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "explorer.middleware.CacheControlMiddleware",
    "django.middleware.http.ConditionalGetMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        # Jinja2 is the template backend (macros + 5 custom filters),
        # listed first so render() resolves templates through it.
        "BACKEND": "explorer.jinja2.Jinja2",
        "DIRS": [BASE_DIR / "explorer" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {},
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database — Django owns the schema (migrations); the build pipeline
# populates it.
DATABASES = {
    "default": _db_config_from_url(
        os.getenv("DATABASE_URL", "postgresql://localhost:5432/datagovuk_explorer"),
    ),
}


# Internationalization

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


# Static files — served by WhiteNoise in prod (collectstatic output) and
# the staticfiles handler in dev. Templates reference assets via
# {{ static('...') }}. No MEDIA_URL override: we serve no media, and the
# Django default ("") stays distinct from "/static/".
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "explorer" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}

# Caching — dev uses finders to skip collectstatic on every change.
if DEBUG:
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_MAX_AGE = 0
