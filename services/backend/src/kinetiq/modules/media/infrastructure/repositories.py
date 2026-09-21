from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from django.db import transaction

from kinetiq.modules.media.application.ports import (
    MediaEventPublisher,
    ProgressPhotoRepository,
    WorkoutSessionLookup,
)
from kinetiq.modules.media.domain.entities import (
    IdempotencyConflictError,
    ProgressPhoto,
    ProgressPhotoStatus,
)
from kinetiq.modules.media.infrastructure.models import (
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
    )


class DjangoProgressPhotoRepository(ProgressPhotoRepository):
    def save_upload_request_idempotently(
        self,
        *,
        photo: ProgressPhoto,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[ProgressPhoto, bool]:
        with transaction.atomic():
            receipt = (
                MediaUploadReceiptRecord.objects.select_related("photo")
                .filter(owner_id=photo.owner_id, idempotency_key=idempotency_key)
                .first()
            )
            if receipt is not None:
                if (
                    request_fingerprint
                    and receipt.request_fingerprint
                    and receipt.request_fingerprint != request_fingerprint
                ):
                    raise IdempotencyConflictError(
                        f"Idempotency key '{idempotency_key}' already used with "
                        "different parameters"
                    )
                return _record_to_domain(receipt.photo), False

            record = ProgressPhotoRecord.objects.create(
                id=photo.id,
                owner_id=photo.owner_id,
                session_id=photo.session_id,
                s3_key=photo.s3_key,
                content_type=photo.content_type,
                byte_length=photo.byte_length,
                status=photo.status.value,
            )
            MediaUploadReceiptRecord.objects.create(
                owner_id=photo.owner_id,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                photo=record,
            )
            return _record_to_domain(record), True

    def get_by_id(self, *, photo_id: UUID, owner_id: UUID) -> ProgressPhoto | None:
        record = ProgressPhotoRecord.objects.filter(id=photo_id, owner_id=owner_id).first()
        if record is None:
            return None
        return _record_to_domain(record)

    def save(self, *, photo: ProgressPhoto) -> ProgressPhoto:
        ProgressPhotoRecord.objects.filter(id=photo.id, owner_id=photo.owner_id).update(
            status=photo.status.value,
            confirmed_at=photo.confirmed_at,
            deleted_at=photo.deleted_at,
        )
        record = ProgressPhotoRecord.objects.get(id=photo.id)
        return _record_to_domain(record)

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

    def delete_tombstone(
        self, *, photo_id: UUID, owner_id: UUID, deleted_at: datetime
    ) -> ProgressPhoto | None:
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
            return _record_to_domain(record)


class DjangoWorkoutSessionLookup(WorkoutSessionLookup):
    def is_valid_owned_session(self, *, owner_id: UUID, session_id: UUID) -> bool:
        return WorkoutSessionRecord.objects.filter(id=session_id, owner_id=owner_id).exists()


class LogMediaEventPublisher(MediaEventPublisher):
    """Emits ProgressPhotoDeleted.v1 business event."""

    def publish_photo_deleted(self, *, photo_id: UUID, owner_id: UUID) -> None:
        logger.info(
            "ProgressPhotoDeleted.v1 emitted for photo_id=%s, owner_id=%s",
            photo_id,
            owner_id,
            extra={
                "event_type": "ProgressPhotoDeleted.v1",
                "photo_id": str(photo_id),
                "user_id": str(owner_id),
            },
        )
