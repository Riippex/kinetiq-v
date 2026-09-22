"""Real-concurrency evidence for the private-media upload and cleanup paths.

Must run against a real PostgreSQL server:

    DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres \\
        uv run pytest tests/postgres -q

Every worker thread uses its own database connection and all are released by a
barrier. SQLite cannot show any of this (it serializes writers and gives each
thread an independent in-memory database), so the suite skips these tests
unless PostgreSQL is the configured backend. In the default suite the same
paths are covered deterministically, but NOT under real parallelism.
"""

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.db import connection, connections

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.media.application import (
    DeleteProgressPhotoUseCase,
    FinalizeProgressPhotoUseCase,
    MediaCleanupService,
    RequestProgressPhotoUploadUseCase,
)
from kinetiq.modules.media.domain import (
    IdempotencyConflictError,
    InvalidPhotoStateError,
    MediaCleanupReason,
    PhotoNotFoundError,
    ProgressPhotoStatus,
)
from kinetiq.modules.media.infrastructure.models import (
    MediaCleanupJobRecord,
    MediaUploadReceiptRecord,
    ProgressPhotoRecord,
)
from kinetiq.modules.media.infrastructure.repositories import (
    DjangoMediaCleanupRepository,
    DjangoProgressPhotoRepository,
)
from kinetiq.modules.media.infrastructure.storage import InMemoryMediaStorageAdapter

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason=(
        "Real concurrent evidence requires PostgreSQL; run with "
        "DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres"
    ),
)

WORKERS = 6


class RaceObservingRepository(DjangoProgressPhotoRepository):
    """Widens the read-then-insert window and counts requests that lost the race."""

    def __init__(self) -> None:
        self.race_replays = 0
        self._lookups: dict[int, int] = {}
        self._lock = threading.Lock()

    def _find_receipt(self, owner_id, idempotency_key):  # type: ignore[no-untyped-def,override]
        receipt = DjangoProgressPhotoRepository._find_receipt(owner_id, idempotency_key)
        with self._lock:
            count = self._lookups[threading.get_ident()] = (
                self._lookups.get(threading.get_ident(), 0) + 1
            )
            if count == 2:
                # A second lookup by one request means its INSERT lost the race.
                self.race_replays += 1
        if receipt is None:
            # Every racer must read "no receipt" before any of them inserts.
            time.sleep(0.2)
        return receipt


def _run_parallel(calls: list[Callable[[], object]]) -> list[object]:
    """Run each call on its own thread and database connection, all released at once."""
    barrier = threading.Barrier(len(calls))
    outcomes: list[object] = [None] * len(calls)
    thread_connections: set[int] = set()
    guard = threading.Lock()

    def worker(index: int) -> None:
        try:
            with guard:
                thread_connections.add(id(connections["default"]))
            barrier.wait(timeout=10)
            outcomes[index] = calls[index]()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcomes[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "a worker thread is still running"
    assert len(thread_connections) == len(calls), "workers did not use separate connections"
    return outcomes


def _request_use_case(repo: DjangoProgressPhotoRepository) -> RequestProgressPhotoUploadUseCase:
    return RequestProgressPhotoUploadUseCase(repository=repo, storage=InMemoryMediaStorageAdapter())


@pytest.mark.django_db(transaction=True)
def test_parallel_identical_upload_requests_create_exactly_one_photo() -> None:
    owner = User.objects.create_user(username=f"media-race-{uuid4().hex[:8]}")
    repo = RaceObservingRepository()
    use_case = _request_use_case(repo)

    def call() -> object:
        return use_case.execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=1024,
            idempotency_key="race-key",
        )

    outcomes = _run_parallel([call for _ in range(WORKERS)])

    errors = [o for o in outcomes if isinstance(o, BaseException)]
    assert errors == [], errors
    assert len({o.photo_id for o in outcomes}) == 1, "every caller must see the same photo"  # type: ignore[attr-defined]
    assert ProgressPhotoRecord.objects.filter(owner=owner).count() == 1
    assert (
        MediaUploadReceiptRecord.objects.filter(owner=owner, idempotency_key="race-key").count()
        == 1
    )
    # The unique-constraint race path was genuinely exercised.
    assert repo.race_replays >= 1


