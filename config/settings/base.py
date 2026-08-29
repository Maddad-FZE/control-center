import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = os.environ.get("DEBUG", "False").lower() in ("1", "true", "yes")

_allowed = os.environ.get(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1,192.168.0.40,zaidan.home",
)
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()]
_extra_hosts = os.environ.get("EXTRA_ALLOWED_HOSTS", "")
if _extra_hosts:
    ALLOWED_HOSTS.extend(h.strip() for h in _extra_hosts.split(",") if h.strip())

_csrf = os.environ.get(
    "CSRF_TRUSTED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000",
)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf.split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "csp",
    "core",
    "dashboard",
    "library",
    "apps.notes",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.middleware.HostAppMiddleware",
    "core.middleware.SetupRequiredMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.AddonEnabledMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.site",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data" / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dubai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "data" / "django_cache",
        "OPTIONS": {"MAX_ENTRIES": 2000},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
SESSION_SAVE_EVERY_REQUEST = True
_session_domain = os.environ.get("SESSION_COOKIE_DOMAIN", "")
if _session_domain:
    SESSION_COOKIE_DOMAIN = _session_domain

SITE_TITLE = os.environ.get("SITE_TITLE", "Home Server Command Center")

# Brute-force protection
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# CSP — fonts and styles self-hosted; CRT animations in external css files
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": ("'self'",),
        "style-src": ("'self'", "'unsafe-inline'"),
        "img-src": ("'self'", "data:", "https:"),
        "font-src": ("'self'",),
        "connect-src": ("'self'",),
        "media-src": ("'self'", "data:"),
        "frame-ancestors": ("'none'",),
    }
}

# Homelab integrations
HEALTH_CHECK_ENABLED = os.environ.get("HEALTH_CHECK_ENABLED", "true").lower() in (
    "1",
    "true",
    "yes",
)
DOCKER_HOST = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
NTFY_URL = os.environ.get("NTFY_URL", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "homelab-alerts")
NTFY_USER = os.environ.get("NTFY_USER", "")
NTFY_PASSWORD = os.environ.get("NTFY_PASSWORD", "")

# Self-update via GitHub releases
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Maddad-FZE/control-center")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
UPDATE_CHECK_INTERVAL_HOURS = float(
    os.environ.get("UPDATE_CHECK_INTERVAL_HOURS", "12")
)
UPDATES_ALLOW_INSTALL = os.environ.get("UPDATES_ALLOW_INSTALL", "true").lower() in (
    "1",
    "true",
    "yes",
)
UPDATE_RESTART_COMMAND = os.environ.get("UPDATE_RESTART_COMMAND", "")
SERVICES_HOST = os.environ.get("SERVICES_HOST", "")

# Public subdomain → Django app name (notes, etc.)
HOST_APP_MAP = {
    host.strip(): app.strip()
    for pair in os.environ.get("HOST_APP_MAP", "notes.thezaidan.family:notes").split(",")
    if pair.strip()
    for host, app in [pair.split(":", 1)]
}

# Nav registry — Dashboard only; addons and Library are built in context_processors.site
NAV_APPS = [
    {"name": "Dashboard", "url_name": "dashboard", "icon": "dashboard"},
]
