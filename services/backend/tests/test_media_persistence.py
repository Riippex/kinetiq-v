"""Database-backed behavior of the media outbox and upload idempotency.

These run on the default SQLite suite. They prove atomicity, claim semantics
and the idempotency race *path* deterministically; genuinely parallel
connections are covered by tests/postgres/test_media_concurrency.py.
"""

from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from kinetiq.bootstrap.container import (
    delete_progress_photo,
    finalize_progress_photo,
    get_media_storage,
    list_progress_photos,
    process_media_cleanup,
    reconcile_abandoned_uploads,
    request_progress_photo_upload,
)
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.media.application import MediaEventOutboxService, upload_request_fingerprint
from kinetiq.modules.media.domain import (
    MAX_PENDING_UPLOADS_PER_OWNER,
    IdempotencyConflictError,
    InvalidPhotoStateError,
    MediaCleanupReason,
    MediaCleanupStatus,
    MediaEventStatus,
    PhotoNotFoundError,
    ProgressPhoto,
    ProgressPhotoStatus,
    TooManyPendingUploadsError,
)
from kinetiq.modules.media.infrastructure import repositories
from kinetiq.modules.media.infrastructure.models import (
    MediaCleanupJobRecord,
    MediaEventOutboxRecord,
    MediaUploadReceiptRecord,
    ProgressPhotoRecord,
)
from kinetiq.modules.media.infrastructure.repositories import (
    DjangoMediaCleanupRepository,
    DjangoMediaEventOutboxRepository,
    DjangoProgressPhotoRepository,
)
from kinetiq.modules.media.infrastructure.storage import (
    InMemoryMediaStorageAdapter,
    S3MediaStorageAdapter,
)

DELETE_PHOTO_MUTATION = """
mutation DeletePhoto($photoId: ID!) {
  deleteProgressPhoto(photoId: $photoId) { success storageCleanup errors { code } }
}
"""
FINALIZE_PHOTO_MUTATION = """
mutation FinalizePhoto($photoId: ID!) {
  finalizeProgressPhoto(photoId: $photoId) { photo { id status } errors { code } }
}
"""
REQUEST_UPLOAD_MUTATION = """
mutation RequestUpload($contentType: String!, $byteLength: Int!, $idempotencyKey: String!) {
  requestProgressPhotoUpload(
    contentType: $contentType, byteLength: $byteLength, idempotencyKey: $idempotencyKey
  ) { uploadRequest { photoId uploadUrl } errors { code field } }
}
"""


def _storage() -> InMemoryMediaStorageAdapter:
    storage = get_media_storage()
    assert isinstance(storage, InMemoryMediaStorageAdapter)
    storage.delete_failures_remaining = 0
    return storage


def _photo(
    owner: User, *, status: ProgressPhotoStatus = ProgressPhotoStatus.PENDING_UPLOAD
) -> ProgressPhoto:
    photo_id = uuid4()
    return ProgressPhoto(
        id=photo_id,
        owner_id=owner.id,
        session_id=None,
        s3_key=f"photos/{owner.id}/{photo_id}.jpg",
        content_type="image/jpeg",
        byte_length=1024,
        status=status,
        created_at=datetime.now(UTC),
    )


def _fingerprint(**overrides: object) -> str:
    fields: dict[str, object] = {
        "session_id": None,
        "content_type": "image/jpeg",
        "byte_length": 1024,
    }
    fields.update(overrides)
    return upload_request_fingerprint(**fields)  # type: ignore[arg-type]


@pytest.mark.django_db
def test_idempotent_replay_returns_the_original_photo_without_a_second_row() -> None:
    owner = User.objects.create_user(username="idem-replay")
    repo = DjangoProgressPhotoRepository()

    first, created_first = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )
    second, created_second = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )

    assert (created_first, created_second) == (True, False)
    assert first.id == second.id
    assert ProgressPhotoRecord.objects.filter(owner=owner).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "changed",
    [{"content_type": "image/png"}, {"byte_length": 2048}, {"session_id": uuid4()}],
    ids=["content_type", "byte_length", "session_id"],
)
def test_reusing_a_key_with_any_changed_field_conflicts(changed: dict[str, object]) -> None:
    owner = User.objects.create_user(username="idem-conflict")
    repo = DjangoProgressPhotoRepository()
    repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )

    with pytest.raises(IdempotencyConflictError):
        repo.save_upload_request_idempotently(
            photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint(**changed)
        )

    assert ProgressPhotoRecord.objects.filter(owner=owner).count() == 1


