from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from kinetiq.modules.media.application.ports import MediaEventOutboxRepository, MediaEventPublisher
from kinetiq.modules.media.domain.entities import MediaEventStatus, ProgressPhotoDeletedEvent

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500


@dataclass(frozen=True, slots=True)
class OutboxRunSummary:
    claimed: int = 0
    completed: int = 0
    retried: int = 0
    dead_lettered: int = 0


class MediaEventOutboxService:
    """Durable, retried delivery of ProgressPhotoDeleted.v1 outbox events.

    A cleanup job's completion durably records the event in the same
    transaction (see `MediaCleanupRepository.mark_done_and_enqueue_deleted_event`);
    this service is solely responsible for delivering it to the configured
    publisher, with the same claim/exponential-backoff/dead-letter
    discipline as `MediaCleanupService` -- a transient publish failure is
    retried, never silently dropped, and the event is marked DONE only once
    the publisher has actually accepted it.
    """

    def __init__(
        self,
        repository: MediaEventOutboxRepository,
        publisher: MediaEventPublisher,
        *,
        max_attempts: int = 8,
        lease_seconds: int = 300,
        base_backoff_seconds: int = 30,
        max_backoff_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def attempt(self, event_id: UUID) -> MediaEventStatus:
        """Try to deliver one event now. Never raises for a publish failure."""
        now = self._clock()
        event = self._repository.claim(
            event_id=event_id, now=now, lease_seconds=self._lease_seconds
        )
        if event is None:
            current = self._repository.get(event_id=event_id)
            return current.status if current is not None else MediaEventStatus.DONE

        try:
            # `event.id` is stable across every retried delivery of this same
            # row, so a consumer can dedupe an at-least-once redelivery
            # (e.g. a crash right after this call succeeds but before
            # `mark_done` below) instead of double-applying the effect.
            self._publisher.publish_photo_deleted(
                event_id=event.id,
                photo_id=event.photo_id,
                owner_id=event.owner_id,
                occurred_at=event.created_at,
            )
        except Exception as exc:  # noqa: BLE001 - any publish failure must be retried
            return self._record_failure(event, exc, now)

        self._repository.mark_done(event_id=event.id, at=now)
        return MediaEventStatus.DONE

    def process_due(self, *, limit: int = 50) -> OutboxRunSummary:
        """Worker entry point: attempt delivery of every event that is due."""
        summary = {"claimed": 0, "completed": 0, "retried": 0, "dead_lettered": 0}
        for event_id in self._repository.due_event_ids(now=self._clock(), limit=limit):
            status = self.attempt(event_id)
            summary["claimed"] += 1
            if status == MediaEventStatus.DONE:
                summary["completed"] += 1
            elif status == MediaEventStatus.DEAD_LETTER:
                summary["dead_lettered"] += 1
            else:
                summary["retried"] += 1
        return OutboxRunSummary(**summary)

    def _record_failure(
        self, event: ProgressPhotoDeletedEvent, exc: Exception, now: datetime
    ) -> MediaEventStatus:
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        if event.attempts >= self._max_attempts:
            logger.error(
                "ProgressPhotoDeleted.v1 event %s for photo %s dead-lettered after %s attempts: %s",
                event.id,
                event.photo_id,
                event.attempts,
                error,
            )
            self._repository.mark_dead_letter(event_id=event.id, error=error, at=now)
            return MediaEventStatus.DEAD_LETTER

        delay = min(
            self._base_backoff_seconds * (2 ** (event.attempts - 1)), self._max_backoff_seconds
        )
        logger.warning(
            "ProgressPhotoDeleted.v1 event %s for photo %s failed "
            "(attempt %s), retrying in %ss: %s",
            event.id,
            event.photo_id,
            event.attempts,
            delay,
            error,
        )
        self._repository.mark_retry(
            event_id=event.id, error=error, next_attempt_at=now + timedelta(seconds=delay)
        )
        return MediaEventStatus.PENDING
