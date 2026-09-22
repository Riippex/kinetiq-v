"""Test settings backed by a real PostgreSQL instance.

Concurrency and row-locking behavior (`select_for_update`, transaction
isolation) cannot be verified against SQLite: SQLite serializes at the
database/connection level rather than at the row level, so a race that only
manifests under PostgreSQL's MVCC + row-lock semantics would pass on SQLite
for the wrong reason. Tests that specifically exercise concurrent
`apply_transition` calls must run under this settings module against a real
PostgreSQL server (see docs/runbooks for local docker-compose setup) rather
than under the default in-memory SQLite `test_settings`.
"""

import os

# settings.py refuses to start without a real DJANGO_SECRET_KEY unless
# DJANGO_DEBUG is set; this is a fixed, published test-only value that must
# never be used outside the test suite.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-django-secret-key-not-for-production-use")

from .settings import *  # noqa: E402,F403

DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_TEST_DB", "kinetiq_test"),
        "USER": os.getenv("POSTGRES_TEST_USER", "kinetiq"),
        "PASSWORD": os.getenv("POSTGRES_TEST_PASSWORD", "devlocalpass"),
        "HOST": os.getenv("POSTGRES_TEST_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_TEST_PORT", "15432"),
    }
}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
# Process-local store: no Redis server is needed for the default suite.
DISPLAY_PAIRING_STORE = "memory"
# This settings module tests real PostgreSQL row-locking/concurrency, not
# real S3: no AWS credentials are configured here, so selecting the real
# adapter would fail (correctly -- see get_media_storage) rather than
# silently degrade.
USE_IN_MEMORY_MEDIA_STORAGE = True