@pytest.mark.django_db
def test_a_receipt_without_a_fingerprint_is_never_a_valid_replay() -> None:
    owner = User.objects.create_user(username="idem-legacy")
    photo = _photo(owner)
    record = ProgressPhotoRecord.objects.create(
        id=photo.id,
        owner=owner,
        s3_key=photo.s3_key,
        content_type=photo.content_type,
        byte_length=photo.byte_length,
        status=photo.status.value,
    )
    MediaUploadReceiptRecord.objects.create(
        owner=owner, idempotency_key="legacy", request_fingerprint="", photo=record
    )

    with pytest.raises(IdempotencyConflictError):
        DjangoProgressPhotoRepository().save_upload_request_idempotently(
            photo=_photo(owner), idempotency_key="legacy", request_fingerprint=_fingerprint()
        )


@pytest.mark.django_db
def test_a_missing_fingerprint_is_rejected_instead_of_skipping_the_comparison() -> None:
    owner = User.objects.create_user(username="idem-empty")

    with pytest.raises(ValueError, match="request_fingerprint"):
        DjangoProgressPhotoRepository().save_upload_request_idempotently(
            photo=_photo(owner), idempotency_key="k", request_fingerprint=""
        )


@pytest.mark.django_db(transaction=True)
def test_losing_the_unique_constraint_race_replays_the_winner(monkeypatch) -> None:
    """Force the race path: the loser's initial lookup misses, its INSERT collides."""
    owner = User.objects.create_user(username="idem-race-path")
    repo = DjangoProgressPhotoRepository()
    winner, _ = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )

    real_find = DjangoProgressPhotoRepository._find_receipt
    lookups: list[object] = []

    def blind_first_lookup(owner_id, idempotency_key):  # type: ignore[no-untyped-def]
        lookups.append(1)
        return None if len(lookups) == 1 else real_find(owner_id, idempotency_key)

    monkeypatch.setattr(
        DjangoProgressPhotoRepository, "_find_receipt", staticmethod(blind_first_lookup)
    )

    replayed, created = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )

    assert created is False
    assert replayed.id == winner.id
    assert len(lookups) == 2, "the IntegrityError path must re-read the winner's receipt"
    assert ProgressPhotoRecord.objects.filter(owner=owner).count() == 1

    # ...and the same race with a conflicting request is a conflict, not a replay.
    lookups.clear()
    with pytest.raises(IdempotencyConflictError):
        repo.save_upload_request_idempotently(
            photo=_photo(owner),
            idempotency_key="k",
            request_fingerprint=_fingerprint(byte_length=1),
        )
    assert ProgressPhotoRecord.objects.filter(owner=owner).count() == 1


@pytest.mark.django_db
def test_upload_replay_after_confirmation_or_deletion_is_refused() -> None:
    owner = User.objects.create_user(username="idem-state")
    storage = _storage()
    use_case = request_progress_photo_upload()

    def request(key: str):  # type: ignore[no-untyped-def]
        return use_case.execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key=key,
        )

    confirmed = request("confirmed")
    storage.put_object_data(
        s3_key=ProgressPhotoRecord.objects.get(id=confirmed.photo_id).s3_key,
        data=b"x" * 8,
        content_type="image/jpeg",
    )
    finalize_progress_photo().execute(owner_id=owner.id, photo_id=confirmed.photo_id)
    with pytest.raises(InvalidPhotoStateError):
        request("confirmed")

    deleted = request("deleted")
    delete_progress_photo().execute(owner_id=owner.id, photo_id=deleted.photo_id)
    with pytest.raises(InvalidPhotoStateError):
        request("deleted")


@pytest.mark.django_db
def test_confirm_if_pending_never_resurrects_a_deleted_photo() -> None:
    """Second Codex adversarial-review pass: a stale finalize write must
    never undo a concurrent delete."""
    owner = User.objects.create_user(username="confirm-guard-deleted")
    repo = DjangoProgressPhotoRepository()
    photo, _ = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )
    assert repo.tombstone_and_enqueue_cleanup(
        photo_id=photo.id, owner_id=owner.id, deleted_at=datetime.now(UTC)
    )

    result = repo.confirm_if_pending(
        photo_id=photo.id, owner_id=owner.id, confirmed_at=datetime.now(UTC), final_s3_key="final/k"
    )

    assert result is None
    record = ProgressPhotoRecord.objects.get(id=photo.id)
    assert record.status == "DELETED"
    assert record.confirmed_at is None
    assert record.final_s3_key is None


