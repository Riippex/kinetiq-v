from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_PHOTO_BYTE_LENGTH = 10 * 1024 * 1024  # 10 MB


class ProgressPhotoStatus(StrEnum):
    PENDING_UPLOAD = "PENDING_UPLOAD"
    CONFIRMED = "CONFIRMED"
    DELETED = "DELETED"


class MediaError(Exception):
    """Base exception for media domain errors."""


class IdempotencyConflictError(MediaError):
    """Raised when an idempotency key is reused with mismatched parameters."""


class UnsupportedMediaTypeError(MediaError):
    """Raised when an uploaded media type is not supported."""


class MediaPayloadTooLargeError(MediaError):
    """Raised when the specified file size exceeds the allowed threshold."""


class PhotoNotFoundError(MediaError):
    """Raised when a progress photo does not exist or has been deleted."""


class InvalidPhotoStateError(MediaError):
    """Raised when attempting an invalid lifecycle transition on a photo."""


class MediaUploadNotCompletedError(MediaError):
    """Raised when finalizing a photo whose object does not exist in storage."""


class PhotoOwnershipError(MediaError):
    """Raised when an operation violates photo ownership."""


class MediaUploadRejectedError(MediaError):
    """Raised when the uploaded object does not match the declared photo
    (size or content type), so it must not be confirmed."""


class MediaStorageError(MediaError):
    """Raised when the object store fails to complete an operation."""


@dataclass(frozen=True, slots=True)
class ProgressPhoto:
    id: UUID
    owner_id: UUID
    session_id: UUID | None
    s3_key: str
    content_type: str
    byte_length: int
    status: ProgressPhotoStatus
    created_at: datetime
    confirmed_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.content_type not in ALLOWED_MEDIA_TYPES:
            raise UnsupportedMediaTypeError(
                f"Unsupported media type '{self.content_type}'. "
                f"Allowed types: {sorted(ALLOWED_MEDIA_TYPES)}"
            )
        if self.byte_length <= 0:
            raise ValueError("Photo byte length must be strictly positive")
        if self.byte_length > MAX_PHOTO_BYTE_LENGTH:
            raise MediaPayloadTooLargeError(
                f"Photo byte length {self.byte_length} exceeds limit of "
                f"{MAX_PHOTO_BYTE_LENGTH} bytes"
            )
        if not self.s3_key.strip():
            raise ValueError("s3_key cannot be empty")

    def confirm(self, confirmed_at: datetime) -> ProgressPhoto:
        if self.status == ProgressPhotoStatus.DELETED:
            raise InvalidPhotoStateError("Cannot confirm a deleted progress photo")
        return ProgressPhoto(
            id=self.id,
            owner_id=self.owner_id,
            session_id=self.session_id,
            s3_key=self.s3_key,
            content_type=self.content_type,
            byte_length=self.byte_length,
            status=ProgressPhotoStatus.CONFIRMED,
            created_at=self.created_at,
            confirmed_at=confirmed_at,
            deleted_at=None,
        )

    def mark_deleted(self, deleted_at: datetime) -> ProgressPhoto:
        return ProgressPhoto(
            id=self.id,
            owner_id=self.owner_id,
            session_id=self.session_id,
            s3_key=self.s3_key,
            content_type=self.content_type,
            byte_length=self.byte_length,
            status=ProgressPhotoStatus.DELETED,
            created_at=self.created_at,
            confirmed_at=self.confirmed_at,
            deleted_at=deleted_at,
        )


class MediaCleanupStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    DEAD_LETTER = "DEAD_LETTER"


class MediaCleanupReason(StrEnum):
    PHOTO_DELETED = "PHOTO_DELETED"
    UPLOAD_REJECTED = "UPLOAD_REJECTED"


@dataclass(frozen=True, slots=True)
class StoredObjectInfo:
    """What the object store actually holds for a key."""

    content_length: int
    content_type: str | None


@dataclass(frozen=True, slots=True)
class MediaCleanupJob:
    """Durable, retryable request to remove an object from private storage."""

    id: UUID
    owner_id: UUID
    photo_id: UUID
    s3_key: str
    reason: MediaCleanupReason
    status: MediaCleanupStatus
    attempts: int
    next_attempt_at: datetime
    created_at: datetime
    last_error: str | None = None
    completed_at: datetime | None = None
