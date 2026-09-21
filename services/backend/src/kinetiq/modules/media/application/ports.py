from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from kinetiq.modules.media.domain.entities import ProgressPhoto


class MediaStoragePort(Protocol):
    def generate_upload_url(
        self, *, s3_key: str, content_type: str, ttl_seconds: int = 900
    ) -> str: ...

    def generate_download_url(self, *, s3_key: str, ttl_seconds: int = 900) -> str: ...

    def object_exists(self, *, s3_key: str) -> bool: ...

    def delete_object(self, *, s3_key: str) -> None: ...


class ProgressPhotoRepository(Protocol):
    def save_upload_request_idempotently(
        self,
        *,
        photo: ProgressPhoto,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[ProgressPhoto, bool]: ...

    def get_by_id(self, *, photo_id: UUID, owner_id: UUID) -> ProgressPhoto | None: ...

    def save(self, *, photo: ProgressPhoto) -> ProgressPhoto: ...

    def list_by_owner(
        self, *, owner_id: UUID, session_id: UUID | None = None
    ) -> list[ProgressPhoto]: ...

    def delete_tombstone(
        self, *, photo_id: UUID, owner_id: UUID, deleted_at: datetime
    ) -> ProgressPhoto | None: ...


class WorkoutSessionLookup(Protocol):
    def is_valid_owned_session(self, *, owner_id: UUID, session_id: UUID) -> bool: ...


class MediaEventPublisher(Protocol):
    def publish_photo_deleted(self, *, photo_id: UUID, owner_id: UUID) -> None: ...
