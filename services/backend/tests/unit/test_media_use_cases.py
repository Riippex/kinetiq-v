from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from kinetiq.modules.media.application.cleanup import MediaCleanupService
from kinetiq.modules.media.application.event_outbox import MediaEventOutboxService, OutboxRunSummary
from kinetiq.modules.media.application.use_cases import (
    DeleteProgressPhotoUseCase,
    FinalizeProgressPhotoUseCase,
    ListProgressPhotosUseCase,
    ReconcileAbandonedUploadsUseCase,
    RequestProgressPhotoUploadUseCase,
    upload_request_fingerprint,
)
from kinetiq.modules.media.domain.entities import (
    MAX_PENDING_UPLOADS_PER_OWNER,
    IdempotencyConflictError,
    InvalidPhotoStateError,
    MediaCleanupJob,
    MediaCleanupReason,
    MediaCleanupStatus,
    MediaEventStatus,
    MediaUploadNotCompletedError,
    MediaUploadRejectedError,
    PhotoNotFoundError,
    ProgressPhoto,
    ProgressPhotoDeletedEvent,
    ProgressPhotoStatus,
    TooManyPendingUploadsError,
)
from kinetiq.modules.media.infrastructure.storage import InMemoryMediaStorageAdapter

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeMediaEventOutboxRepository:
    """In-memory outbox with the same claim/lease semantics as the Django one."""

    def __init__(self) -> None:
        self.events: dict[UUID, ProgressPhotoDeletedEvent] = {}

    def enqueue(
        self, *, owner_id: UUID, photo_id: UUID, now: datetime
    ) -> ProgressPhotoDeletedEvent:
        event = ProgressPhotoDeletedEvent(
            id=uuid4(),
            owner_id=owner_id,
            photo_id=photo_id,
            status=MediaEventStatus.PENDING,
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
        self.events[event.id] = event
        return event

    def claim(
        self, *, event_id: UUID, now: datetime, lease_seconds: int
    ) -> ProgressPhotoDeletedEvent | None:
        event = self.events.get(event_id)
        if event is None or event.status != MediaEventStatus.PENDING or event.next_attempt_at > now:
            return None
        claimed = replace(
            event,
            attempts=event.attempts + 1,
            next_attempt_at=now + timedelta(seconds=lease_seconds),
        )
        self.events[event_id] = claimed
        return claimed

    def due_event_ids(self, *, now: datetime, limit: int) -> list[UUID]:
        due = [
            e
            for e in self.events.values()
            if e.status == MediaEventStatus.PENDING and e.next_attempt_at <= now
        ]
        return [e.id for e in sorted(due, key=lambda e: e.next_attempt_at)][:limit]

    def mark_done(self, *, event_id: UUID, at: datetime) -> None:
        self.events[event_id] = replace(
            self.events[event_id], status=MediaEventStatus.DONE, completed_at=at, last_error=None
        )

    def mark_retry(
        self, *, event_id: UUID, error: str, next_attempt_at: datetime
    ) -> ProgressPhotoDeletedEvent:
        self.events[event_id] = replace(
            self.events[event_id], last_error=error, next_attempt_at=next_attempt_at
        )
        return self.events[event_id]

    def mark_dead_letter(
        self, *, event_id: UUID, error: str, at: datetime
    ) -> ProgressPhotoDeletedEvent:
        self.events[event_id] = replace(
            self.events[event_id],
            status=MediaEventStatus.DEAD_LETTER,
            last_error=error,
            completed_at=at,
        )
        return self.events[event_id]

    def get(self, *, event_id: UUID) -> ProgressPhotoDeletedEvent | None:
        return self.events.get(event_id)

    def counts_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.events.values():
            counts[event.status.value] = counts.get(event.status.value, 0) + 1
        return counts


class FakeCleanupRepository:
    """In-memory outbox with the same claim/lease semantics as the Django one."""

    def __init__(self, event_outbox: FakeMediaEventOutboxRepository) -> None:
        self.jobs: dict[UUID, MediaCleanupJob] = {}
        self._event_outbox = event_outbox

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
            verify_after=verify_after,
        )
        self.jobs[job.id] = job
        return job

    def defer_verification(self, *, job_id: UUID, next_attempt_at: datetime) -> MediaCleanupJob:
        self.jobs[job_id] = replace(self.jobs[job_id], next_attempt_at=next_attempt_at)
        return self.jobs[job_id]

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

    def mark_done_and_enqueue_deleted_event(
        self, *, job_id: UUID, photo_id: UUID, owner_id: UUID, at: datetime
    ) -> None:
        self.mark_done(job_id=job_id, at=at)
        self._event_outbox.enqueue(owner_id=owner_id, photo_id=photo_id, now=at)

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

    def confirm_if_pending(
        self, *, photo_id: UUID, owner_id: UUID, confirmed_at: datetime
    ) -> ProgressPhoto | None:
        p = self.photos.get(photo_id)
        if p is None or p.owner_id != owner_id or p.status != ProgressPhotoStatus.PENDING_UPLOAD:
            return None
        updated = p.confirm(confirmed_at=confirmed_at)
        self.photos[photo_id] = updated
        return updated

    def refresh_upload_authorization_if_pending(
        self, *, photo_id: UUID, owner_id: UUID, authorized_until: datetime
    ) -> ProgressPhoto | None:
        p = self.photos.get(photo_id)
        if p is None or p.owner_id != owner_id or p.status != ProgressPhotoStatus.PENDING_UPLOAD:
            return None
        updated = p.with_upload_authorization(authorized_until)
        self.photos[photo_id] = updated
        return updated

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
            verify_after=p.upload_authorized_until,
        )
        return updated, job

    def count_pending_uploads(self, *, owner_id: UUID) -> int:
        return sum(
            1
            for p in self.photos.values()
            if p.owner_id == owner_id and p.status == ProgressPhotoStatus.PENDING_UPLOAD
        )

    def find_abandoned_pending_upload_ids(
        self, *, older_than: datetime, limit: int
    ) -> list[tuple[UUID, UUID]]:
        abandoned = [
            (p.id, p.owner_id)
            for p in self.photos.values()
            if p.status == ProgressPhotoStatus.PENDING_UPLOAD
            and p.upload_authorized_until is not None
            and p.upload_authorized_until < older_than
        ]
        return abandoned[:limit]


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
        self.event_outbox_repo = FakeMediaEventOutboxRepository()
        self.cleanup_repo = FakeCleanupRepository(event_outbox=self.event_outbox_repo)
        self.repo = FakeProgressPhotoRepository(self.cleanup_repo)
        self.storage = InMemoryMediaStorageAdapter()
        self.publisher = FakeEventPublisher()
        self.cleanup = MediaCleanupService(
            repository=self.cleanup_repo,
            storage=self.storage,
            max_attempts=3,
            lease_seconds=300,
            base_backoff_seconds=30,
            # The post-authorization PUT-completion grace is tested on its
            # own (see the dedicated grace-period tests); zero here keeps
            # every other test's verify_after timing exact.
            put_completion_grace_seconds=0,
            clock=lambda: self.now,
        )
        self.event_outbox = MediaEventOutboxService(
            repository=self.event_outbox_repo,
            publisher=self.publisher,
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

    def deliver_events(self) -> OutboxRunSummary:
        """Runs the separate outbox-delivery pass -- a cleanup job's
        completion only durably records the event; this is what actually
        calls the publisher."""
        return self.event_outbox.process_due()

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

    def close_upload_authorization(self, photo_id: UUID) -> None:
        """Test-only: simulate the presigned URL's authorization window having
        already elapsed, for a delete test unrelated to that window (see the
        deferred-verification tests, which test it directly)."""
        photo = self.repo.photos[photo_id]
        self.repo.photos[photo_id] = replace(photo, upload_authorized_until=self.now)


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


def test_request_upload_rejects_a_new_upload_once_the_owner_is_at_the_pending_cap() -> None:
    """Fifth Codex adversarial-review pass: interrupted clients (or an
    abusive account) must not be able to accumulate unbounded PENDING_UPLOAD
    rows and private S3 objects."""
    h = Harness()
    for i in range(MAX_PENDING_UPLOADS_PER_OWNER):
        h.request_upload(key=f"quota-{i}")
    assert len(h.repo.photos) == MAX_PENDING_UPLOADS_PER_OWNER

    with pytest.raises(TooManyPendingUploadsError):
        h.request_upload(key="quota-over")

    # The rejected row is cleanly rolled back (tombstoned), not left dangling
    # counting against the cap forever, and no other owner is affected.
    assert h.repo.count_pending_uploads(owner_id=h.owner_id) == MAX_PENDING_UPLOADS_PER_OWNER
    other_owner = uuid4()
    other_repo_count = h.repo.count_pending_uploads(owner_id=other_owner)
    assert other_repo_count == 0


def test_request_upload_replay_of_an_existing_key_is_never_blocked_by_the_quota() -> None:
    """The cap only stops a *new* upload from being created; retrying an
    already-accepted key (e.g. after a network hiccup) must still succeed
    even once the owner is at (or over) the cap."""
    h = Harness()
    for i in range(MAX_PENDING_UPLOADS_PER_OWNER):
        h.request_upload(key=f"quota-replay-{i}")

    first = h.request_upload(key="quota-replay-0")
    second = h.request_upload(key="quota-replay-0")

    assert first == second


def test_reconcile_abandoned_uploads_tombstones_only_expired_pending_uploads() -> None:
    h = Harness()
    fresh_id = h.request_upload(key="fresh")
    abandoned_id = h.request_upload(key="abandoned")
    confirmed_id = h.confirmed_photo("confirmed")
    reconcile = ReconcileAbandonedUploadsUseCase(repository=h.repo, cleanup=h.cleanup)

    abandoned_deadline = h.repo.photos[abandoned_id].upload_authorized_until
    assert abandoned_deadline is not None
    # RequestProgressPhotoUploadUseCase stamps authorized_until from the real
    # wall clock, not h.now -- push "fresh"'s deadline safely ahead of the
    # cutoff this test will use, so only "abandoned" is ever in scope.
    h.repo.photos[fresh_id] = replace(
        h.repo.photos[fresh_id], upload_authorized_until=abandoned_deadline + timedelta(hours=1)
    )

    # Not due yet: the fresh upload's authorization window is still open.
    assert reconcile.execute().reconciled == 0
    assert h.repo.photos[fresh_id].status == ProgressPhotoStatus.PENDING_UPLOAD

    # Past the authorization window (Harness's cleanup uses zero grace; see
    # the dedicated grace-period tests for that margin): reconciled.
    h.now = abandoned_deadline + timedelta(seconds=1)
    result = reconcile.execute()

    assert result.reconciled == 1
    assert h.repo.photos[abandoned_id].status == ProgressPhotoStatus.DELETED
    assert h.repo.photos[fresh_id].status == ProgressPhotoStatus.PENDING_UPLOAD
    assert h.repo.photos[confirmed_id].status == ProgressPhotoStatus.CONFIRMED

    # Already reconciled: idempotent, does not re-report it.
    assert reconcile.execute().reconciled == 0


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
    h.close_upload_authorization(photo1)
    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo1)

    assert result.storage_cleanup == MediaCleanupStatus.DONE
    assert not h.storage.has_object(s3_key=s3_key)
    h.deliver_events()
    assert h.publisher.deleted_events == [(photo1, h.owner_id)]

    photos_after = list_use_case.execute(owner_id=h.owner_id)
    assert [p.id for p in photos_after] == [photo2_id]

    with pytest.raises(PhotoNotFoundError):
        h.delete.execute(owner_id=h.owner_id, photo_id=photo1)