@pytest.mark.django_db
def test_confirm_if_pending_does_not_overwrite_an_already_confirmed_photo() -> None:
    owner = User.objects.create_user(username="confirm-guard-confirmed")
    repo = DjangoProgressPhotoRepository()
    photo, _ = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )
    first_confirmed_at = datetime.now(UTC)
    assert repo.confirm_if_pending(
        photo_id=photo.id,
        owner_id=owner.id,
        confirmed_at=first_confirmed_at,
        final_s3_key="final/first",
    )

    second = repo.confirm_if_pending(
        photo_id=photo.id,
        owner_id=owner.id,
        confirmed_at=datetime.now(UTC) + timedelta(hours=1),
        final_s3_key="final/second",
    )

    assert second is None
    record = ProgressPhotoRecord.objects.get(id=photo.id)
    assert record.confirmed_at == first_confirmed_at
    assert record.final_s3_key == "final/first"


@pytest.mark.django_db
def test_refresh_upload_authorization_if_pending_never_resurrects_a_deleted_photo() -> None:
    """Second Codex adversarial-review pass: a stale upload-request replay
    must never mint/extend authorization for a concurrently deleted photo."""
    owner = User.objects.create_user(username="refresh-guard-deleted")
    repo = DjangoProgressPhotoRepository()
    photo, _ = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )
    assert repo.tombstone_and_enqueue_cleanup(
        photo_id=photo.id, owner_id=owner.id, deleted_at=datetime.now(UTC)
    )
    new_deadline = datetime.now(UTC) + timedelta(hours=1)

    result = repo.refresh_upload_authorization_if_pending(
        photo_id=photo.id, owner_id=owner.id, authorized_until=new_deadline
    )

    assert result is None
    record = ProgressPhotoRecord.objects.get(id=photo.id)
    assert record.status == "DELETED"
    assert record.upload_authorized_until != new_deadline


@pytest.mark.django_db
def test_refresh_upload_authorization_if_pending_does_not_extend_a_confirmed_photo() -> None:
    owner = User.objects.create_user(username="refresh-guard-confirmed")
    repo = DjangoProgressPhotoRepository()
    photo, _ = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )
    assert repo.confirm_if_pending(
        photo_id=photo.id, owner_id=owner.id, confirmed_at=datetime.now(UTC), final_s3_key="final/k"
    )

    result = repo.refresh_upload_authorization_if_pending(
        photo_id=photo.id,
        owner_id=owner.id,
        authorized_until=datetime.now(UTC) + timedelta(hours=1),
    )

    assert result is None


