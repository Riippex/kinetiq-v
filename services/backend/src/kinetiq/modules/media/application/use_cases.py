from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from kinetiq.modules.media.application.ports import (
    MediaEventPublisher,
    MediaStoragePort,
    ProgressPhotoRepository,
    WorkoutSessionLookup,
)
from kinetiq.modules.media.domain.entities import (
    ALLOWED_MEDIA_TYPES,
    MAX_PHOTO_BYTE_LENGTH,
    MediaPayloadTooLargeError,
    MediaUploadNotCompletedError,
    PhotoNotFoundError,
    ProgressPhoto,
    ProgressPhotoStatus,
    UnsupportedMediaTypeError,
)

_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True, slots=True)
class UploadRequestDTO:
    photo_id: UUID
    upload_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ProgressPhotoDTO:
    id: UUID
    session_id: UUID | None
    content_type: str
    byte_length: int
    url: str
    status: str
    created_at: datetime
    confirmed_at: datetime | None


class RequestProgressPhotoUploadUseCase:
    def __init__(
        self,
        repository: ProgressPhotoRepository,
        storage: MediaStoragePort,
        session_lookup: WorkoutSessionLookup | None = None,
        ttl_seconds: int = 900,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._session_lookup = session_lookup
        self._ttl_seconds = ttl_seconds

    def execute(
        self,
        *,
        owner_id: UUID,
        session_id: UUID | None,
        content_type: str,
        byte_length: int,
        idempotency_key: str,
        request_fingerprint: str = "",
    ) -> UploadRequestDTO:
        if content_type not in ALLOWED_MEDIA_TYPES:
            raise UnsupportedMediaTypeError(
                f"Unsupported media type '{content_type}'. "
                f"Allowed types: {sorted(ALLOWED_MEDIA_TYPES)}"
            )
        if byte_length <= 0:
            raise ValueError("byte_length must be strictly positive")
        if byte_length > MAX_PHOTO_BYTE_LENGTH:
            raise MediaPayloadTooLargeError(
                f"byte_length {byte_length} exceeds max allowed {MAX_PHOTO_BYTE_LENGTH}"
            )
        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")

        if session_id is not None and self._session_lookup is not None:
            if not self._session_lookup.is_valid_owned_session(
                owner_id=owner_id, session_id=session_id
            ):
                raise ValueError(f"Session '{session_id}' not found or not owned by user")

        ext = _CONTENT_TYPE_EXTENSIONS.get(content_type, ".jpg")
        photo_id = uuid4()
        s3_key = f"photos/{owner_id}/{photo_id}{ext}"
        now = datetime.now(UTC)

        photo = ProgressPhoto(
            id=photo_id,
            owner_id=owner_id,
            session_id=session_id,
            s3_key=s3_key,
            content_type=content_type,
            byte_length=byte_length,
            status=ProgressPhotoStatus.PENDING_UPLOAD,
            created_at=now,
        )

        saved_photo, _ = self._repository.save_upload_request_idempotently(
            photo=photo,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

        upload_url = self._storage.generate_upload_url(
            s3_key=saved_photo.s3_key,
            content_type=saved_photo.content_type,
            ttl_seconds=self._ttl_seconds,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)

        return UploadRequestDTO(
            photo_id=saved_photo.id,
            upload_url=upload_url,
            expires_at=expires_at,
        )


class FinalizeProgressPhotoUseCase:
    def __init__(
        self,
        repository: ProgressPhotoRepository,
        storage: MediaStoragePort,
        ttl_seconds: int = 900,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._ttl_seconds = ttl_seconds

    def execute(self, *, owner_id: UUID, photo_id: UUID) -> ProgressPhotoDTO:
        photo = self._repository.get_by_id(photo_id=photo_id, owner_id=owner_id)
        if photo is None or photo.status == ProgressPhotoStatus.DELETED:
            raise PhotoNotFoundError(f"Progress photo '{photo_id}' not found")

        if photo.status == ProgressPhotoStatus.CONFIRMED:
            download_url = self._storage.generate_download_url(
                s3_key=photo.s3_key, ttl_seconds=self._ttl_seconds
            )
            return ProgressPhotoDTO(
                id=photo.id,
                session_id=photo.session_id,
                content_type=photo.content_type,
                byte_length=photo.byte_length,
                url=download_url,
                status=photo.status.value,
                created_at=photo.created_at,
                confirmed_at=photo.confirmed_at,
            )

        if not self._storage.object_exists(s3_key=photo.s3_key):
            raise MediaUploadNotCompletedError(
                f"Cannot finalize photo '{photo_id}': object not found in storage"
            )

        now = datetime.now(UTC)
        confirmed_photo = photo.confirm(confirmed_at=now)
        saved_photo = self._repository.save(photo=confirmed_photo)

        download_url = self._storage.generate_download_url(
            s3_key=saved_photo.s3_key, ttl_seconds=self._ttl_seconds
        )
        return ProgressPhotoDTO(
            id=saved_photo.id,
            session_id=saved_photo.session_id,
            content_type=saved_photo.content_type,
            byte_length=saved_photo.byte_length,
            url=download_url,
            status=saved_photo.status.value,
            created_at=saved_photo.created_at,
            confirmed_at=saved_photo.confirmed_at,
        )


class ListProgressPhotosUseCase:
    def __init__(
        self,
        repository: ProgressPhotoRepository,
        storage: MediaStoragePort,
        ttl_seconds: int = 900,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._ttl_seconds = ttl_seconds

    def execute(
        self, *, owner_id: UUID, session_id: UUID | None = None
    ) -> list[ProgressPhotoDTO]:
        photos = self._repository.list_by_owner(owner_id=owner_id, session_id=session_id)
        result: list[ProgressPhotoDTO] = []
        for p in photos:
            if p.status == ProgressPhotoStatus.DELETED:
                continue
            download_url = self._storage.generate_download_url(
                s3_key=p.s3_key, ttl_seconds=self._ttl_seconds
            )
            result.append(
                ProgressPhotoDTO(
                    id=p.id,
                    session_id=p.session_id,
                    content_type=p.content_type,
                    byte_length=p.byte_length,
                    url=download_url,
                    status=p.status.value,
                    created_at=p.created_at,
                    confirmed_at=p.confirmed_at,
                )
            )
        return result


class DeleteProgressPhotoUseCase:
    def __init__(
        self,
        repository: ProgressPhotoRepository,
        storage: MediaStoragePort,
        event_publisher: MediaEventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._event_publisher = event_publisher

    def execute(self, *, owner_id: UUID, photo_id: UUID) -> bool:
        now = datetime.now(UTC)
        deleted_photo = self._repository.delete_tombstone(
            photo_id=photo_id, owner_id=owner_id, deleted_at=now
        )
        if deleted_photo is None:
            raise PhotoNotFoundError(f"Progress photo '{photo_id}' not found")

        # Object cleanup in storage is idempotent and best-effort
        self._storage.delete_object(s3_key=deleted_photo.s3_key)

        if self._event_publisher is not None:
            self._event_publisher.publish_photo_deleted(photo_id=photo_id, owner_id=owner_id)

        return True
