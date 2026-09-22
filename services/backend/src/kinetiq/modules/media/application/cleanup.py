from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from kinetiq.modules.media.application.ports import (
    MediaCleanupRepository,
    MediaEventPublisher,
    MediaStoragePort,
)
from kinetiq.modules.media.domain.entities import (
    MediaCleanupJob,
    MediaCleanupReason,
    MediaCleanupStatus,
)

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 500


@dataclass(frozen=True, slots=True)
class CleanupRunSummary:
    claimed: int = 0
    completed: int = 0
    retried: int = 0
    dead_lettered: int = 0


class MediaCleanupService:
    """Durable removal of private objects from storage.

    Deleting a photo commits its tombstone and a cleanup job together. Storage
    removal is then attempted, and any failure is recorded on the job and
    retried with exponential backoff (idempotent deletes), until it succeeds or
    the job is dead-lettered for operator attention. A photo whose storage
    cleanup has not succeeded is therefore never silently forgotten.
    """

    def __init__(
        self,
        repository: MediaCleanupRepository,
        storage: MediaStoragePort,
        event_publisher: MediaEventPublisher | None = None,
        *,
        max_attempts: int = 8,
        lease_seconds: int = 300,
        base_backoff_seconds: int = 30,
        max_backoff_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._event_publisher = event_publisher
        self._max_attempts = max_attempts
        self._lease_seconds = lease_seconds
        self._base_backoff_seconds = base_backoff_seconds
        self._max_backoff_seconds = max_backoff_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def now(self) -> datetime:
        """The service clock, so jobs are stamped on the same timeline they are claimed on."""
        return self._clock()

    def enqueue_object_cleanup(
        self, *, owner_id: UUID, photo_id: UUID, s3_key: str, reason: MediaCleanupReason
    ) -> MediaCleanupJob:
        return self._repository.enqueue(
            owner_id=owner_id,
            photo_id=photo_id,
            s3_key=s3_key,
            reason=reason,
            now=self._clock(),
        )

    def attempt(self, job_id: UUID) -> MediaCleanupStatus:
        """Try to complete one job now. Never raises for a storage failure."""
        now = self._clock()
        job = self._repository.claim(job_id=job_id, now=now, lease_seconds=self._lease_seconds)
        if job is None:
            current = self._repository.get(job_id=job_id)
            return current.status if current is not None else MediaCleanupStatus.DONE

        try:
            self._storage.delete_object(s3_key=job.s3_key)
        except Exception as exc:  # noqa: BLE001 - any storage failure must be retried
            return self._record_failure(job, exc, now)

        if job.verify_after is not None and job.verify_after > now:
            # The object is gone now, but a presigned PUT issued before this
            # delete may still be authorized to recreate it at this key until
            # `verify_after`. Re-check no earlier than that instant instead of
            # declaring this job -- and the caller-visible cleanup -- done
            # while that window is still open.
            self._repository.defer_verification(job_id=job.id, next_attempt_at=job.verify_after)
            return MediaCleanupStatus.PENDING

        self._repository.mark_done(job_id=job.id, at=now)
        self._publish_deleted(job)
        return MediaCleanupStatus.DONE

    def process_due(self, *, limit: int = 50) -> CleanupRunSummary:
        """Worker entry point: attempt every job that is due."""
        summary = {"claimed": 0, "completed": 0, "retried": 0, "dead_lettered": 0}
        for job_id in self._repository.due_job_ids(now=self._clock(), limit=limit):
            status = self.attempt(job_id)
            summary["claimed"] += 1
            if status == MediaCleanupStatus.DONE:
                summary["completed"] += 1
            elif status == MediaCleanupStatus.DEAD_LETTER:
                summary["dead_lettered"] += 1
            else:
                summary["retried"] += 1
        return CleanupRunSummary(**summary)

    def _record_failure(
        self, job: MediaCleanupJob, exc: Exception, now: datetime
    ) -> MediaCleanupStatus:
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
        if job.attempts >= self._max_attempts:
            logger.error(
                "Media cleanup job %s for photo %s dead-lettered after %s attempts: %s",
                job.id,
                job.photo_id,
                job.attempts,
                error,
            )
            self._repository.mark_dead_letter(job_id=job.id, error=error, at=now)
            return MediaCleanupStatus.DEAD_LETTER

        delay = min(
            self._base_backoff_seconds * (2 ** (job.attempts - 1)), self._max_backoff_seconds
        )
        logger.warning(
            "Media cleanup job %s for photo %s failed (attempt %s), retrying in %ss: %s",
            job.id,
            job.photo_id,
            job.attempts,
            delay,
            error,
        )
        self._repository.mark_retry(
            job_id=job.id, error=error, next_attempt_at=now + timedelta(seconds=delay)
        )
        return MediaCleanupStatus.PENDING

    def _publish_deleted(self, job: MediaCleanupJob) -> None:
        if self._event_publisher is None or job.reason != MediaCleanupReason.PHOTO_DELETED:
            return
        try:
            self._event_publisher.publish_photo_deleted(
                photo_id=job.photo_id, owner_id=job.owner_id
            )
        except Exception:  # noqa: BLE001 - the object is already gone; do not undo it
            logger.exception("Failed to publish ProgressPhotoDeleted for %s", job.photo_id)
