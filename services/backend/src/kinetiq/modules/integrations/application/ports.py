from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID


class ToolReceiptStore(Protocol):
    """Durable idempotency ledger for commands whose use case has no native key."""

    def run_once(
        self,
        *,
        owner_id: UUID,
        tool: str,
        key: str,
        request_fingerprint: str,
        effect: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Run `effect` at most once per (owner, tool, key).

        The receipt is claimed and the response recorded in the same
        transaction as the effect, so either both persist or neither does. A
        repeat with the same fingerprint replays the recorded response; a
        repeat with a different fingerprint raises `IdempotencyConflictError`
        before `effect` runs. Concurrent identical calls resolve to a single
        effect.
        """
