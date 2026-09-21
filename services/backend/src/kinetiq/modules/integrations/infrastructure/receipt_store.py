from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from kinetiq.modules.integrations.application.errors import IdempotencyConflictError
from kinetiq.modules.integrations.infrastructure.models import McpToolReceipt


class DjangoToolReceiptStore:
    """`ToolReceiptStore` backed by the `McpToolReceipt` table."""

    def run_once(
        self,
        *,
        owner_id: UUID,
        tool: str,
        key: str,
        request_fingerprint: str,
        effect: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        existing = self._find(owner_id, tool, key)
        if existing is not None:
            return self._replay(existing, request_fingerprint)

        try:
            with transaction.atomic():
                # Claiming the receipt first makes the unique constraint the
                # arbiter between concurrent identical requests: the loser
                # fails here and replays, instead of also running the effect.
                receipt = McpToolReceipt.objects.create(
                    owner_id=owner_id,
                    tool=tool,
                    key=key,
                    request_fingerprint=request_fingerprint,
                    response={},
                )
                result = effect()
                receipt.response = result
                receipt.save(update_fields=["response"])
                return result
        except IntegrityError:
            return self._replay_after_race(owner_id, tool, key, request_fingerprint)

    def _replay_after_race(
        self, owner_id: UUID, tool: str, key: str, request_fingerprint: str
    ) -> dict[str, Any]:
        winner = self._find(owner_id, tool, key)
        if winner is None:
            raise  # an unrelated integrity error, not the idempotency race
        return self._replay(winner, request_fingerprint)

    @staticmethod
    def _find(owner_id: UUID, tool: str, key: str) -> McpToolReceipt | None:
        return McpToolReceipt.objects.filter(owner_id=owner_id, tool=tool, key=key).first()

    @staticmethod
    def _replay(receipt: McpToolReceipt, request_fingerprint: str) -> dict[str, Any]:
        if receipt.request_fingerprint != request_fingerprint:
            raise IdempotencyConflictError(
                "IDEMPOTENCY_CONFLICT: this idempotency_key was already used "
                "with different arguments"
            )
        response: dict[str, Any] = receipt.response
        return response
