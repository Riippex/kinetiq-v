from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from kinetiq.modules.media.application.use_cases import (
    DeleteProgressPhotoUseCase,
    FinalizeProgressPhotoUseCase,
    ListProgressPhotosUseCase,
    RequestProgressPhotoUploadUseCase,
)
from kinetiq.modules.media.domain.entities import (
    IdempotencyConflictError,
    MediaUploadNotCompletedError,
    PhotoNotFoundError,
    ProgressPhoto,
    ProgressPhotoStatus,
)
from kinetiq.modules.media.infrastructure.storage import InMemoryMediaStorageAdapter


class FakeProgressPhotoRepository:
    def __init__(self) -> None:
        self.photos: dict[UUID, ProgressPhoto] = {}
        self.receipts: dict[tuple[UUID, str], tuple[UUID, str]] = {}

    def save_upload_request_idempotently(
        self,
        *,
        photo: ProgressPhoto,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[ProgressPhoto, bool]:
        key = (photo.owner_id, idempotency_key)
        if key in self.receipts:
            existing_id, existing_fp = self.receipts[key]
            if request_fingerprint and existing_fp and existing_fp != request_fingerprint:
                raise IdempotencyConflictError("Mismatched idempotency fingerprint")
            return self.photos[existing_id], False

        self.photos[photo.id] = photo
        self.receipts[key] = (photo.id, request_fingerprint)
        return photo, True

    def get_by_id(self, *, photo_id: UUID, owner_id: UUID) -> ProgressPhoto | None:
        p = self.photos.get(photo_id)
        if p and p.owner_id == owner_id:
            return p
        return None

    def save(self, *, photo: ProgressPhoto) -> ProgressPhoto:
        self.photos[photo.id] = photo
        return photo

    def list_by_owner(
        self, *, owner_id: UUID, session_id: UUID | None = None
    ) -> list[ProgressPhoto]:
        result = [
            p
            for p in self.photos.values()
            if p.owner_id == owner_id and p.status == ProgressPhotoStatus.CONFIRMED
        ]
        if session_id is not None:
            result = [p for p in result if p.session_id == session_id]
        return sorted(result, key=lambda x: x.created_at, reverse=True)

    def delete_tombstone(
        self, *, photo_id: UUID, owner_id: UUID, deleted_at: datetime
    ) -> ProgressPhoto | None:
        p = self.get_by_id(photo_id=photo_id, owner_id=owner_id)
        if p is None or p.status == ProgressPhotoStatus.DELETED:
            return None
        updated = p.mark_deleted(deleted_at)
        self.photos[photo_id] = updated
        return updated


class FakeWorkoutSessionLookup:
    def __init__(self, valid_sessions: set[tuple[UUID, UUID]]) -> None:
        self.valid_sessions = valid_sessions

    def is_valid_owned_session(self, *, owner_id: UUID, session_id: UUID) -> bool:
        return (owner_id, session_id) in self.valid_sessions


class FakeEventPublisher:
    def __init__(self) -> None:
        self.deleted_events: list[tuple[UUID, UUID]] = []

    def publish_photo_deleted(self, *, photo_id: UUID, owner_id: UUID) -> None:
        self.deleted_events.append((photo_id, owner_id))


def test_request_upload_use_case_success() -> None:
    repo = FakeProgressPhotoRepository()
    storage = InMemoryMediaStorageAdapter()
    owner_id = uuid4()

    use_case = RequestProgressPhotoUploadUseCase(repository=repo, storage=storage)
    result = use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="req-1",
    )

    assert result.photo_id in repo.photos
    saved = repo.photos[result.photo_id]
    assert saved.status == ProgressPhotoStatus.PENDING_UPLOAD
    assert saved.content_type == "image/jpeg"
    assert "mock-s3.local" in result.upload_url
    assert result.expires_at > datetime.now(UTC)


def test_request_upload_idempotency() -> None:
    repo = FakeProgressPhotoRepository()
    storage = InMemoryMediaStorageAdapter()
    owner_id = uuid4()

    use_case = RequestProgressPhotoUploadUseCase(repository=repo, storage=storage)
    res1 = use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="req-same",
        request_fingerprint="fp1",
    )
    res2 = use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="req-same",
        request_fingerprint="fp1",
    )

    assert res1.photo_id == res2.photo_id
    assert len(repo.photos) == 1


def test_request_upload_idempotency_conflict() -> None:
    repo = FakeProgressPhotoRepository()
    storage = InMemoryMediaStorageAdapter()
    owner_id = uuid4()

    use_case = RequestProgressPhotoUploadUseCase(repository=repo, storage=storage)
    use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="req-conflict",
        request_fingerprint="fp1",
    )

    with pytest.raises(IdempotencyConflictError):
        use_case.execute(
            owner_id=owner_id,
            session_id=None,
            content_type="image/png",
            byte_length=2048,
            idempotency_key="req-conflict",
            request_fingerprint="fp2",
        )


