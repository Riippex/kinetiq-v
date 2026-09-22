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

from .settings import *  # noqa: F403

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
