from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from kinetiq.modules.media.application.cleanup import MediaCleanupService
from kinetiq.modules.media.application.use_cases import (
    DeleteProgressPhotoUseCase,
    FinalizeProgressPhotoUseCase,
    ListProgressPhotosUseCase,
    RequestProgressPhotoUploadUseCase,
    upload_request_fingerprint,
)
from kinetiq.modules.media.domain.entities import (
    IdempotencyConflictError,
    InvalidPhotoStateError,
    MediaCleanupJob,
    MediaCleanupReason,
    MediaCleanupStatus,
    MediaUploadNotCompletedError,
    MediaUploadRejectedError,
    PhotoNotFoundError,
    ProgressPhoto,
    ProgressPhotoStatus,
)
from kinetiq.modules.media.infrastructure.storage import InMemoryMediaStorageAdapter

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeCleanupRepository:
    """In-memory outbox with the same claim/lease semantics as the Django one."""

    def __init__(self) -> None:
        self.jobs: dict[UUID, MediaCleanupJob] = {}

    def enqueue(
        self,
        *,
        owner_id: UUID,
        photo_id: UUID,
        s3_key: str,
        reason: MediaCleanupReason,
        now: datetime,
    ) -> MediaCleanupJob:
        for job in self.jobs.values():
            if (
                job.photo_id == photo_id
                and job.reason == reason
                and job.status == MediaCleanupStatus.PENDING
            ):
                return job
        job = MediaCleanupJob(
            id=uuid4(),
            owner_id=owner_id,
            photo_id=photo_id,
            s3_key=s3_key,
            reason=reason,
            status=MediaCleanupStatus.PENDING,
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
        self.jobs[job.id] = job
        return job

    def claim(self, *, job_id: UUID, now: datetime, lease_seconds: int) -> MediaCleanupJob | None:
        job = self.jobs.get(job_id)
        if job is None or job.status != MediaCleanupStatus.PENDING or job.next_attempt_at > now:
            return None
        claimed = replace(
            job,
            attempts=job.attempts + 1,
            next_attempt_at=now + timedelta(seconds=lease_seconds),
        )
        self.jobs[job_id] = claimed
        return claimed

    def due_job_ids(self, *, now: datetime, limit: int) -> list[UUID]:
        due = [
            j
            for j in self.jobs.values()
            if j.status == MediaCleanupStatus.PENDING and j.next_attempt_at <= now
        ]
        return [j.id for j in sorted(due, key=lambda j: j.next_attempt_at)][:limit]

    def mark_done(self, *, job_id: UUID, at: datetime) -> None:
        self.jobs[job_id] = replace(
            self.jobs[job_id], status=MediaCleanupStatus.DONE, completed_at=at, last_error=None
        )

    def mark_retry(self, *, job_id: UUID, error: str, next_attempt_at: datetime) -> MediaCleanupJob:
        self.jobs[job_id] = replace(
            self.jobs[job_id], last_error=error, next_attempt_at=next_attempt_at
        )
        return self.jobs[job_id]

    def mark_dead_letter(self, *, job_id: UUID, error: str, at: datetime) -> MediaCleanupJob:
        self.jobs[job_id] = replace(
            self.jobs[job_id],
            status=MediaCleanupStatus.DEAD_LETTER,
            last_error=error,
            completed_at=at,
        )
        return self.jobs[job_id]

    def get(self, *, job_id: UUID) -> MediaCleanupJob | None:
        return self.jobs.get(job_id)

    def counts_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for job in self.jobs.values():
            counts[job.status.value] = counts.get(job.status.value, 0) + 1
        return counts


class FakeProgressPhotoRepository:
    def __init__(self, cleanup_repo: FakeCleanupRepository | None = None) -> None:
        self.photos: dict[UUID, ProgressPhoto] = {}
        self.receipts: dict[tuple[UUID, str], tuple[UUID, str]] = {}
        self.cleanup_repo = cleanup_repo or FakeCleanupRepository()

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
            if existing_fp != request_fingerprint:
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

    def tombstone_and_enqueue_cleanup(
        self, *, photo_id: UUID, owner_id: UUID, deleted_at: datetime
    ) -> tuple[ProgressPhoto, MediaCleanupJob] | None:
        p = self.get_by_id(photo_id=photo_id, owner_id=owner_id)
        if p is None or p.status == ProgressPhotoStatus.DELETED:
            return None
        updated = p.mark_deleted(deleted_at)
        self.photos[photo_id] = updated
        job = self.cleanup_repo.enqueue(
            owner_id=owner_id,
            photo_id=photo_id,
            s3_key=p.s3_key,
            reason=MediaCleanupReason.PHOTO_DELETED,
            now=deleted_at,
        )
        return updated, job


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


class Harness:
    """Wires every media use case over in-memory fakes and a controllable clock."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)
        self.cleanup_repo = FakeCleanupRepository()
        self.repo = FakeProgressPhotoRepository(self.cleanup_repo)
        self.storage = InMemoryMediaStorageAdapter()
        self.publisher = FakeEventPublisher()
        self.cleanup = MediaCleanupService(
            repository=self.cleanup_repo,
            storage=self.storage,
            event_publisher=self.publisher,
            max_attempts=3,
            lease_seconds=300,
            base_backoff_seconds=30,
            clock=lambda: self.now,
        )
        self.request = RequestProgressPhotoUploadUseCase(repository=self.repo, storage=self.storage)
        self.finalize = FinalizeProgressPhotoUseCase(
            repository=self.repo, storage=self.storage, cleanup=self.cleanup
        )
        self.delete = DeleteProgressPhotoUseCase(repository=self.repo, cleanup=self.cleanup)
        self.owner_id = uuid4()

    def request_upload(
        self,
        *,
        key: str,
        content_type: str = "image/jpeg",
        byte_length: int = 1024,
        session_id: UUID | None = None,
    ) -> UUID:
        return self.request.execute(
            owner_id=self.owner_id,
            session_id=session_id,
            content_type=content_type,
            byte_length=byte_length,
            idempotency_key=key,
        ).photo_id

    def upload(
        self, photo_id: UUID, *, size: int | None = None, content_type: str | None = None
    ) -> None:
        photo = self.repo.photos[photo_id]
        self.storage.put_object_data(
            s3_key=photo.s3_key,
            data=b"x" * (photo.byte_length if size is None else size),
            content_type=content_type or photo.content_type,
        )

    def confirmed_photo(self, key: str = "k") -> UUID:
        photo_id = self.request_upload(key=key)
        self.upload(photo_id)
        self.finalize.execute(owner_id=self.owner_id, photo_id=photo_id)
        return photo_id


def test_request_upload_use_case_success() -> None:
    h = Harness()

    result = h.request.execute(
        owner_id=h.owner_id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=1024,
        idempotency_key="req-1",
    )

    saved = h.repo.photos[result.photo_id]
    assert saved.status == ProgressPhotoStatus.PENDING_UPLOAD
    assert saved.content_type == "image/jpeg"
    assert "mock-s3.local" in result.upload_url
    assert result.expires_at > datetime.now(UTC)


def test_upload_url_is_bound_to_the_declared_size_and_type() -> None:
    h = Harness()
    result = h.request.execute(
        owner_id=h.owner_id,
        session_id=None,
        content_type="image/png",
        byte_length=2048,
        idempotency_key="bound",
    )

    assert "length=2048" in result.upload_url
    assert "type=image/png" in result.upload_url


def test_request_upload_idempotent_replay_returns_same_photo() -> None:
    h = Harness()

    first = h.request_upload(key="req-same")
    second = h.request_upload(key="req-same")

    assert first == second
    assert len(h.repo.photos) == 1


@pytest.mark.parametrize(
    "changed",
    [
        {"content_type": "image/png"},
        {"byte_length": 2048},
        {"session_id": uuid4()},
    ],
    ids=["content_type", "byte_length", "session_id"],
)
def test_request_upload_key_reuse_with_any_changed_field_conflicts(
    changed: dict[str, Any],
) -> None:
    h = Harness()
    if "session_id" in changed:
        h.request = RequestProgressPhotoUploadUseCase(
            repository=h.repo,
            storage=h.storage,
            session_lookup=FakeWorkoutSessionLookup({(h.owner_id, changed["session_id"])}),
        )
    h.request_upload(key="req-conflict")

    with pytest.raises(IdempotencyConflictError):
        h.request_upload(key="req-conflict", **changed)

    # The conflicting request must not have created a second photo.
    assert len(h.repo.photos) == 1


def test_request_upload_replay_for_confirmed_photo_does_not_mint_new_url() -> None:
    h = Harness()
    photo_id = h.request_upload(key="k-confirmed")
    h.upload(photo_id)
    h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)

    with pytest.raises(InvalidPhotoStateError):
        h.request_upload(key="k-confirmed")


def test_request_upload_replay_for_deleted_photo_does_not_mint_new_url() -> None:
    h = Harness()
    photo_id = h.request_upload(key="k-deleted")
    h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)

    with pytest.raises(InvalidPhotoStateError):
        h.request_upload(key="k-deleted")


def test_upload_request_fingerprint_is_canonical_and_field_sensitive() -> None:
    session_id = uuid4()
    base = upload_request_fingerprint(
        session_id=session_id, content_type="image/jpeg", byte_length=10
    )

    assert base == upload_request_fingerprint(
        session_id=session_id, content_type="image/jpeg", byte_length=10
    )
    assert base != upload_request_fingerprint(
        session_id=None, content_type="image/jpeg", byte_length=10
    )
    assert base != upload_request_fingerprint(
        session_id=session_id, content_type="image/png", byte_length=10
    )
    assert base != upload_request_fingerprint(
        session_id=session_id, content_type="image/jpeg", byte_length=11
    )


def test_request_upload_validates_session_ownership() -> None:
    h = Harness()
    other_owner_id = uuid4()
    session_id = uuid4()
    lookup = FakeWorkoutSessionLookup(valid_sessions={(other_owner_id, session_id)})
    use_case = RequestProgressPhotoUploadUseCase(
        repository=h.repo, storage=h.storage, session_lookup=lookup
    )

    with pytest.raises(ValueError, match="Session '.*' not found or not owned"):
        use_case.execute(
            owner_id=h.owner_id,
            session_id=session_id,
            content_type="image/jpeg",
            byte_length=1024,
            idempotency_key="key-1",
        )


def test_finalize_photo_not_in_storage_raises() -> None:
    h = Harness()
    photo_id = h.request_upload(key="key-finalize")

    with pytest.raises(MediaUploadNotCompletedError, match="object not found in storage"):
        h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)


def test_finalize_photo_success_after_upload() -> None:
    h = Harness()
    photo_id = h.request_upload(key="key-fin-ok")
    h.upload(photo_id)

    dto = h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)

    assert dto.status == ProgressPhotoStatus.CONFIRMED.value
    assert dto.confirmed_at is not None
    assert "mock-s3.local" in dto.url

    # Idempotent re-finalize returns confirmed photo
    re_dto = h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)
    assert re_dto.id == dto.id
    assert re_dto.status == ProgressPhotoStatus.CONFIRMED.value


@pytest.mark.parametrize(
    ("size", "content_type"),
    [
        (2048, None),  # larger than declared
        (512, None),  # smaller than declared
        (1024, "image/png"),  # different type than declared
    ],
    ids=["oversized", "undersized", "wrong-type"],
)
def test_finalize_rejects_and_removes_object_that_differs_from_declaration(
    size: int, content_type: str | None
) -> None:
    h = Harness()
    photo_id = h.request_upload(key="key-mismatch")
    s3_key = h.repo.photos[photo_id].s3_key
    h.upload(photo_id, size=size, content_type=content_type)

    with pytest.raises(MediaUploadRejectedError):
        h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)

    assert not h.storage.has_object(s3_key=s3_key)
    assert h.repo.photos[photo_id].status == ProgressPhotoStatus.PENDING_UPLOAD
    (job,) = h.cleanup_repo.jobs.values()
    assert job.reason == MediaCleanupReason.UPLOAD_REJECTED
    assert job.status == MediaCleanupStatus.DONE


def test_finalize_rejection_survives_a_storage_outage_via_durable_job() -> None:
    h = Harness()
    photo_id = h.request_upload(key="key-mismatch-outage")
    s3_key = h.repo.photos[photo_id].s3_key
    h.upload(photo_id, size=4096)
    h.storage.delete_failures_remaining = 1

    with pytest.raises(MediaUploadRejectedError):
        h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)

    # The rejected object is still in storage, but a job owns its removal.
    assert h.storage.has_object(s3_key=s3_key)
    (job,) = h.cleanup_repo.jobs.values()
    assert job.status == MediaCleanupStatus.PENDING

    h.now += timedelta(seconds=31)
    summary = h.cleanup.process_due()

    assert summary.completed == 1
    assert not h.storage.has_object(s3_key=s3_key)


def test_finalize_never_confirms_a_rejected_photo_on_retry_without_reupload() -> None:
    h = Harness()
    photo_id = h.request_upload(key="key-retry")
    h.upload(photo_id, size=4096)

    with pytest.raises(MediaUploadRejectedError):
        h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)
    with pytest.raises(MediaUploadNotCompletedError):
        h.finalize.execute(owner_id=h.owner_id, photo_id=photo_id)


def test_list_and_delete_photo_flow() -> None:
    h = Harness()
    photo1 = h.confirmed_photo("k1")
    photo2_id = h.request_upload(key="k2", content_type="image/png", byte_length=2048)
    h.upload(photo2_id)
    h.finalize.execute(owner_id=h.owner_id, photo_id=photo2_id)

    list_use_case = ListProgressPhotosUseCase(repository=h.repo, storage=h.storage)
    assert len(list_use_case.execute(owner_id=h.owner_id)) == 2

    s3_key = h.repo.photos[photo1].s3_key
    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo1)

    assert result.storage_cleanup == MediaCleanupStatus.DONE
    assert not h.storage.has_object(s3_key=s3_key)
    assert h.publisher.deleted_events == [(photo1, h.owner_id)]

    photos_after = list_use_case.execute(owner_id=h.owner_id)
    assert [p.id for p in photos_after] == [photo2_id]

    with pytest.raises(PhotoNotFoundError):
        h.delete.execute(owner_id=h.owner_id, photo_id=photo1)


def test_delete_is_durable_when_storage_is_down_and_event_waits_for_removal() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()
    s3_key = h.repo.photos[photo_id].s3_key
    h.storage.delete_failures_remaining = 1

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)

    # Tombstoned and hidden, but the caller is told removal is still pending.
    assert result.storage_cleanup == MediaCleanupStatus.PENDING
    assert h.repo.photos[photo_id].status == ProgressPhotoStatus.DELETED
    assert h.storage.has_object(s3_key=s3_key)
    assert h.publisher.deleted_events == []

    # Not yet due: the worker leaves it alone (backoff).
    assert h.cleanup.process_due().claimed == 0

    h.now += timedelta(seconds=31)
    summary = h.cleanup.process_due()

    assert (summary.claimed, summary.completed) == (1, 1)
    assert not h.storage.has_object(s3_key=s3_key)
    assert h.publisher.deleted_events == [(photo_id, h.owner_id)]
    assert h.cleanup.process_due().claimed == 0


def test_cleanup_backs_off_exponentially_then_dead_letters() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()
    h.storage.delete_failures_remaining = 100

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)
    (job_id,) = h.cleanup_repo.jobs
    assert result.storage_cleanup == MediaCleanupStatus.PENDING
    assert h.cleanup_repo.jobs[job_id].next_attempt_at == h.now + timedelta(seconds=30)

    h.now += timedelta(seconds=31)
    assert h.cleanup.attempt(job_id) == MediaCleanupStatus.PENDING
    assert h.cleanup_repo.jobs[job_id].next_attempt_at == h.now + timedelta(seconds=60)

    h.now += timedelta(seconds=61)
    assert h.cleanup.attempt(job_id) == MediaCleanupStatus.DEAD_LETTER
    job = h.cleanup_repo.jobs[job_id]
    assert job.attempts == 3
    assert job.last_error and "simulated storage outage" in job.last_error
    assert h.publisher.deleted_events == []

    # A dead-lettered job is surfaced, never silently retried forever.
    assert h.cleanup_repo.counts_by_status() == {"DEAD_LETTER": 1}
    assert h.cleanup.process_due().claimed == 0


def test_cleanup_attempt_is_exclusive_while_leased() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()
    h.storage.delete_failures_remaining = 1
    h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)
    (job_id,) = h.cleanup_repo.jobs

    h.now += timedelta(seconds=31)
    first = h.cleanup_repo.claim(job_id=job_id, now=h.now, lease_seconds=300)
    second = h.cleanup_repo.claim(job_id=job_id, now=h.now, lease_seconds=300)

    assert first is not None
    assert second is None


def test_event_publisher_failure_does_not_undo_completed_cleanup() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()

    def _boom(**_: object) -> None:
        raise RuntimeError("bus down")

    h.publisher.publish_photo_deleted = _boom  # type: ignore[method-assign]

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)

    assert result.storage_cleanup == MediaCleanupStatus.DONE


def test_delete_of_another_owners_photo_is_not_found() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()

    with pytest.raises(PhotoNotFoundError):
        h.delete.execute(owner_id=uuid4(), photo_id=photo_id)
    assert h.cleanup_repo.jobs == {}
