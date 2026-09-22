from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from kinetiq.modules.media.domain.entities import (
    MediaCleanupJob,
    MediaCleanupReason,
    ProgressPhoto,
    ProgressPhotoDeletedEvent,
    StoredObjectInfo,
)


class MediaStoragePort(Protocol):
    def generate_upload_url(
        self, *, s3_key: str, content_type: str, byte_length: int, ttl_seconds: int = 900
    ) -> str:
        """Pre-signed PUT bound to the declared content type and exact size."""
        ...

    def generate_download_url(self, *, s3_key: str, ttl_seconds: int = 900) -> str: ...

    def get_object_info(self, *, s3_key: str) -> StoredObjectInfo | None:
        """Size and content type of the stored object, or None if absent."""
        ...

    def delete_object(self, *, s3_key: str) -> None:
        """Idempotently remove the object; raises `MediaStorageError` on failure.

        Deleting an already-absent key succeeds.
        """
        ...


class ProgressPhotoRepository(Protocol):
    def save_upload_request_idempotently(
        self,
        *,
        photo: ProgressPhoto,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[ProgressPhoto, bool]:
        """Persist the photo and its receipt once per (owner, idempotency_key).

        Reusing the key with a different fingerprint raises
        `IdempotencyConflictError`; identical retries, including concurrent
        ones, resolve to the original photo.
        """
        ...

    def get_by_id(self, *, photo_id: UUID, owner_id: UUID) -> ProgressPhoto | None: ...

    def confirm_if_pending(
        self, *, photo_id: UUID, owner_id: UUID, confirmed_at: datetime
    ) -> ProgressPhoto | None:
        """Atomically transition PENDING_UPLOAD -> CONFIRMED.

        None if the row is no longer PENDING_UPLOAD (concurrently confirmed
        or deleted) -- DELETED is a terminal state a stale write must never
        undo.
        """
        ...

    def refresh_upload_authorization_if_pending(
        self, *, photo_id: UUID, owner_id: UUID, authorized_until: datetime
    ) -> ProgressPhoto | None:
        """Atomically extend the presigned-PUT authorization deadline.

        None if the row is no longer PENDING_UPLOAD (concurrently confirmed
        or deleted) -- minting or extending authorization for either would
        let a stale replay recreate the object or outrun deletion cleanup's
        verification window.
        """
        ...

    def list_by_owner(
        self, *, owner_id: UUID, session_id: UUID | None = None
    ) -> list[ProgressPhoto]: ...

    def tombstone_and_enqueue_cleanup(
        self, *, photo_id: UUID, owner_id: UUID, deleted_at: datetime
    ) -> tuple[ProgressPhoto, MediaCleanupJob] | None:
        """Tombstone the photo and enqueue its storage cleanup in ONE transaction.

        Returns None when the photo does not exist or is already deleted.
        """
        ...

    def count_pending_uploads(self, *, owner_id: UUID) -> int:
        """How many PENDING_UPLOAD photos this owner currently has
        outstanding (bounds unfinalized-upload accumulation)."""
        ...

    def find_abandoned_pending_upload_ids(
        self, *, older_than: datetime, limit: int
    ) -> list[tuple[UUID, UUID]]:
        """`(photo_id, owner_id)` pairs for PENDING_UPLOAD photos whose
        presigned-PUT authorization is not None and has already expired --
        never finalized, and no longer reachable by any legitimate client."""
        ...


class MediaCleanupRepository(Protocol):
    def enqueue(
        self,
        *,
        owner_id: UUID,
        photo_id: UUID,
        s3_key: str,
        reason: MediaCleanupReason,
        now: datetime,
        verify_after: datetime | None = None,
    ) -> MediaCleanupJob:
        """Create (or return the existing pending) cleanup job for the object."""
        ...

    def claim(self, *, job_id: UUID, now: datetime, lease_seconds: int) -> MediaCleanupJob | None:
        """Atomically lease one due PENDING job; None if not due or already leased."""
        ...

    def due_job_ids(self, *, now: datetime, limit: int) -> list[UUID]: ...

    def mark_done(self, *, job_id: UUID, at: datetime) -> None:
        """Complete a job that needs no durable event (e.g. UPLOAD_REJECTED).

        A PHOTO_DELETED job must use
        `mark_done_and_enqueue_deleted_event` instead, so completion and the
        event it produces commit atomically.
        """
        ...

    def mark_done_and_enqueue_deleted_event(
        self, *, job_id: UUID, photo_id: UUID, owner_id: UUID, at: datetime
    ) -> None:
        """Complete a PHOTO_DELETED job and durably enqueue its
        ProgressPhotoDeleted.v1 event in ONE transaction: a crash between
        "storage confirmed removed" and "event recorded" must never lose
        the event, unlike a fire-and-forget publish attempted afterward."""
        ...

    def defer_verification(self, *, job_id: UUID, next_attempt_at: datetime) -> MediaCleanupJob:
        """The object was removed, but must be re-checked no earlier than
        `next_attempt_at` (see `MediaCleanupJob.verify_after`) before the job
        may be marked DONE. Not a failure: `last_error` is left untouched."""
        ...

    def mark_retry(
        self, *, job_id: UUID, error: str, next_attempt_at: datetime
    ) -> MediaCleanupJob: ...

    def mark_dead_letter(self, *, job_id: UUID, error: str, at: datetime) -> MediaCleanupJob: ...

    def get(self, *, job_id: UUID) -> MediaCleanupJob | None: ...

    def counts_by_status(self) -> dict[str, int]: ...


class MediaEventOutboxRepository(Protocol):
    """Durable, retried delivery record for ProgressPhotoDeleted.v1 (see
    ProgressPhotoDeletedEvent). Mirrors MediaCleanupRepository's
    claim/backoff/dead-letter discipline."""

    def claim(
        self, *, event_id: UUID, now: datetime, lease_seconds: int
    ) -> ProgressPhotoDeletedEvent | None:
        """Atomically lease one due PENDING event; None if not due or already leased."""
        ...

    def due_event_ids(self, *, now: datetime, limit: int) -> list[UUID]: ...

    def mark_done(self, *, event_id: UUID, at: datetime) -> None: ...

    def mark_retry(
        self, *, event_id: UUID, error: str, next_attempt_at: datetime
    ) -> ProgressPhotoDeletedEvent: ...

    def mark_dead_letter(
        self, *, event_id: UUID, error: str, at: datetime
    ) -> ProgressPhotoDeletedEvent: ...

    def get(self, *, event_id: UUID) -> ProgressPhotoDeletedEvent | None: ...

    def counts_by_status(self) -> dict[str, int]: ...


class WorkoutSessionLookup(Protocol):
    def is_valid_owned_session(self, *, owner_id: UUID, session_id: UUID) -> bool: ...


class MediaEventPublisher(Protocol):
    def publish_photo_deleted(self, *, photo_id: UUID, owner_id: UUID) -> None: ...
