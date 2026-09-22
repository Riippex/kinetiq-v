from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from kinetiq.modules.media.application.cleanup import MediaCleanupService
from kinetiq.modules.media.application.ports import (
    MediaStoragePort,
    ProgressPhotoRepository,
    WorkoutSessionLookup,
)
from kinetiq.modules.media.domain.entities import (
    ALLOWED_MEDIA_TYPES,
    MAX_PENDING_UPLOADS_PER_OWNER,
    MAX_PHOTO_BYTE_LENGTH,
    InvalidPhotoStateError,
    MediaCleanupReason,
    MediaCleanupStatus,
    MediaPayloadTooLargeError,
    MediaUploadNotCompletedError,
    MediaUploadRejectedError,
    PhotoNotFoundError,
    ProgressPhoto,
    ProgressPhotoStatus,
    TooManyPendingUploadsError,
    UnsupportedMediaTypeError,
)

_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def upload_request_fingerprint(
    *, session_id: UUID | None, content_type: str, byte_length: int
) -> str:
    """Canonical fingerprint of every field of an upload request.

    The idempotency key is scoped to the owner, so the owner is not part of
    the fingerprint. Reusing a key with any different field is a conflict.
    """
    canonical = json.dumps(
        {
            "session_id": str(session_id) if session_id is not None else None,
            "content_type": content_type,
            "byte_length": byte_length,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


@dataclass(frozen=True, slots=True)
class DeleteProgressPhotoResultDTO:
    """`storage_cleanup` is DONE only once the object is confirmed gone;
    PENDING means a durable, retried cleanup job still owns the removal."""

    photo_id: UUID
    storage_cleanup: MediaCleanupStatus


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
        authorized_until = now + timedelta(seconds=self._ttl_seconds)

        photo = ProgressPhoto(
            id=photo_id,
            owner_id=owner_id,
            session_id=session_id,
            s3_key=s3_key,
            content_type=content_type,
            byte_length=byte_length,
            status=ProgressPhotoStatus.PENDING_UPLOAD,
            created_at=now,
            upload_authorized_until=authorized_until,
        )

        saved_photo, created = self._repository.save_upload_request_idempotently(
            photo=photo,
            idempotency_key=idempotency_key,
            request_fingerprint=upload_request_fingerprint(
                session_id=session_id, content_type=content_type, byte_length=byte_length
            ),
        )

        if created and self._repository.count_pending_uploads(owner_id=owner_id) > (
            MAX_PENDING_UPLOADS_PER_OWNER
        ):
            # Only a genuinely new upload can push the count over the cap --
            # an idempotent replay of an existing key must never be blocked
            # by it. No presigned URL was ever issued for this row (we bail
            # before generating one below), so tombstoning it now is a clean
            # rollback via the same durable cleanup path as an owner-initiated
            # delete, not a partial/inconsistent state.
            self._repository.tombstone_and_enqueue_cleanup(
                photo_id=saved_photo.id, owner_id=owner_id, deleted_at=now
            )
            raise TooManyPendingUploadsError(
                f"Owner already has {MAX_PENDING_UPLOADS_PER_OWNER} or more unfinalized "
                "uploads outstanding; finalize or delete one before requesting another"
            )

        # A replayed key must never mint a fresh upload URL for a photo that is
        # already confirmed or deleted: that would let a caller write to the
        # key of a deleted private photo.
        if saved_photo.status != ProgressPhotoStatus.PENDING_UPLOAD:
            raise InvalidPhotoStateError(
                f"Upload for idempotency key '{idempotency_key}' can no longer be "
                f"requested: photo is {saved_photo.status.value}"
            )

        # Every call issues a fresh presigned URL, so the object can be
        # recreated at `s3_key` until THIS authorization -- persist the
        # extended deadline (including on an idempotent replay) so deletion
        # cleanup later knows to wait for it. Conditioned on the photo still
        # being PENDING_UPLOAD: a concurrent finalize or delete between the
        # check above and this write must never be overwritten by a stale
        # replay minting a fresh authorization.
        if saved_photo.upload_authorized_until != authorized_until:
            refreshed = self._repository.refresh_upload_authorization_if_pending(
                photo_id=saved_photo.id, owner_id=owner_id, authorized_until=authorized_until
            )
            if refreshed is None:
                current = self._repository.get_by_id(photo_id=saved_photo.id, owner_id=owner_id)
                status = current.status.value if current is not None else "DELETED"
                raise InvalidPhotoStateError(
                    f"Upload for idempotency key '{idempotency_key}' can no longer be "
                    f"requested: photo is {status}"
                )
            saved_photo = refreshed

        upload_url = self._storage.generate_upload_url(
            s3_key=saved_photo.s3_key,
            content_type=saved_photo.content_type,
            byte_length=saved_photo.byte_length,
            ttl_seconds=self._ttl_seconds,
        )

        return UploadRequestDTO(
            photo_id=saved_photo.id,
            upload_url=upload_url,
            expires_at=authorized_until,
        )


class FinalizeProgressPhotoUseCase:
    def __init__(
        self,
        repository: ProgressPhotoRepository,
        storage: MediaStoragePort,
        cleanup: MediaCleanupService,
        ttl_seconds: int = 900,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._cleanup = cleanup
        self._ttl_seconds = ttl_seconds

    def execute(self, *, owner_id: UUID, photo_id: UUID) -> ProgressPhotoDTO:
        photo = self._repository.get_by_id(photo_id=photo_id, owner_id=owner_id)
        if photo is None or photo.status == ProgressPhotoStatus.DELETED:
            raise PhotoNotFoundError(f"Progress photo '{photo_id}' not found")

        if photo.status == ProgressPhotoStatus.CONFIRMED:
            return self._to_dto(photo)

        stored = self._storage.get_object_info(s3_key=photo.s3_key)
        if stored is None:
            raise MediaUploadNotCompletedError(
                f"Cannot finalize photo '{photo_id}': object not found in storage"
            )

        # The declared metadata was validated at request time, but the client
        # controls what it actually uploads. Confirm only an object that
        # matches what was declared and authorized; remove anything else.
        if stored.content_length != photo.byte_length or stored.content_type != photo.content_type:
            job = self._cleanup.enqueue_object_cleanup(
                owner_id=owner_id,
                photo_id=photo.id,
                s3_key=photo.s3_key,
                reason=MediaCleanupReason.UPLOAD_REJECTED,
            )
            self._cleanup.attempt(job.id)
            raise MediaUploadRejectedError(
                f"Uploaded object for photo '{photo_id}' does not match the declared "
                f"{photo.content_type} of {photo.byte_length} bytes "
                f"(stored: {stored.content_type}, {stored.content_length} bytes)"
            )

        confirmed = self._repository.confirm_if_pending(
            photo_id=photo_id, owner_id=owner_id, confirmed_at=datetime.now(UTC)
        )
        if confirmed is None:
            # Lost the race: the photo was concurrently confirmed (another
            # finalize call) or deleted since the read above. Re-fetch to
            # tell an idempotent re-finalize apart from a real deletion --
            # never resurrect a deleted photo by returning our stale intent.
            current = self._repository.get_by_id(photo_id=photo_id, owner_id=owner_id)
            if current is not None and current.status == ProgressPhotoStatus.CONFIRMED:
                return self._to_dto(current)
            raise PhotoNotFoundError(f"Progress photo '{photo_id}' not found")
        return self._to_dto(confirmed)

    def _to_dto(self, photo: ProgressPhoto) -> ProgressPhotoDTO:
        return ProgressPhotoDTO(
            id=photo.id,
            session_id=photo.session_id,
            content_type=photo.content_type,
            byte_length=photo.byte_length,
            url=self._storage.generate_download_url(
                s3_key=photo.s3_key, ttl_seconds=self._ttl_seconds
            ),
            status=photo.status.value,
            created_at=photo.created_at,
            confirmed_at=photo.confirmed_at,
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
        cleanup: MediaCleanupService,
    ) -> None:
        self._repository = repository
        self._cleanup = cleanup

    def execute(self, *, owner_id: UUID, photo_id: UUID) -> DeleteProgressPhotoResultDTO:
        # The tombstone and the cleanup job commit atomically, so a deleted
        # photo can never exist without a durable job owning its object.
        deleted = self._repository.tombstone_and_enqueue_cleanup(
            photo_id=photo_id, owner_id=owner_id, deleted_at=self._cleanup.now()
        )
        if deleted is None:
            raise PhotoNotFoundError(f"Progress photo '{photo_id}' not found")
        _, job = deleted

        # Try now; on failure the job stays PENDING and the worker retries it.
        status = self._cleanup.attempt(job.id)
        return DeleteProgressPhotoResultDTO(photo_id=photo_id, storage_cleanup=status)


@dataclass(frozen=True, slots=True)
class ReconcileAbandonedUploadsResult:
    reconciled: int


class ReconcileAbandonedUploadsUseCase:
    """Durably cleans up PENDING_UPLOAD photos an owner never finalized:
    without this, an interrupted client -- or an abusive account -- could
    accumulate unbounded private S3 objects and receipt rows, since
    MAX_PENDING_UPLOADS_PER_OWNER only bounds the *rate* of new
    accumulation, not existing rows. Intended to run periodically alongside
    `process_media_cleanup` (see the management command)."""

    def __init__(
        self,
        repository: ProgressPhotoRepository,
        cleanup: MediaCleanupService,
    ) -> None:
        self._repository = repository
        self._cleanup = cleanup

    def execute(self, *, limit: int = 100) -> ReconcileAbandonedUploadsResult:
        now = self._cleanup.now()
        # Same margin as deletion cleanup's post-expiry verification: a PUT
        # started just before the authorization deadline can still be
        # mid-transfer past it, and the client's finalize call right behind
        # it must not lose a race against reconciliation tombstoning the row.
        cutoff = now - timedelta(seconds=self._cleanup.put_completion_grace_seconds)
        abandoned = self._repository.find_abandoned_pending_upload_ids(
            older_than=cutoff, limit=limit
        )

        reconciled = 0
        for photo_id, owner_id in abandoned:
            deleted = self._repository.tombstone_and_enqueue_cleanup(
                photo_id=photo_id, owner_id=owner_id, deleted_at=now
            )
            if deleted is None:
                continue
            _, job = deleted
            self._cleanup.attempt(job.id)
            reconciled += 1

        return ReconcileAbandonedUploadsResult(reconciled=reconciled)