def test_delete_is_durable_when_storage_is_down_and_event_waits_for_removal() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()
    s3_key = h.repo.photos[photo_id].s3_key
    h.close_upload_authorization(photo_id)
    h.storage.delete_failures_remaining = 1

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)

    # Tombstoned and hidden, but the caller is told removal is still pending.
    assert result.storage_cleanup == MediaCleanupStatus.PENDING
    assert h.repo.photos[photo_id].status == ProgressPhotoStatus.DELETED
    assert h.storage.has_object(s3_key=s3_key)
    # The job hasn't completed yet, so no event was even enqueued.
    assert h.deliver_events().claimed == 0

    # Not yet due: the worker leaves it alone (backoff).
    assert h.cleanup.process_due().claimed == 0

    h.now += timedelta(seconds=31)
    summary = h.cleanup.process_due()

    assert (summary.claimed, summary.completed) == (1, 1)
    assert not h.storage.has_object(s3_key=s3_key)
    assert h.deliver_events().completed == 1
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
    # A job that never completes never enqueues its event.
    assert h.deliver_events().claimed == 0
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


def test_cleanup_completion_does_not_depend_on_the_publisher() -> None:
    """Fifth Codex adversarial-review pass: cleanup completion and durably
    recording the event happen atomically in the repository; the publisher
    is only ever called later, by the separate MediaEventOutboxService, so
    a publisher failure can never affect (or even be reached during)
    `storage_cleanup` reporting DONE."""
    h = Harness()
    photo_id = h.confirmed_photo()

    def _boom(**_: object) -> None:
        raise RuntimeError("bus down")

    h.publisher.publish_photo_deleted = _boom  # type: ignore[method-assign]
    h.close_upload_authorization(photo_id)

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)

    assert result.storage_cleanup == MediaCleanupStatus.DONE
    # The event was durably enqueued despite the cleanup pass never touching
    # the (failing) publisher at all.
    (event,) = h.event_outbox_repo.events.values()
    assert event.status == MediaEventStatus.PENDING
    assert h.publisher.deleted_events == []


