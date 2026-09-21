import json
import logging
from datetime import datetime

from django.core.cache import cache

from kinetiq.modules.workouts.domain.display_pairing import (
    DisplayDeviceType,
    DisplayPairingCode,
    DisplayPairingStatus,
)

logger = logging.getLogger(__name__)

PAIRING_KEY_PREFIX = "kinetiq:display_pairing:"
# A process-local dict lost every pairing code on restart or across worker
# processes -- a phone and a TV are frequently served by different worker
# processes, so an in-memory store could pair on one and never be seen by
# the other. Redis TTL is a generous outer safeguard around the pairing
# code's own `expires_at`/PAIRED lifetime, not the source of truth for
# expiry -- it only ensures a stale key cannot accumulate forever.
DEFAULT_TTL_SECONDS = 6 * 3600


class RedisDisplayPairingStore:
    """Shared, expiring `DisplayPairingStore` backed by the Django cache
    (Redis). Replaces the process-local `InMemoryDisplayPairingStore` so a
    phone and a TV served by different worker processes -- or different
    processes entirely -- see the same pairing state."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds

    def _key(self, code: str) -> str:
        return f"{PAIRING_KEY_PREFIX}{code}"

    def save(self, pairing: DisplayPairingCode) -> None:
        payload = {
            "code": pairing.code,
            "device_type": pairing.device_type.value,
            "created_at": pairing.created_at.isoformat(),
            "expires_at": pairing.expires_at.isoformat(),
            "status": pairing.status.value,
            "paired_session_id": pairing.paired_session_id,
            "owner_id": pairing.owner_id,
        }
        try:
            cache.set(self._key(pairing.code), json.dumps(payload), timeout=self._ttl_seconds)
        except Exception:
            logger.exception("Failed to store display pairing code %s in Redis", pairing.code)
            raise

    def get(self, code: str) -> DisplayPairingCode | None:
        try:
            raw = cache.get(self._key(code))
        except Exception:
            logger.exception("Failed to read display pairing code %s from Redis", code)
            return None

        if raw is None:
            return None

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        payload = json.loads(raw)
        return DisplayPairingCode(
            code=payload["code"],
            device_type=DisplayDeviceType(payload["device_type"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            status=DisplayPairingStatus(payload["status"]),
            paired_session_id=payload.get("paired_session_id"),
            owner_id=payload.get("owner_id"),
        )
