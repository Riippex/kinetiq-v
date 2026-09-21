"""Caller-provided idempotency for mutating MCP tools.

Session lifecycle tools pass the caller's key straight to the product use
case, which already dedupes by (owner, operation, key) with a request
fingerprint. The remaining mutating use cases (profile, goal, routine) have no
native key, so `run_idempotent` records the first response per
(owner, tool, key) in one transaction with the effect and replays it on retry.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from kinetiq.modules.integrations.infrastructure.models import McpToolReceipt

MAX_IDEMPOTENCY_KEY_LENGTH = 128


class IdempotencyKeyError(ValueError):
    """The caller-provided idempotency key is missing or malformed."""


class IdempotencyConflictError(Exception):
    """The idempotency key was already used with different arguments."""


def validate_idempotency_key(key: str) -> str:
    cleaned = key.strip() if isinstance(key, str) else ""
    if not cleaned:
        raise IdempotencyKeyError("idempotency_key is required for this mutating tool")
    if len(cleaned) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise IdempotencyKeyError(
            f"idempotency_key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters"
        )
    return cleaned


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay(receipt: McpToolReceipt, fingerprint: str) -> dict[str, Any]:
    if receipt.request_fingerprint != fingerprint:
        raise IdempotencyConflictError(
            "IDEMPOTENCY_CONFLICT: this idempotency_key was already used with different arguments"
        )
    response: dict[str, Any] = receipt.response
    return response


def run_idempotent(
    *,
    owner_id: UUID,
    tool: str,
    key: str,
    payload: dict[str, Any],
    effect: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run `effect` at most once per (owner, tool, key); replay its response."""
    key = validate_idempotency_key(key)
    fingerprint = _fingerprint(payload)

    existing = McpToolReceipt.objects.filter(owner_id=owner_id, tool=tool, key=key).first()
    if existing is not None:
        return _replay(existing, fingerprint)

    try:
        with transaction.atomic():
            # Claiming the receipt first makes the unique constraint the
            # arbiter between concurrent retries: the loser fails here and
            # replays, instead of also running the effect.
            receipt = McpToolReceipt.objects.create(
                owner_id=owner_id,
                tool=tool,
                key=key,
                request_fingerprint=fingerprint,
                response={},
            )
            result = effect()
            receipt.response = result
            receipt.save(update_fields=["response"])
            return result
    except IntegrityError:
        winner = McpToolReceipt.objects.filter(owner_id=owner_id, tool=tool, key=key).first()
        if winner is None:
            raise
        return _replay(winner, fingerprint)