@pytest.mark.django_db(transaction=True)
def test_parallel_upload_requests_reusing_a_key_with_different_parameters_conflict() -> None:
    owner = User.objects.create_user(username=f"media-conflict-{uuid4().hex[:8]}")
    repo = RaceObservingRepository()
    use_case = _request_use_case(repo)

    def make_call(byte_length: int) -> Callable[[], object]:
        return lambda: use_case.execute(
            owner_id=owner.id,
            session_id=None,
            content_type="image/jpeg",
            byte_length=byte_length,
            idempotency_key="shared-key",
        )

    outcomes = _run_parallel([make_call(1000 + i) for i in range(WORKERS)])

    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    conflicts = [o for o in outcomes if isinstance(o, IdempotencyConflictError)]
    assert len(winners) == 1, outcomes
    assert len(conflicts) == WORKERS - 1, outcomes
    assert ProgressPhotoRecord.objects.filter(owner=owner).count() == 1
    assert MediaUploadReceiptRecord.objects.filter(owner=owner).count() == 1


@pytest.mark.django_db(transaction=True)
def test_parallel_cleanup_workers_claim_a_job_exactly_once() -> None:
    owner = User.objects.create_user(username=f"media-claim-{uuid4().hex[:8]}")
    cleanup = DjangoMediaCleanupRepository()
    now = datetime.now(UTC)
    job = cleanup.enqueue(
        owner_id=owner.id,
        photo_id=uuid4(),
        s3_key="photos/x.jpg",
        reason=MediaCleanupReason.PHOTO_DELETED,
        now=now,
    )

    outcomes = _run_parallel(
        [lambda: cleanup.claim(job_id=job.id, now=now, lease_seconds=300) for _ in range(WORKERS)]
    )

    errors = [o for o in outcomes if isinstance(o, BaseException)]
    assert errors == [], errors
    assert len([o for o in outcomes if o is not None]) == 1, "exactly one worker owns the job"
    assert MediaCleanupJobRecord.objects.get(id=job.id).attempts == 1


@pytest.mark.django_db(transaction=True)
def test_parallel_deletes_of_one_photo_produce_a_single_tombstone_and_job() -> None:
    owner = User.objects.create_user(username=f"media-delete-{uuid4().hex[:8]}")
    storage = InMemoryMediaStorageAdapter()
    photo_repo = DjangoProgressPhotoRepository()
    photo, _ = photo_repo.save_upload_request_idempotently(
        photo=_pending_photo(owner), idempotency_key="k", request_fingerprint="fp"
    )
    storage.put_object_data(s3_key=photo.s3_key, data=b"x" * photo.byte_length)
    delete = DeleteProgressPhotoUseCase(
        repository=photo_repo,
        cleanup=MediaCleanupService(repository=DjangoMediaCleanupRepository(), storage=storage),
    )

    outcomes = _run_parallel(
        [lambda: delete.execute(owner_id=owner.id, photo_id=photo.id) for _ in range(WORKERS)]
    )

    succeeded = [o for o in outcomes if not isinstance(o, BaseException)]
    not_found = [o for o in outcomes if isinstance(o, PhotoNotFoundError)]
    assert len(succeeded) == 1, outcomes
    assert len(not_found) == WORKERS - 1, outcomes
    assert MediaCleanupJobRecord.objects.filter(photo_id=photo.id).count() == 1
    assert ProgressPhotoRecord.objects.get(id=photo.id).status == "DELETED"
    assert not storage.has_object(s3_key=photo.s3_key)


class DelayedGetObjectInfoStorage(InMemoryMediaStorageAdapter):
    """Widens finalize's window between reading the object and writing its
    confirmation, so a concurrent delete has time to commit its tombstone
    first."""

    def __init__(self, delay_seconds: float) -> None:
        super().__init__()
        self._delay_seconds = delay_seconds

    def get_object_info(self, *, s3_key: str):  # type: ignore[no-untyped-def,override]
        info = super().get_object_info(s3_key=s3_key)
        time.sleep(self._delay_seconds)
        return info