@pytest.mark.django_db
def test_tombstone_and_cleanup_job_are_created_together() -> None:
    owner = User.objects.create_user(username="outbox-atomic")
    repo = DjangoProgressPhotoRepository()
    photo, _ = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )

    result = repo.tombstone_and_enqueue_cleanup(
        photo_id=photo.id, owner_id=owner.id, deleted_at=datetime.now(UTC)
    )

    assert result is not None
    tombstoned, job = result
    assert tombstoned.status == ProgressPhotoStatus.DELETED
    assert job.status == MediaCleanupStatus.PENDING
    assert job.reason == MediaCleanupReason.PHOTO_DELETED
    assert job.s3_key == photo.s3_key
    assert MediaCleanupJobRecord.objects.filter(photo_id=photo.id).count() == 1

    # A second delete neither re-tombstones nor enqueues another job.
    assert (
        repo.tombstone_and_enqueue_cleanup(
            photo_id=photo.id, owner_id=owner.id, deleted_at=datetime.now(UTC)
        )
        is None
    )
    assert MediaCleanupJobRecord.objects.filter(photo_id=photo.id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_a_failure_enqueuing_the_job_rolls_the_tombstone_back(monkeypatch) -> None:
    owner = User.objects.create_user(username="outbox-rollback")
    repo = DjangoProgressPhotoRepository()
    photo, _ = repo.save_upload_request_idempotently(
        photo=_photo(owner), idempotency_key="k", request_fingerprint=_fingerprint()
    )

    def boom(**_: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(repositories, "_enqueue_cleanup_job", boom)

    with pytest.raises(RuntimeError):
        repo.tombstone_and_enqueue_cleanup(
            photo_id=photo.id, owner_id=owner.id, deleted_at=datetime.now(UTC)
        )

    # No orphaned tombstone: the photo is still live and no job exists.
    assert ProgressPhotoRecord.objects.get(id=photo.id).status == "PENDING_UPLOAD"
    assert MediaCleanupJobRecord.objects.count() == 0


@pytest.mark.django_db
def test_enqueue_is_idempotent_per_object_and_reason() -> None:
    owner = User.objects.create_user(username="outbox-enqueue")
    cleanup = DjangoMediaCleanupRepository()
    now = datetime.now(UTC)
    photo_id = uuid4()

    first = cleanup.enqueue(
        owner_id=owner.id,
        photo_id=photo_id,
        s3_key="k",
        reason=MediaCleanupReason.UPLOAD_REJECTED,
        now=now,
    )
    second = cleanup.enqueue(
        owner_id=owner.id,
        photo_id=photo_id,
        s3_key="k",
        reason=MediaCleanupReason.UPLOAD_REJECTED,
        now=now,
    )
    other_reason = cleanup.enqueue(
        owner_id=owner.id,
        photo_id=photo_id,
        s3_key="k",
        reason=MediaCleanupReason.PHOTO_DELETED,
        now=now,
    )

    assert first.id == second.id
    assert other_reason.id != first.id


@pytest.mark.django_db
def test_claim_leases_a_due_job_exactly_once_and_respects_backoff() -> None:
    owner = User.objects.create_user(username="outbox-claim")
    cleanup = DjangoMediaCleanupRepository()
    now = datetime.now(UTC)
    job = cleanup.enqueue(
        owner_id=owner.id,
        photo_id=uuid4(),
        s3_key="k",
        reason=MediaCleanupReason.PHOTO_DELETED,
        now=now,
    )

    first = cleanup.claim(job_id=job.id, now=now, lease_seconds=300)
    second = cleanup.claim(job_id=job.id, now=now, lease_seconds=300)

    assert first is not None and first.attempts == 1
    assert second is None, "a leased job must not be claimable again"
    assert cleanup.due_job_ids(now=now, limit=10) == []
    assert cleanup.due_job_ids(now=now + timedelta(seconds=301), limit=10) == [job.id]

    # A crashed worker's lease expires and the job is retried.
    reclaimed = cleanup.claim(job_id=job.id, now=now + timedelta(seconds=301), lease_seconds=300)
    assert reclaimed is not None and reclaimed.attempts == 2


@pytest.mark.django_db
def test_worker_retries_after_outage_and_completes_with_the_real_repository() -> None:
    owner = User.objects.create_user(username="outbox-worker")
    storage = _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="k",
        )
        .photo_id
    )
    s3_key = ProgressPhotoRecord.objects.get(id=photo_id).s3_key
    storage.put_object_data(s3_key=s3_key, data=b"x" * 8)
    storage.delete_failures_remaining = 1
    # Not testing the upload-authorization window or its post-expiry grace
    # here (see test_delete_defers_completion_until_... and the grace-period
    # tests for that): close it well past the default grace so a successful
    # retry can complete right away.
    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )

    result = delete_progress_photo().execute(owner_id=owner.id, photo_id=photo_id)

    assert result.storage_cleanup == MediaCleanupStatus.PENDING
    assert storage.has_object(s3_key=s3_key)
    job = MediaCleanupJobRecord.objects.get(photo_id=photo_id)
    assert job.status == "PENDING" and job.attempts == 1 and "simulated" in (job.last_error or "")

    # Force the job due (skip the real backoff wait) and run the worker.
    MediaCleanupJobRecord.objects.filter(id=job.id).update(next_attempt_at=datetime.now(UTC))
    summary = process_media_cleanup().process_due()

    assert summary.completed == 1
    assert not storage.has_object(s3_key=s3_key)
    job.refresh_from_db()
    assert job.status == "DONE" and job.completed_at is not None


@pytest.mark.django_db
def test_request_upload_is_rejected_once_the_owner_is_at_the_pending_cap() -> None:
    """Fifth Codex adversarial-review pass: bounds unfinalized-upload
    accumulation against the real repository."""
    owner = User.objects.create_user(username="quota-owner")
    _storage()
    use_case = request_progress_photo_upload()
    for i in range(MAX_PENDING_UPLOADS_PER_OWNER):
        use_case.execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key=f"quota-{i}",
        )
    assert ProgressPhotoRecord.objects.filter(owner=owner, status="PENDING_UPLOAD").count() == (
        MAX_PENDING_UPLOADS_PER_OWNER
    )

    with pytest.raises(TooManyPendingUploadsError):
        use_case.execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="quota-over",
        )

    # Cleanly rolled back: still exactly the cap, not cap+1.
    assert ProgressPhotoRecord.objects.filter(owner=owner, status="PENDING_UPLOAD").count() == (
        MAX_PENDING_UPLOADS_PER_OWNER
    )
    assert ProgressPhotoRecord.objects.filter(owner=owner, status="DELETED").count() == 1


