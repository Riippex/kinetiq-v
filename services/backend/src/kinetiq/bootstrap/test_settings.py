import os

# settings.py refuses to start without a real DJANGO_SECRET_KEY unless
# DJANGO_DEBUG is set; this is a fixed, published test-only value that must
# never be used outside the test suite.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-django-secret-key-not-for-production-use")

from .settings import *  # noqa: E402,F403

DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
USE_IN_MEMORY_MEDIA_STORAGE = True
# Process-local store: no Redis server is needed for the default suite.
DISPLAY_PAIRING_STORE = "memory"