def test_event_outbox_retries_a_failing_publisher_without_losing_the_event() -> None:
    """Fifth Codex adversarial-review pass: a transient publish failure must
    be retried with backoff, never silently dropped."""
    h = Harness()
    photo_id = h.confirmed_photo()
    h.close_upload_authorization(photo_id)
    h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)
    (event_id,) = h.event_outbox_repo.events

    attempts = 0

    def _fails_once(**kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("bus unreachable")
        h.publisher.deleted_events.append((kwargs["photo_id"], kwargs["owner_id"]))  # type: ignore[arg-type]

    h.publisher.publish_photo_deleted = _fails_once  # type: ignore[method-assign]

    first = h.event_outbox.attempt(event_id)
    assert first == MediaEventStatus.PENDING
    assert h.event_outbox_repo.events[event_id].next_attempt_at == h.now + timedelta(seconds=30)
    assert h.publisher.deleted_events == []

    h.now += timedelta(seconds=31)
    second = h.event_outbox.attempt(event_id)

    assert second == MediaEventStatus.DONE
    assert h.publisher.deleted_events == [(photo_id, h.owner_id)]
    assert h.event_outbox_repo.events[event_id].status == MediaEventStatus.DONE


def test_event_outbox_dead_letters_an_event_after_max_attempts() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()
    h.close_upload_authorization(photo_id)
    h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)
    (event_id,) = h.event_outbox_repo.events

    def _always_fails(**_: object) -> None:
        raise RuntimeError("bus permanently down")

    h.publisher.publish_photo_deleted = _always_fails  # type: ignore[method-assign]

    assert h.event_outbox.attempt(event_id) == MediaEventStatus.PENDING
    h.now += timedelta(seconds=31)
    assert h.event_outbox.attempt(event_id) == MediaEventStatus.PENDING
    h.now += timedelta(seconds=61)
    status = h.event_outbox.attempt(event_id)

    assert status == MediaEventStatus.DEAD_LETTER
    event = h.event_outbox_repo.events[event_id]
    assert event.attempts == 3
    assert event.last_error and "bus permanently down" in event.last_error
    assert h.event_outbox_repo.counts_by_status() == {"DEAD_LETTER": 1}
    assert h.publisher.deleted_events == []