@pytest.mark.django_db
def test_reconcile_abandoned_uploads_tombstones_expired_pending_uploads() -> None:
    owner = User.objects.create_user(username="reconcile-owner")
    _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="abandoned",
        )
        .photo_id
    )

    # Not due yet: the authorization window is still open.
    assert reconcile_abandoned_uploads().execute().reconciled == 0
    assert ProgressPhotoRecord.objects.get(id=photo_id).status == "PENDING_UPLOAD"

    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )

    result = reconcile_abandoned_uploads().execute()

    assert result.reconciled == 1
    record = ProgressPhotoRecord.objects.get(id=photo_id)
    assert record.status == "DELETED"
    assert MediaCleanupJobRecord.objects.filter(photo_id=photo_id).count() == 1
    # Idempotent: nothing left to reconcile.
    assert reconcile_abandoned_uploads().execute().reconciled == 0


@pytest.mark.django_db
def test_management_command_reconciles_abandoned_uploads() -> None:
    owner = User.objects.create_user(username="command-reconcile-owner")
    storage = _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="abandoned-cmd",
        )
        .photo_id
    )
    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )

    out = StringIO()
    call_command("process_media_cleanup", stdout=out)

    assert "reconciled=1" in out.getvalue()
    assert ProgressPhotoRecord.objects.get(id=photo_id).status == "DELETED"
    assert not storage.has_object(s3_key=ProgressPhotoRecord.objects.get(id=photo_id).s3_key)


@pytest.mark.django_db
def test_photo_deletion_atomically_enqueues_its_event_with_job_completion() -> None:
    """Fifth Codex adversarial-review pass: the durable outbox event for
    ProgressPhotoDeleted.v1 is recorded in the SAME transaction as the
    cleanup job's completion (DjangoMediaCleanupRepository.
    mark_done_and_enqueue_deleted_event), not as a fire-and-forget publish
    attempted afterward -- so a crash between the two can never lose it."""
    owner = User.objects.create_user(username="outbox-atomicity")
    storage = _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="k",
        )
        .photo_id
    )
    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )

    assert MediaEventOutboxRecord.objects.count() == 0
    result = delete_progress_photo().execute(owner_id=owner.id, photo_id=photo_id)

    assert result.storage_cleanup == MediaCleanupStatus.DONE
    assert not storage.has_object(s3_key=ProgressPhotoRecord.objects.get(id=photo_id).s3_key)
    event = MediaEventOutboxRecord.objects.get(photo_id=photo_id)
    assert event.owner_id == owner.id
    assert event.status == "PENDING"
    assert event.event_type == "ProgressPhotoDeleted.v1"


@pytest.mark.django_db
def test_event_outbox_retries_a_failing_publisher_without_losing_the_event() -> None:
    owner = User.objects.create_user(username="outbox-retry")
    _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="k",
        )
        .photo_id
    )
    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )
    delete_progress_photo().execute(owner_id=owner.id, photo_id=photo_id)
    (event_id,) = MediaEventOutboxRecord.objects.values_list("id", flat=True)

    class FailOnceThenSucceedPublisher:
        def __init__(self) -> None:
            self.attempts = 0
            self.delivered: list[tuple[Any, Any]] = []
            self.delivered_event_ids: list[Any] = []

        def publish_photo_deleted(
            self, *, event_id: Any, photo_id: Any, owner_id: Any, occurred_at: Any
        ) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("bus unreachable")
            self.delivered.append((photo_id, owner_id))
            self.delivered_event_ids.append(event_id)

    publisher = FailOnceThenSucceedPublisher()
    outbox = MediaEventOutboxService(
        repository=DjangoMediaEventOutboxRepository(), publisher=publisher, base_backoff_seconds=30
    )

    first = outbox.attempt(event_id)
    assert first == MediaEventStatus.PENDING
    assert publisher.delivered == []
    record = MediaEventOutboxRecord.objects.get(id=event_id)
    assert record.status == "PENDING" and "bus unreachable" in (record.last_error or "")

    MediaEventOutboxRecord.objects.filter(id=event_id).update(next_attempt_at=datetime.now(UTC))
    second = outbox.attempt(event_id)

    assert second == MediaEventStatus.DONE
    assert publisher.delivered == [(photo_id, owner.id)]
    assert MediaEventOutboxRecord.objects.get(id=event_id).status == "DONE"


