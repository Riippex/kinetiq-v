import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from kinetiq.modules.integrations.application.errors import IdempotencyKeyError
from kinetiq.modules.integrations.application.ports import ToolReceiptStore

MAX_IDEMPOTENCY_KEY_LENGTH = 128


def validate_idempotency_key(key: object) -> str:
    cleaned = key.strip() if isinstance(key, str) else ""
    if not cleaned:
        raise IdempotencyKeyError("idempotency_key is required for this mutating tool")
    if len(cleaned) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise IdempotencyKeyError(
            f"idempotency_key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters"
        )
    return cleaned


def request_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotentToolRunner:
    """Runs a command at most once per caller-provided idempotency key.

    `payload` must contain every argument of the request: the key identifies
    the complete request, so reusing it with any different argument is a
    conflict rather than a replay.
    """

    def __init__(self, store: ToolReceiptStore) -> None:
        self._store = store

    def run(
        self,
        *,
        owner_id: UUID,
        tool: str,
        key: str,
        payload: dict[str, Any],
        effect: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        return self._store.run_once(
            owner_id=owner_id,
            tool=tool,
            key=validate_idempotency_key(key),
            request_fingerprint=request_fingerprint(payload),
            effect=effect,
        )