def test_delete_of_another_owners_photo_is_not_found() -> None:
    h = Harness()
    photo_id = h.confirmed_photo()

    with pytest.raises(PhotoNotFoundError):
        h.delete.execute(owner_id=uuid4(), photo_id=photo_id)
    assert h.cleanup_repo.jobs == {}


def test_delete_defers_completion_until_the_upload_authorization_window_elapses() -> None:
    """A presigned PUT issued before delete stays authorized to recreate the
    object at `s3_key` until it expires -- cleanup must not report itself
    done, or publish the deleted event, while that window is still open."""
    h = Harness()
    photo_id = h.confirmed_photo()
    s3_key = h.repo.photos[photo_id].s3_key
    authorized_until = h.repo.photos[photo_id].upload_authorized_until
    assert authorized_until is not None and authorized_until > h.now

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)

    # Removed immediately, but not yet reported final.
    assert result.storage_cleanup == MediaCleanupStatus.PENDING
    assert not h.storage.has_object(s3_key=s3_key)
    # The job hasn't completed yet, so no event was even enqueued.
    assert h.deliver_events().claimed == 0
    (job,) = h.cleanup_repo.jobs.values()
    assert job.next_attempt_at == authorized_until

    # Not due before the window elapses: the worker leaves it alone.
    h.now = authorized_until - timedelta(seconds=1)
    assert h.cleanup.process_due().claimed == 0

    # Due once the window elapses: the final verification pass completes it.
    h.now = authorized_until + timedelta(seconds=1)
    summary = h.cleanup.process_due()

    assert (summary.claimed, summary.completed) == (1, 1)
    assert h.cleanup_repo.jobs[job.id].status == MediaCleanupStatus.DONE
    assert h.deliver_events().completed == 1
    assert h.publisher.deleted_events == [(photo_id, h.owner_id)]