@pytest.mark.django_db
def test_management_command_delivers_the_outboxed_event() -> None:
    owner = User.objects.create_user(username="outbox-command-deliver")
    _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="k",
        )
        .photo_id
    )
    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )
    delete_progress_photo().execute(owner_id=owner.id, photo_id=photo_id)
    assert MediaEventOutboxRecord.objects.get(photo_id=photo_id).status == "PENDING"

    out = StringIO()
    call_command("process_media_cleanup", stdout=out)

    assert "events_completed=1" in out.getvalue()
    assert MediaEventOutboxRecord.objects.get(photo_id=photo_id).status == "DONE"


@pytest.mark.django_db
def test_management_command_reports_and_fails_loudly_on_dead_letters() -> None:
    owner = User.objects.create_user(username="outbox-command")
    _storage()
    out = StringIO()

    call_command("process_media_cleanup", stdout=out)
    assert "claimed=0" in out.getvalue()

    MediaCleanupJobRecord.objects.create(
        owner_id=owner.id,
        photo_id=uuid4(),
        s3_key="k",
        reason="PHOTO_DELETED",
        status="DEAD_LETTER",
        attempts=8,
        next_attempt_at=datetime.now(UTC),
    )
    with pytest.raises(CommandError, match="dead-lettered"):
        call_command("process_media_cleanup", stdout=StringIO())


@pytest.mark.django_db
def test_deleting_the_owner_never_cascades_away_existing_cleanup_jobs_or_events() -> None:
    """Seventh Codex adversarial-review pass, finding #2: MediaCleanupJobRecord
    and MediaEventOutboxRecord no longer FK-cascade with the owning User (see
    the `owner_id` field comments in models.py), so a completed cleanup job
    and its outbox event survive the account being deleted -- a CASCADE here
    would silently destroy the durable pointer to the S3 object mid-cleanup
    and orphan it forever. The photo's own (PII) metadata row still legitimately
    disappears with the account."""
    owner = User.objects.create_user(username="account-delete-survives")
    storage = _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="k",
        )
        .photo_id
    )
    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )
    delete_progress_photo().execute(owner_id=owner.id, photo_id=photo_id)
    call_command("process_media_cleanup", stdout=StringIO())
    job = MediaCleanupJobRecord.objects.get(photo_id=photo_id)
    event = MediaEventOutboxRecord.objects.get(photo_id=photo_id)
    # process_media_cleanup drains both the cleanup job and its outbox event
    # in the same run, so both are already terminal here.
    assert job.status == "DONE"
    assert event.status == "DONE"
    assert not storage.has_object(s3_key=job.s3_key)

    owner_id = owner.id
    owner.delete()

    assert not User.objects.filter(id=owner_id).exists()
    assert not ProgressPhotoRecord.objects.filter(owner_id=owner_id).exists()
    assert MediaCleanupJobRecord.objects.filter(id=job.id, owner_id=owner_id).exists()
    assert MediaEventOutboxRecord.objects.filter(id=event.id, owner_id=owner_id).exists()


