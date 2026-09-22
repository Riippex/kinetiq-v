import json
from datetime import datetime

import redis

from kinetiq.modules.workouts.domain.display_pairing import (
    DisplayDeviceType,
    DisplayPairingCode,
    DisplayPairingStatus,
)

PAIRING_KEY_PREFIX = "kinetiq:display_pairing:"
# Outer safeguard around the code's own `expires_at`/PAIRED lifetime, not the
# source of truth for expiry: it only ensures a stale key cannot accumulate
# forever. Every committed change refreshes it.
DEFAULT_TTL_SECONDS = 6 * 3600


def _serialize(pairing: DisplayPairingCode) -> str:
    return json.dumps(
        {
            "code": pairing.code,
            "device_type": pairing.device_type.value,
            "created_at": pairing.created_at.isoformat(),
            "expires_at": pairing.expires_at.isoformat(),
            "status": pairing.status.value,
            "paired_session_id": pairing.paired_session_id,
            "owner_id": pairing.owner_id,
            "version": pairing.version,
        }
    )


def _deserialize(raw: str | bytes) -> DisplayPairingCode:
    payload = json.loads(raw)
    return DisplayPairingCode(
        code=payload["code"],
        device_type=DisplayDeviceType(payload["device_type"]),
        created_at=datetime.fromisoformat(payload["created_at"]),
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        status=DisplayPairingStatus(payload["status"]),
        paired_session_id=payload.get("paired_session_id"),
        owner_id=payload.get("owner_id"),
        version=int(payload.get("version", 0)),
    )


class RedisDisplayPairingStore:
    """Shared, expiring `DisplayPairingStore` on a real Redis server.

    Ownership claims must be atomic: two users racing for the same live code
    must not both win. `create_if_absent` uses `SET NX`, and
    `compare_and_save` is an optimistic transaction (`WATCH` + `MULTI`/`EXEC`)
    that commits only if the stored version is unchanged since it was read.
    Values are JSON under this store's own keys (not the Django cache, whose
    values are opaque to Redis-side transactions).
    """

    def __init__(self, client: "redis.Redis", ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _key(code: str) -> str:
        return f"{PAIRING_KEY_PREFIX}{code}"

    def get(self, code: str) -> DisplayPairingCode | None:
        raw = self._client.get(self._key(code))
        return None if raw is None else _deserialize(raw)

    def create_if_absent(self, pairing: DisplayPairingCode) -> bool:
        created = self._client.set(
            self._key(pairing.code), _serialize(pairing), nx=True, ex=self._ttl_seconds
        )
        return bool(created)

    def compare_and_save(self, *, expected_version: int, pairing: DisplayPairingCode) -> bool:
        key = self._key(pairing.code)
        with self._client.pipeline() as pipe:
            try:
                pipe.watch(key)  # type: ignore[no-untyped-call]
                raw = pipe.get(key)
                if raw is None or _deserialize(raw).version != expected_version:
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(key, _serialize(pairing), ex=self._ttl_seconds)
                pipe.execute()
                return True
            except redis.WatchError:
                return False
