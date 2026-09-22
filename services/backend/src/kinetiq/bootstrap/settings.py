import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from kinetiq.bootstrap.vision_settings import resolve_vision_settings

BASE_DIR = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = BASE_DIR.parents[1]
load_dotenv(REPOSITORY_ROOT / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"

_INSECURE_DEFAULT_SECRET_KEY = "unsafe-local-development-key"
_MIN_SECRET_KEY_LENGTH = 20


def _resolve_secret_key() -> str:
    """A fallback (or a placeholder/too-short value) is fine only under
    explicit local development (`DJANGO_DEBUG=true`): Django uses this key
    for cryptographic signing, so a deployment that silently started with a
    publicly known or trivially weak key would sign values an attacker
    could forge. Everywhere else this must fail loudly at settings load,
    not degrade into an insecure default.
    """
    key = os.getenv("DJANGO_SECRET_KEY")
    if DEBUG:
        return key or _INSECURE_DEFAULT_SECRET_KEY
    if not key:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is required when DJANGO_DEBUG is not enabled; "
            "refusing to start with no signing secret."
        )
    if key == _INSECURE_DEFAULT_SECRET_KEY:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is set to the known local-development placeholder; "
            "refusing to start with a publicly known signing secret."
        )
    if len(key) < _MIN_SECRET_KEY_LENGTH:
        raise ImproperlyConfigured(
            f"DJANGO_SECRET_KEY is shorter than {_MIN_SECRET_KEY_LENGTH} characters; "
            "refusing to start with a trivially weak signing secret."
        )
    return key


SECRET_KEY = _resolve_secret_key()
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "kinetiq.modules.identity.infrastructure.apps.IdentityConfig",
    "kinetiq.modules.profiles.infrastructure.apps.ProfilesConfig",
    "kinetiq.modules.goals.infrastructure.apps.GoalsConfig",
    "kinetiq.modules.catalog.infrastructure.apps.CatalogConfig",
    "kinetiq.modules.routines.infrastructure.apps.RoutinesConfig",
    "kinetiq.modules.workouts.infrastructure.apps.WorkoutsConfig",
    "kinetiq.modules.media.infrastructure.apps.MediaConfig",
    "kinetiq.modules.integrations.infrastructure.apps.IntegrationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "kinetiq.bootstrap.urls"
ASGI_APPLICATION = "kinetiq.bootstrap.asgi.application"
WSGI_APPLICATION = "kinetiq.bootstrap.wsgi.application"

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
    }
]

DATABASES = {
    "default": dj_database_url.config(
        default="postgresql://kinetiq:kinetiq@127.0.0.1:5432/kinetiq",
        conn_max_age=60,
        conn_health_checks=True,
    )
}

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
# "redis" (shared, atomic claims) everywhere except the test settings.
DISPLAY_PAIRING_STORE = os.getenv("DISPLAY_PAIRING_STORE", "redis")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# Vision (kinetiq-v-vision) service client configuration. Validated eagerly
# at settings-import time (resolve_vision_settings) so a misconfigured
# deployment fails fast at startup rather than on the first Vision-dependent
# request. VISION_SERVICE_CREDENTIAL is a scoped service-to-service
# credential sent as a bearer token (see
# bootstrap/container.py:get_vision_rest_adapter); empty by default for
# local development against an unauthenticated Vision instance.
_vision_settings = resolve_vision_settings(
    base_url=os.getenv("VISION_BASE_URL", "http://127.0.0.1:8001"),
    timeout_seconds_raw=os.getenv("VISION_TIMEOUT_SECONDS", "5.0"),
    service_credential=os.getenv("VISION_SERVICE_CREDENTIAL", ""),
)
VISION_BASE_URL = _vision_settings.base_url
VISION_TIMEOUT_SECONDS = _vision_settings.timeout_seconds
VISION_SERVICE_CREDENTIAL = _vision_settings.service_credential

AUTH_PASSWORD_VALIDATORS: list[dict[str, str]] = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "kinetiq_identity.User"

# Private S3 media settings
MEDIA_S3_BUCKET = os.getenv("MEDIA_S3_BUCKET", "kinetiq-media-private")
MEDIA_S3_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
MEDIA_PRESIGNED_EXPIRY_SECONDS = int(os.getenv("MEDIA_PRESIGNED_EXPIRY_SECONDS", "900"))
MEDIA_S3_ENDPOINT_URL = os.getenv("MEDIA_S3_ENDPOINT_URL", None)
USE_IN_MEMORY_MEDIA_STORAGE = (
    os.getenv("USE_IN_MEMORY_MEDIA_STORAGE", "false").lower() == "true"
)


# MCP (Alexa+) runtime endpoint. Bearer tokens must be signed OIDC/JWT access
# tokens: signature verified against the trusted JWKS, plus issuer, audience,
# expiry, token use and scope. With no issuer/audience configured the endpoint
# fails closed and rejects every token.
def _csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


MCP_OIDC_ISSUER = os.getenv("MCP_OIDC_ISSUER", "")
MCP_OIDC_AUDIENCE = os.getenv("MCP_OIDC_AUDIENCE", "")
MCP_OIDC_JWKS_URL = os.getenv("MCP_OIDC_JWKS_URL", "")
MCP_OIDC_REQUIRED_SCOPE = os.getenv("MCP_OIDC_REQUIRED_SCOPE", "kinetiq/coach")
MCP_OIDC_TOKEN_USE = os.getenv("MCP_OIDC_TOKEN_USE", "access")
MCP_RESOURCE_URL = os.getenv("MCP_RESOURCE_URL", "http://localhost:8000/mcp")
# DNS-rebinding protection: Host and Origin headers must match these lists.
# Hosts default to the Django allow-list (bare and with any port).
MCP_ALLOWED_HOSTS = _csv_env("MCP_ALLOWED_HOSTS") or [
    entry for host in ALLOWED_HOSTS for entry in (host, f"{host}:*")
]
MCP_ALLOWED_ORIGINS = _csv_env("MCP_ALLOWED_ORIGINS")