@pytest.mark.django_db
def test_deleting_the_owner_tombstones_and_enqueues_cleanup_for_every_live_photo() -> None:
    """Seventh Codex adversarial-review pass, finding #2: a photo that is
    still CONFIRMED (no cleanup job exists for it yet) when its owner is
    deleted must not simply vanish with the CASCADE -- its S3 object would
    become permanently unreachable, with nothing left in the database to
    ever clean it up. `signals.tombstone_media_before_account_deletion`
    (wired via MediaConfig.ready()) tombstones it and durably enqueues its
    cleanup job before the account row is actually removed, so the object
    can still be deleted by process_media_cleanup afterward."""
    owner = User.objects.create_user(username="account-delete-live-photo")
    storage = _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="k",
        )
        .photo_id
    )
    staging_key = ProgressPhotoRecord.objects.get(id=photo_id).s3_key
    storage.put_object_data(s3_key=staging_key, data=b"x" * 8, content_type="image/jpeg")
    finalize_progress_photo().execute(owner_id=owner.id, photo_id=photo_id)
    confirmed_record = ProgressPhotoRecord.objects.get(id=photo_id)
    assert confirmed_record.status == "CONFIRMED"
    # Finalize already copied the object to its immutable key and removed
    # the staging one (finding #1) -- the live object this test is about now
    # lives at final_s3_key.
    final_key = confirmed_record.final_s3_key
    assert final_key and not storage.has_object(s3_key=staging_key)
    assert MediaCleanupJobRecord.objects.count() == 0
    ProgressPhotoRecord.objects.filter(id=photo_id).update(
        upload_authorized_until=datetime.now(UTC) - timedelta(seconds=400)
    )

    owner_id = owner.id
    owner.delete()

    assert not User.objects.filter(id=owner_id).exists()
    assert not ProgressPhotoRecord.objects.filter(id=photo_id).exists()
    job = MediaCleanupJobRecord.objects.get(photo_id=photo_id)
    assert job.owner_id == owner_id
    assert job.reason == "PHOTO_DELETED"
    assert job.status == "PENDING"
    assert job.s3_key == final_key
    assert storage.has_object(s3_key=final_key)

    call_command("process_media_cleanup", stdout=StringIO())

    assert not storage.has_object(s3_key=final_key)
    assert MediaCleanupJobRecord.objects.get(id=job.id).status == "DONE"


@pytest.mark.django_db
def test_deleting_the_owner_with_no_live_photos_is_a_no_op_for_the_signal() -> None:
    """The signal must not misfire (create phantom jobs) when the owner has
    no non-DELETED photo at all."""
    owner = User.objects.create_user(username="account-delete-no-photos")
    owner.delete()
    assert MediaCleanupJobRecord.objects.count() == 0


@pytest.mark.django_db
def test_finalize_copies_to_an_immutable_key_the_staging_url_can_no_longer_overwrite() -> None:
    """Seventh Codex adversarial-review pass, finding #1: a presigned PUT
    for the staging key remains valid until its own declared expiry
    regardless of the photo's later status -- finalize must copy the
    validated object to an immutable key nothing was ever authorized to
    PUT to, so a stale re-upload to the staging key can never reach what
    listProgressPhotos/finalizeProgressPhoto actually serve."""
    owner = User.objects.create_user(username="finalize-immutable")
    storage = _storage()
    photo_id = (
        request_progress_photo_upload()
        .execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=8,
            idempotency_key="k",
        )
        .photo_id
    )
    staging_key = ProgressPhotoRecord.objects.get(id=photo_id).s3_key
    storage.put_object_data(s3_key=staging_key, data=b"x" * 8, content_type="image/jpeg")

    dto = finalize_progress_photo().execute(owner_id=owner.id, photo_id=photo_id)

    record = ProgressPhotoRecord.objects.get(id=photo_id)
    final_key = record.final_s3_key
    assert final_key and final_key != staging_key
    assert storage.has_object(s3_key=final_key)
    assert not storage.has_object(s3_key=staging_key)

    # The client still holds the (still-valid) presigned PUT URL for the
    # staging key and re-uploads different content to it.
    storage.put_object_data(s3_key=staging_key, data=b"y" * 999, content_type="image/png")

    listed = list_progress_photos().execute(owner_id=owner.id)
    assert len(listed) == 1
    assert listed[0].url == dto.url
    served = storage.get_object_info(s3_key=final_key)
    assert served is not None
    assert served.content_length == 8
    assert served.content_type == "image/jpeg"


@pytest.mark.django_db
def test_graphql_delete_reports_pending_cleanup_and_worker_finishes_it() -> None:
    owner = User.objects.create_user(username="gql-outage", password="pw")
    client = Client()
    client.force_login(owner)
    storage = _storage()

    def post(query: str, variables: dict[str, object]) -> dict:
        response = client.post(
            "/graphql/",
            data={"query": query, "variables": variables},
            content_type="application/json",
        )
        assert response.status_code == 200
        return response.json()["data"]

    photo_id = post(
        REQUEST_UPLOAD_MUTATION,
        {"contentType": "image/jpeg", "byteLength": 16, "idempotencyKey": "gql-k"},
    )["requestProgressPhotoUpload"]["uploadRequest"]["photoId"]
    s3_key = ProgressPhotoRecord.objects.get(id=photo_id).s3_key
    storage.put_object_data(s3_key=s3_key, data=b"x" * 16)
    storage.delete_failures_remaining = 1

    deleted = post(DELETE_PHOTO_MUTATION, {"photoId": photo_id})["deleteProgressPhoto"]

    assert deleted == {"success": True, "storageCleanup": "PENDING", "errors": []}
    assert storage.has_object(s3_key=s3_key)

    MediaCleanupJobRecord.objects.update(next_attempt_at=datetime.now(UTC))
    call_command("process_media_cleanup", stdout=StringIO())
    assert not storage.has_object(s3_key=s3_key)