def test_request_upload_validates_session_ownership() -> None:
    repo = FakeProgressPhotoRepository()
    storage = InMemoryMediaStorageAdapter()
    owner_id = uuid4()
    other_owner_id = uuid4()
    session_id = uuid4()
    lookup = FakeWorkoutSessionLookup(valid_sessions={(other_owner_id, session_id)})

    use_case = RequestProgressPhotoUploadUseCase(
        repository=repo, storage=storage, session_lookup=lookup
    )

    with pytest.raises(ValueError, match="Session '.*' not found or not owned"):
        use_case.execute(
            owner_id=owner_id,
            session_id=session_id,
            content_type="image/jpeg",
            byte_length=1024,
            idempotency_key="key-1",
        )


def test_finalize_photo_not_in_storage_raises() -> None:
    repo = FakeProgressPhotoRepository()
    storage = InMemoryMediaStorageAdapter()
    owner_id = uuid4()

    req_use_case = RequestProgressPhotoUploadUseCase(repository=repo, storage=storage)
    req = req_use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="key-finalize",
    )

    fin_use_case = FinalizeProgressPhotoUseCase(repository=repo, storage=storage)
    with pytest.raises(MediaUploadNotCompletedError, match="object not found in storage"):
        fin_use_case.execute(owner_id=owner_id, photo_id=req.photo_id)


def test_finalize_photo_success_after_upload() -> None:
    repo = FakeProgressPhotoRepository()
    storage = InMemoryMediaStorageAdapter()
    owner_id = uuid4()

    req_use_case = RequestProgressPhotoUploadUseCase(repository=repo, storage=storage)
    req = req_use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="key-fin-ok",
    )

    photo = repo.photos[req.photo_id]
    # Simulate client uploading file to storage
    storage.put_object_data(s3_key=photo.s3_key, data=b"binary-content")

    fin_use_case = FinalizeProgressPhotoUseCase(repository=repo, storage=storage)
    dto = fin_use_case.execute(owner_id=owner_id, photo_id=req.photo_id)

    assert dto.status == ProgressPhotoStatus.CONFIRMED.value
    assert dto.confirmed_at is not None
    assert "mock-s3.local" in dto.url

    # Idempotent re-finalize returns confirmed photo
    re_dto = fin_use_case.execute(owner_id=owner_id, photo_id=req.photo_id)
    assert re_dto.id == dto.id
    assert re_dto.status == ProgressPhotoStatus.CONFIRMED.value


def test_list_and_delete_photo_flow() -> None:
    repo = FakeProgressPhotoRepository()
    storage = InMemoryMediaStorageAdapter()
    publisher = FakeEventPublisher()
    owner_id = uuid4()

    # Create & confirm two photos
    req_use_case = RequestProgressPhotoUploadUseCase(repository=repo, storage=storage)
    fin_use_case = FinalizeProgressPhotoUseCase(repository=repo, storage=storage)

    req1 = req_use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="k1",
    )
    storage.put_object_data(s3_key=repo.photos[req1.photo_id].s3_key)
    fin_use_case.execute(owner_id=owner_id, photo_id=req1.photo_id)

    req2 = req_use_case.execute(
        owner_id=owner_id,
        session_id=None,
        content_type="image/png",
        byte_length=2048,
        idempotency_key="k2",
    )
    storage.put_object_data(s3_key=repo.photos[req2.photo_id].s3_key)
    fin_use_case.execute(owner_id=owner_id, photo_id=req2.photo_id)

    # List photos
    list_use_case = ListProgressPhotosUseCase(repository=repo, storage=storage)
    photos = list_use_case.execute(owner_id=owner_id)
    assert len(photos) == 2

    # Delete photo 1
    del_use_case = DeleteProgressPhotoUseCase(
        repository=repo, storage=storage, event_publisher=publisher
    )
    success = del_use_case.execute(owner_id=owner_id, photo_id=req1.photo_id)
    assert success is True

    # Storage object cleaned up
    assert not storage.object_exists(s3_key=repo.photos[req1.photo_id].s3_key)
    # Event emitted
    assert (req1.photo_id, owner_id) in publisher.deleted_events

    # List only returns remaining active photo
    photos_after = list_use_case.execute(owner_id=owner_id)
    assert len(photos_after) == 1
    assert photos_after[0].id == req2.photo_id

    # Deleting again raises PhotoNotFoundError
    with pytest.raises(PhotoNotFoundError):
        del_use_case.execute(owner_id=owner_id, photo_id=req1.photo_id)
