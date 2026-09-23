from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, F

from kinetiq.modules.media.application.ports import (
    MediaCleanupRepository,
    MediaEventOutboxRepository,
    MediaEventPublisher,
    ProgressPhotoRepository,
    WorkoutSessionLookup,
)
from kinetiq.modules.media.domain.entities import (
    IdempotencyConflictError,
    MediaCleanupJob,
    MediaCleanupReason,
    MediaCleanupStatus,
    MediaEventStatus,
    ProgressPhoto,
    ProgressPhotoDeletedEvent,
    ProgressPhotoStatus,
)
from kinetiq.modules.media.infrastructure.models import (
    MediaCleanupJobRecord,
    MediaEventOutboxRecord,
    MediaUploadReceiptRecord,
    ProgressPhotoRecord,
)
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord

logger = logging.getLogger(__name__)


def _record_to_domain(record: ProgressPhotoRecord) -> ProgressPhoto:
    return ProgressPhoto(
        id=record.id,
        owner_id=record.owner_id,
        session_id=record.session_id,
        s3_key=record.s3_key,
        content_type=record.content_type,
        byte_length=record.byte_length,
        status=ProgressPhotoStatus(record.status),
        created_at=record.created_at,
        confirmed_at=record.confirmed_at,
        deleted_at=record.deleted_at,
        upload_authorized_until=record.upload_authorized_until,
        final_s3_key=record.final_s3_key,
    )


def _job_to_domain(record: MediaCleanupJobRecord) -> MediaCleanupJob:
    return MediaCleanupJob(
        id=record.id,
        owner_id=record.owner_id,
        photo_id=record.photo_id,
        s3_key=record.s3_key,
        reason=MediaCleanupReason(record.reason),
        status=MediaCleanupStatus(record.status),
        attempts=record.attempts,
        next_attempt_at=record.next_attempt_at,
        created_at=record.created_at,
        last_error=record.last_error,
        completed_at=record.completed_at,
        verify_after=record.verify_after,
    )


def _event_to_domain(record: MediaEventOutboxRecord) -> ProgressPhotoDeletedEvent:
    return ProgressPhotoDeletedEvent(
        id=record.id,
        owner_id=record.owner_id,
        photo_id=record.photo_id,
        status=MediaEventStatus(record.status),
        attempts=record.attempts,
        next_attempt_at=record.next_attempt_at,
        created_at=record.created_at,
        last_error=record.last_error,
        completed_at=record.completed_at,
    )


def _enqueue_cleanup_job(
    *,
    owner_id: UUID,
    photo_id: UUID,
    s3_key: str,
    reason: MediaCleanupReason,
    now: datetime,
    verify_after: datetime | None = None,
) -> MediaCleanupJob:
    """Create the cleanup job, or return the one already pending for the object.

    Safe to call inside a caller's transaction: the creation runs in a
    savepoint, so losing the unique-constraint race does not poison it.
    """
    open_jobs = MediaCleanupJobRecord.objects.filter(
        photo_id=photo_id, reason=reason.value, status=MediaCleanupStatus.PENDING.value
    )
    existing = open_jobs.first()
    if existing is not None:
        return _job_to_domain(existing)
    try:
        with transaction.atomic():
            record = MediaCleanupJobRecord.objects.create(
                owner_id=owner_id,
                photo_id=photo_id,
                s3_key=s3_key,
                reason=reason.value,
                status=MediaCleanupStatus.PENDING.value,
                next_attempt_at=now,
                verify_after=verify_after,
            )
    except IntegrityError:
        record = open_jobs.get()
    return _job_to_domain(record)