@pytest.mark.django_db
def test_graphql_finalize_rejects_and_deletes_an_oversized_upload() -> None:
    owner = User.objects.create_user(username="gql-oversize", password="pw")
    client = Client()
    client.force_login(owner)
    storage = _storage()

    def post(query: str, variables: dict[str, object]) -> dict:
        response = client.post(
            "/graphql/",
            data={"query": query, "variables": variables},
            content_type="application/json",
        )
        return response.json()["data"]

    photo_id = post(
        REQUEST_UPLOAD_MUTATION,
        {"contentType": "image/jpeg", "byteLength": 16, "idempotencyKey": "gql-big"},
    )["requestProgressPhotoUpload"]["uploadRequest"]["photoId"]
    s3_key = ProgressPhotoRecord.objects.get(id=photo_id).s3_key
    # The client declared 16 bytes, then uploaded far more.
    storage.put_object_data(s3_key=s3_key, data=b"x" * 10_000)

    result = post(FINALIZE_PHOTO_MUTATION, {"photoId": photo_id})["finalizeProgressPhoto"]

    assert result["photo"] is None
    assert [e["code"] for e in result["errors"]] == ["UPLOAD_REJECTED"]
    assert not storage.has_object(s3_key=s3_key)
    assert ProgressPhotoRecord.objects.get(id=photo_id).status == "PENDING_UPLOAD"


@pytest.mark.django_db
def test_graphql_key_reuse_with_different_parameters_is_an_idempotency_conflict() -> None:
    owner = User.objects.create_user(username="gql-conflict", password="pw")
    client = Client()
    client.force_login(owner)

    def request(byte_length: int) -> dict:
        response = client.post(
            "/graphql/",
            data={
                "query": REQUEST_UPLOAD_MUTATION,
                "variables": {
                    "contentType": "image/jpeg",
                    "byteLength": byte_length,
                    "idempotencyKey": "gql-same-key",
                },
            },
            content_type="application/json",
        )
        return response.json()["data"]["requestProgressPhotoUpload"]

    first = request(16)
    replay = request(16)
    conflict = request(32)

    assert first["errors"] == [] and replay["errors"] == []
    assert first["uploadRequest"]["photoId"] == replay["uploadRequest"]["photoId"]
    assert conflict["uploadRequest"] is None
    assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    assert ProgressPhotoRecord.objects.filter(owner=owner).count() == 1


@pytest.mark.django_db
def test_use_case_wiring_raises_typed_errors() -> None:
    owner = User.objects.create_user(username="wiring")
    with pytest.raises(PhotoNotFoundError):
        delete_progress_photo().execute(owner_id=owner.id, photo_id=uuid4())
    with pytest.raises(PhotoNotFoundError):
        finalize_progress_photo().execute(owner_id=owner.id, photo_id=uuid4())


def test_get_media_storage_never_silently_falls_back_to_in_memory(settings: Any) -> None:
    """Without the explicit development/test flag, storage selection must
    return the real S3 adapter, never the non-durable in-memory one."""
    settings.USE_IN_MEMORY_MEDIA_STORAGE = False

    storage = get_media_storage()

    assert isinstance(storage, S3MediaStorageAdapter)
    assert not isinstance(storage, InMemoryMediaStorageAdapter)


def test_get_media_storage_propagates_a_construction_failure_instead_of_degrading(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure constructing the real storage adapter (missing dependency,
    bad configuration, an unreachable client, ...) must propagate and fail
    the request loudly, never be swallowed into a silent, permanent
    fallback to the non-durable, per-process in-memory adapter."""
    settings.USE_IN_MEMORY_MEDIA_STORAGE = False

    def _boom(self: object, *args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated S3 adapter construction failure")

    monkeypatch.setattr(S3MediaStorageAdapter, "__init__", _boom)

    with pytest.raises(RuntimeError, match="simulated S3 adapter construction failure"):
        get_media_storage()