@pytest.mark.django_db(transaction=True)
def test_concurrent_finalize_and_delete_never_resurrects_a_deleted_photo() -> None:
    """Second Codex adversarial-review pass: a stale finalize (its object
    read completed before a concurrent delete's tombstone commits) must
    never overwrite that delete when it later writes its confirmation."""
    owner = User.objects.create_user(username=f"media-finalize-delete-{uuid4().hex[:8]}")
    storage = DelayedGetObjectInfoStorage(delay_seconds=0.3)
    photo_repo = DjangoProgressPhotoRepository()
    photo, _ = photo_repo.save_upload_request_idempotently(
        photo=_pending_photo(owner), idempotency_key="k", request_fingerprint="fp"
    )
    storage.put_object_data(s3_key=photo.s3_key, data=b"x" * photo.byte_length)
    cleanup = MediaCleanupService(repository=DjangoMediaCleanupRepository(), storage=storage)
    finalize = FinalizeProgressPhotoUseCase(repository=photo_repo, storage=storage, cleanup=cleanup)
    delete = DeleteProgressPhotoUseCase(repository=photo_repo, cleanup=cleanup)

    finalize_outcome, delete_outcome = _run_parallel(
        [
            lambda: finalize.execute(owner_id=owner.id, photo_id=photo.id),
            lambda: delete.execute(owner_id=owner.id, photo_id=photo.id),
        ]
    )

    assert not isinstance(delete_outcome, BaseException), delete_outcome
    record = ProgressPhotoRecord.objects.get(id=photo.id)
    assert record.status == "DELETED"
    assert record.deleted_at is not None
    # The delete committed first (widened by the read delay above); the
    # stale finalize must see that, not silently resurrect the photo.
    assert isinstance(finalize_outcome, PhotoNotFoundError), finalize_outcome


class DelayedReplayLookupRepository(DjangoProgressPhotoRepository):
    """Widens an upload-request replay's window between reading its receipt
    and refreshing upload authorization, so a concurrent delete has time to
    commit its tombstone first."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay_seconds = delay_seconds

    def _find_receipt(self, owner_id, idempotency_key):  # type: ignore[no-untyped-def,override]
        receipt = DjangoProgressPhotoRepository._find_receipt(owner_id, idempotency_key)
        if receipt is not None:
            time.sleep(self._delay_seconds)
        return receipt


@pytest.mark.django_db(transaction=True)
def test_concurrent_upload_replay_and_delete_never_resurrects_a_deleted_photo() -> None:
    """Second Codex adversarial-review pass: a stale upload-request replay
    (its receipt read completed before a concurrent delete's tombstone
    commits) must never mint/extend authorization for that deleted photo."""
    owner = User.objects.create_user(username=f"media-replay-delete-{uuid4().hex[:8]}")
    storage = InMemoryMediaStorageAdapter()
    photo_repo = DelayedReplayLookupRepository(delay_seconds=0.3)
    request_use_case = RequestProgressPhotoUploadUseCase(repository=photo_repo, storage=storage)
    cleanup = MediaCleanupService(repository=DjangoMediaCleanupRepository(), storage=storage)
    delete = DeleteProgressPhotoUseCase(repository=photo_repo, cleanup=cleanup)

    first = request_use_case.execute(
        owner_id=owner.id,
        session_id=None,
        content_type="image/jpeg",
        byte_length=64,
        idempotency_key="replay-delete-key",
    )

    replay_outcome, delete_outcome = _run_parallel(
        [
            lambda: request_use_case.execute(
                owner_id=owner.id,
                session_id=None,
                content_type="image/jpeg",
                byte_length=64,
                idempotency_key="replay-delete-key",
            ),
            lambda: delete.execute(owner_id=owner.id, photo_id=first.photo_id),
        ]
    )

    assert not isinstance(delete_outcome, BaseException), delete_outcome
    record = ProgressPhotoRecord.objects.get(id=first.photo_id)
    assert record.status == "DELETED"
    assert record.deleted_at is not None
    # The delete committed first (widened by the receipt-lookup delay
    # above); the stale replay must see that, not resurrect authorization.
    assert isinstance(replay_outcome, InvalidPhotoStateError), replay_outcome


def _pending_photo(owner: User):  # type: ignore[no-untyped-def]
    from kinetiq.modules.media.domain import ProgressPhoto

    photo_id = uuid4()
    return ProgressPhoto(
        id=photo_id,
        owner_id=owner.id,
        session_id=None,
        s3_key=f"photos/{owner.id}/{photo_id}.jpg",
        content_type="image/jpeg",
        byte_length=64,
        status=ProgressPhotoStatus.PENDING_UPLOAD,
        created_at=datetime.now(UTC),
    )