class DjangoProgressPhotoRepository(ProgressPhotoRepository):
    def save_upload_request_idempotently(
        self,
        *,
        photo: ProgressPhoto,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[ProgressPhoto, bool]:
        if not request_fingerprint:
            raise ValueError("request_fingerprint is required for idempotent uploads")

        try:
            with transaction.atomic():
                receipt = self._find_receipt(photo.owner_id, idempotency_key)
                if receipt is not None:
                    return self._replay(receipt, idempotency_key, request_fingerprint), False

                record = ProgressPhotoRecord.objects.create(
                    id=photo.id,
                    owner_id=photo.owner_id,
                    session_id=photo.session_id,
                    s3_key=photo.s3_key,
                    content_type=photo.content_type,
                    byte_length=photo.byte_length,
                    status=photo.status.value,
                    upload_authorized_until=photo.upload_authorized_until,
                )
                MediaUploadReceiptRecord.objects.create(
                    owner_id=photo.owner_id,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    photo=record,
                )
                return _record_to_domain(record), True
        except IntegrityError:
            # A concurrent request with the same (owner, key) committed first.
            # Its transaction rolled ours back, so resolve against its receipt.
            receipt = self._find_receipt(photo.owner_id, idempotency_key)
            if receipt is None:
                raise
            return self._replay(receipt, idempotency_key, request_fingerprint), False

    @staticmethod
    def _find_receipt(owner_id: UUID, idempotency_key: str) -> MediaUploadReceiptRecord | None:
        return (
            MediaUploadReceiptRecord.objects.select_related("photo")
            .filter(owner_id=owner_id, idempotency_key=idempotency_key)
            .first()
        )

    @staticmethod
    def _replay(
        receipt: MediaUploadReceiptRecord, idempotency_key: str, request_fingerprint: str
    ) -> ProgressPhoto:
        # Compared unconditionally: a receipt without a matching fingerprint
        # (including any legacy empty one) is never a valid replay.
        if receipt.request_fingerprint != request_fingerprint:
            raise IdempotencyConflictError(
                f"Idempotency key '{idempotency_key}' already used with different parameters"
            )
        return _record_to_domain(receipt.photo)

    def get_by_id(self, *, photo_id: UUID, owner_id: UUID) -> ProgressPhoto | None:
        record = ProgressPhotoRecord.objects.filter(id=photo_id, owner_id=owner_id).first()
        if record is None:
            return None
        return _record_to_domain(record)

    def confirm_if_pending(
        self, *, photo_id: UUID, owner_id: UUID, confirmed_at: datetime, final_s3_key: str
    ) -> ProgressPhoto | None:
        # A single conditional UPDATE is the arbiter: a stale finalize whose
        # photo was concurrently deleted (or already confirmed) sees 0 rows
        # updated and must never resurrect it. `final_s3_key` is persisted in
        # the SAME write as the CONFIRMED status, so the photo can never be
        # observably confirmed without its immutable key already durable.
        updated = ProgressPhotoRecord.objects.filter(
            id=photo_id, owner_id=owner_id, status=ProgressPhotoStatus.PENDING_UPLOAD.value
        ).update(
            status=ProgressPhotoStatus.CONFIRMED.value,
            confirmed_at=confirmed_at,
            final_s3_key=final_s3_key,
        )
        if updated != 1:
            return None
        return _record_to_domain(ProgressPhotoRecord.objects.get(id=photo_id))

    def refresh_upload_authorization_if_pending(
        self, *, photo_id: UUID, owner_id: UUID, authorized_until: datetime
    ) -> ProgressPhoto | None:
        # Same conditional-UPDATE arbiter: a stale replay whose photo was
        # concurrently confirmed or deleted must never mint or extend an
        # authorization for it.
        updated = ProgressPhotoRecord.objects.filter(
            id=photo_id, owner_id=owner_id, status=ProgressPhotoStatus.PENDING_UPLOAD.value
        ).update(upload_authorized_until=authorized_until)
        if updated != 1:
            return None
        return _record_to_domain(ProgressPhotoRecord.objects.get(id=photo_id))

    def list_by_owner(
        self, *, owner_id: UUID, session_id: UUID | None = None
    ) -> list[ProgressPhoto]:
        qs = ProgressPhotoRecord.objects.filter(
            owner_id=owner_id,
            status=ProgressPhotoStatus.CONFIRMED.value,
        )
        if session_id is not None:
            qs = qs.filter(session_id=session_id)
        qs = qs.order_by("-created_at")
        return [_record_to_domain(r) for r in qs]

    def tombstone_and_enqueue_cleanup(
        self, *, photo_id: UUID, owner_id: UUID, deleted_at: datetime
    ) -> tuple[ProgressPhoto, MediaCleanupJob] | None:
        with transaction.atomic():
            record = (
                ProgressPhotoRecord.objects.select_for_update()
                .filter(id=photo_id, owner_id=owner_id)
                .first()
            )
            if record is None or record.status == ProgressPhotoStatus.DELETED.value:
                return None

            record.status = ProgressPhotoStatus.DELETED.value
            record.deleted_at = deleted_at
            record.save(update_fields=["status", "deleted_at"])
            job = _enqueue_cleanup_job(
                owner_id=owner_id,
                photo_id=record.id,
                # Once CONFIRMED, the real (served) object lives at
                # final_s3_key -- s3_key is by then a mutable staging key
                # that should already be gone (deleted right after finalize
                # copied it) and is never what needs removing here. A photo
                # deleted or reconciled before ever being finalized has no
                # final_s3_key, so s3_key (the only object that could exist)
                # is still the correct target.
                s3_key=record.final_s3_key or record.s3_key,
                reason=MediaCleanupReason.PHOTO_DELETED,
                now=deleted_at,
                # A presigned PUT issued before this delete may still be
                # authorized to recreate the object at this key -- the job
                # must not be declared done before that window elapses.
                verify_after=record.upload_authorized_until,
            )
            return _record_to_domain(record), job

    def count_pending_uploads(self, *, owner_id: UUID) -> int:
        return ProgressPhotoRecord.objects.filter(
            owner_id=owner_id, status=ProgressPhotoStatus.PENDING_UPLOAD.value
        ).count()

    def find_abandoned_pending_upload_ids(
        self, *, older_than: datetime, limit: int
    ) -> list[tuple[UUID, UUID]]:
        return list(
            ProgressPhotoRecord.objects.filter(
                status=ProgressPhotoStatus.PENDING_UPLOAD.value,
                upload_authorized_until__isnull=False,
                upload_authorized_until__lt=older_than,
            )
            .order_by("upload_authorized_until")
            .values_list("id", "owner_id")[:limit]
        )


class DjangoMediaCleanupRepository(MediaCleanupRepository):
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
        return _enqueue_cleanup_job(
            owner_id=owner_id,
            photo_id=photo_id,
            s3_key=s3_key,
            reason=reason,
            now=now,
            verify_after=verify_after,
        )

    def claim(self, *, job_id: UUID, now: datetime, lease_seconds: int) -> MediaCleanupJob | None:
        # A single conditional UPDATE is the arbiter: of any number of workers
        # racing for one job, exactly one sees a row updated and owns it.
        claimed = MediaCleanupJobRecord.objects.filter(
            id=job_id,
            status=MediaCleanupStatus.PENDING.value,
            next_attempt_at__lte=now,
        ).update(
            next_attempt_at=now + timedelta(seconds=lease_seconds),
            attempts=F("attempts") + 1,
        )
        if claimed != 1:
            return None
        return _job_to_domain(MediaCleanupJobRecord.objects.get(id=job_id))

    def due_job_ids(self, *, now: datetime, limit: int) -> list[UUID]:
        return list(
            MediaCleanupJobRecord.objects.filter(
                status=MediaCleanupStatus.PENDING.value, next_attempt_at__lte=now
            )
            .order_by("next_attempt_at")
            .values_list("id", flat=True)[:limit]
        )

    def mark_done(self, *, job_id: UUID, at: datetime, expected_attempts: int) -> bool:
        # Fenced: only the worker whose claim last set `attempts` to this
        # exact value may complete the job. A stale worker (its lease
        # already expired and reclaimed by someone else) sees 0 rows
        # updated and must never complete it a second time.
        updated = MediaCleanupJobRecord.objects.filter(
            id=job_id, status=MediaCleanupStatus.PENDING.value, attempts=expected_attempts
        ).update(status=MediaCleanupStatus.DONE.value, completed_at=at, last_error=None)
        return updated == 1

    def mark_done_and_enqueue_deleted_event(
        self, *, job_id: UUID, photo_id: UUID, owner_id: UUID, at: datetime, expected_attempts: int
    ) -> bool:
        with transaction.atomic():
            updated = MediaCleanupJobRecord.objects.filter(
                id=job_id, status=MediaCleanupStatus.PENDING.value, attempts=expected_attempts
            ).update(status=MediaCleanupStatus.DONE.value, completed_at=at, last_error=None)
            if updated != 1:
                # Lost the fence: never enqueue a second outbox event for a
                # deletion another worker already completed (or is
                # completing) -- that would give the same logical deletion
                # two distinct event IDs, defeating consumer dedup.
                return False
            MediaEventOutboxRecord.objects.create(
                owner_id=owner_id,
                photo_id=photo_id,
                event_type="ProgressPhotoDeleted.v1",
                status=MediaEventStatus.PENDING.value,
                next_attempt_at=at,
            )
            return True

    def defer_verification(self, *, job_id: UUID, next_attempt_at: datetime) -> MediaCleanupJob:
        MediaCleanupJobRecord.objects.filter(id=job_id).update(next_attempt_at=next_attempt_at)
        return _job_to_domain(MediaCleanupJobRecord.objects.get(id=job_id))

    def mark_retry(self, *, job_id: UUID, error: str, next_attempt_at: datetime) -> MediaCleanupJob:
        MediaCleanupJobRecord.objects.filter(id=job_id).update(
            last_error=error, next_attempt_at=next_attempt_at
        )
        return _job_to_domain(MediaCleanupJobRecord.objects.get(id=job_id))

    def mark_dead_letter(
        self, *, job_id: UUID, error: str, at: datetime, expected_attempts: int
    ) -> bool:
        # Fenced like `mark_done`: a stale worker's failure report must
        # never regress an already-completed job's status.
        updated = MediaCleanupJobRecord.objects.filter(
            id=job_id, status=MediaCleanupStatus.PENDING.value, attempts=expected_attempts
        ).update(status=MediaCleanupStatus.DEAD_LETTER.value, last_error=error, completed_at=at)
        return updated == 1

    def get(self, *, job_id: UUID) -> MediaCleanupJob | None:
        record = MediaCleanupJobRecord.objects.filter(id=job_id).first()
        return None if record is None else _job_to_domain(record)

    def counts_by_status(self) -> dict[str, int]:
        rows = MediaCleanupJobRecord.objects.values("status").annotate(total=Count("id"))
        return {row["status"]: row["total"] for row in rows}


class DjangoMediaEventOutboxRepository(MediaEventOutboxRepository):
    def claim(
        self, *, event_id: UUID, now: datetime, lease_seconds: int
    ) -> ProgressPhotoDeletedEvent | None:
        # Same single-conditional-UPDATE arbiter as MediaCleanupJobRecord.claim.
        claimed = MediaEventOutboxRecord.objects.filter(
            id=event_id,
            status=MediaEventStatus.PENDING.value,
            next_attempt_at__lte=now,
        ).update(
            next_attempt_at=now + timedelta(seconds=lease_seconds),
            attempts=F("attempts") + 1,
        )
        if claimed != 1:
            return None
        return _event_to_domain(MediaEventOutboxRecord.objects.get(id=event_id))

    def due_event_ids(self, *, now: datetime, limit: int) -> list[UUID]:
        return list(
            MediaEventOutboxRecord.objects.filter(
                status=MediaEventStatus.PENDING.value, next_attempt_at__lte=now
            )
            .order_by("next_attempt_at")
            .values_list("id", flat=True)[:limit]
        )

    def mark_done(self, *, event_id: UUID, at: datetime) -> None:
        MediaEventOutboxRecord.objects.filter(id=event_id).update(
            status=MediaEventStatus.DONE.value, completed_at=at, last_error=None
        )

    def mark_retry(
        self, *, event_id: UUID, error: str, next_attempt_at: datetime
    ) -> ProgressPhotoDeletedEvent:
        MediaEventOutboxRecord.objects.filter(id=event_id).update(
            last_error=error, next_attempt_at=next_attempt_at
        )
        return _event_to_domain(MediaEventOutboxRecord.objects.get(id=event_id))

    def mark_dead_letter(
        self, *, event_id: UUID, error: str, at: datetime
    ) -> ProgressPhotoDeletedEvent:
        MediaEventOutboxRecord.objects.filter(id=event_id).update(
            status=MediaEventStatus.DEAD_LETTER.value, last_error=error, completed_at=at
        )
        return _event_to_domain(MediaEventOutboxRecord.objects.get(id=event_id))

    def get(self, *, event_id: UUID) -> ProgressPhotoDeletedEvent | None:
        record = MediaEventOutboxRecord.objects.filter(id=event_id).first()
        return None if record is None else _event_to_domain(record)

    def counts_by_status(self) -> dict[str, int]:
        rows = MediaEventOutboxRecord.objects.values("status").annotate(total=Count("id"))
        return {row["status"]: row["total"] for row in rows}


class DjangoWorkoutSessionLookup(WorkoutSessionLookup):
    def is_valid_owned_session(self, *, owner_id: UUID, session_id: UUID) -> bool:
        return WorkoutSessionRecord.objects.filter(id=session_id, owner_id=owner_id).exists()


class LogMediaEventPublisher(MediaEventPublisher):
    """Leaf delivery adapter for ProgressPhotoDeleted.v1: called only by
    `MediaEventOutboxService`, which owns the durable claim/retry/
    dead-letter discipline. No downstream event bus is wired yet, so
    delivery here means logged; a real bus can be substituted without
    changing the outbox's durability guarantees."""

    def publish_photo_deleted(
        self, *, event_id: UUID, photo_id: UUID, owner_id: UUID, occurred_at: datetime
    ) -> None:
        logger.info(
            "ProgressPhotoDeleted.v1 emitted for photo_id=%s, owner_id=%s, event_id=%s",
            photo_id,
            owner_id,
            event_id,
            extra={
                "event_type": "ProgressPhotoDeleted.v1",
                "event_id": str(event_id),
                "photo_id": str(photo_id),
                "user_id": str(owner_id),
                "occurred_at": occurred_at.isoformat(),
            },
        )