def test_delete_removes_an_object_recreated_via_a_stale_upload_url_before_reporting_done() -> None:
    """A client holding the still-valid presigned URL PUTs again after the
    delete's first pass -- the deferred verification must remove it too."""
    h = Harness()
    photo_id = h.confirmed_photo()
    s3_key = h.repo.photos[photo_id].s3_key
    authorized_until = h.repo.photos[photo_id].upload_authorized_until
    assert authorized_until is not None

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)
    assert result.storage_cleanup == MediaCleanupStatus.PENDING

    # A stale PUT (still within the presigned URL's window) recreates the
    # object at the same key -- a deleted private photo must not survive this.
    h.storage.put_object_data(s3_key=s3_key)
    assert h.storage.has_object(s3_key=s3_key)

    h.now = authorized_until + timedelta(seconds=1)
    summary = h.cleanup.process_due()

    assert summary.completed == 1
    assert not h.storage.has_object(s3_key=s3_key)


def _harness_with_grace(grace_seconds: int) -> Harness:
    h = Harness()
    h.cleanup = MediaCleanupService(
        repository=h.cleanup_repo,
        storage=h.storage,
        max_attempts=3,
        lease_seconds=300,
        base_backoff_seconds=30,
        put_completion_grace_seconds=grace_seconds,
        clock=lambda: h.now,
    )
    h.delete = DeleteProgressPhotoUseCase(repository=h.repo, cleanup=h.cleanup)
    return h


def test_delete_cleanup_waits_a_grace_period_past_authorization_before_reporting_done() -> None:
    """A presigned PUT started just before the authorization deadline can
    still be mid-transfer after it (S3 validates the signature at request
    start, not completion) -- a single re-check exactly at the deadline is
    not enough; cleanup must wait a further bounded grace period."""
    h = _harness_with_grace(60)
    photo_id = h.confirmed_photo()
    authorized_until = h.repo.photos[photo_id].upload_authorized_until
    assert authorized_until is not None

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)
    assert result.storage_cleanup == MediaCleanupStatus.PENDING

    # Right at the deadline: too early, a late PUT could still land.
    h.now = authorized_until + timedelta(seconds=1)
    assert h.cleanup.process_due().claimed == 0

    # Past the deadline plus the grace period: safe to finalize.
    h.now = authorized_until + timedelta(seconds=61)
    summary = h.cleanup.process_due()

    assert (summary.claimed, summary.completed) == (1, 1)
    assert h.deliver_events().completed == 1
    assert h.publisher.deleted_events == [(photo_id, h.owner_id)]


def test_delete_cleanup_removes_an_object_put_during_the_grace_period() -> None:
    """A PUT that lands strictly after the authorization deadline but
    within the completion grace period must still be caught, not just one
    that lands before the deadline (see the stale-upload-url test above)."""
    h = _harness_with_grace(60)
    photo_id = h.confirmed_photo()
    s3_key = h.repo.photos[photo_id].s3_key
    authorized_until = h.repo.photos[photo_id].upload_authorized_until
    assert authorized_until is not None

    result = h.delete.execute(owner_id=h.owner_id, photo_id=photo_id)
    assert result.storage_cleanup == MediaCleanupStatus.PENDING
    assert not h.storage.has_object(s3_key=s3_key)

    # A PUT that started just before the deadline lands during the grace window.
    h.now = authorized_until + timedelta(seconds=30)
    h.storage.put_object_data(s3_key=s3_key)
    assert h.storage.has_object(s3_key=s3_key)

    h.now = authorized_until + timedelta(seconds=61)
    summary = h.cleanup.process_due()

    assert summary.completed == 1
    assert not h.storage.has_object(s3_key=s3_key)
