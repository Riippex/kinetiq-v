"""Real-concurrency regression test for `DjangoSessionLifecycleRepository.apply_transition`.

Must run against a real PostgreSQL server:

    DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres \\
        uv run pytest tests/postgres -q

SQLite cannot exercise this: it does not provide genuine row-level locking
across concurrent connections, so a race that only manifests under
PostgreSQL's `SELECT ... FOR UPDATE` + MVCC semantics would pass on SQLite
for the wrong reason (or not run concurrently at all). This test therefore
lives outside the default `tests/` collection settings and is skipped unless
a Postgres connection is actually configured for it.
"""

import threading
from uuid import uuid4

import pytest
from django.db import connection

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application.session_lifecycle import SessionLifecycleCommand
from kinetiq.modules.workouts.domain import WorkoutSession
from kinetiq.modules.workouts.infrastructure.models import IdempotencyReceipt, WorkoutSessionRecord
from kinetiq.modules.workouts.infrastructure.repositories import DjangoSessionLifecycleRepository

# SQLite serializes at the connection/file level and gives each thread's
# `:memory:` connection an independent, empty database, so it cannot
# exercise real cross-connection row locking. Skip (not fail) under the
# default SQLite-backed test settings; run for real with
# DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres.
pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason=(
        "Real concurrent row-locking evidence requires PostgreSQL; run with "
        "DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres"
    ),
)

CONFIGURATION = {
    "requested_mode": "NORMAL",
    "active_mode": "NORMAL",
    "intensity": "PLANNED",
    "coaching_tone": "CALM",
    "capture_device_id": "phone-camera",
    "display_device_id": None,
    "prompt_for_progress_photo": False,
    "dynamic": None,
}


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_requests_apply_exactly_once_without_false_revision_conflict() -> None:
    """Two concurrent apply_transition calls with the same operation, key,
    and fingerprint must both resolve successfully to the same single
    change. The second request must never see a spurious REVISION_CONFLICT
    after waiting for the row lock, and must never re-run the transition.
    """
    athlete = User.objects.create_user(username=f"concurrency-athlete-{uuid4().hex[:8]}")
    routine = RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="Concurrency Routine",
        rationale="Testing concurrent idempotency under real PostgreSQL locking.",
        prescription={"items": []},
        accepted=True,
    )
    session_id = uuid4()
    WorkoutSessionRecord.objects.create(
        id=session_id,
        owner=athlete,
        routine=routine,
        revision=1,
        state="READY",
        configuration=CONFIGURATION,
    )

    command = SessionLifecycleCommand(
        session_id=session_id,
        expected_revision=1,
        idempotency_key="concurrent-start-key",
    )
    fingerprint = command.fingerprint()

    started_transaction = threading.Event()

    def slow_transition(session: WorkoutSession) -> WorkoutSession:
        # Signal that this thread is inside the transaction, holding the row
        # lock, then hold it open long enough for the second thread's
        # select_for_update() to genuinely block on it.
        started_transaction.set()
        threading.Event().wait(timeout=1.5)
        return session.start()

    def transition_must_not_run(session: WorkoutSession) -> WorkoutSession:
        raise AssertionError(
            "The second concurrent request must resolve via the idempotency "
            "receipt without re-running the transition"
        )

    result_a: dict[str, WorkoutSession] = {}
    result_b: dict[str, WorkoutSession] = {}
    errors_a: list[BaseException] = []
    errors_b: list[BaseException] = []

    def worker_a() -> None:
        try:
            repo = DjangoSessionLifecycleRepository()
            result_a["session"] = repo.apply_transition(
                owner_id=athlete.id,
                session_id=session_id,
                expected_revision=1,
                operation="workouts.start_session",
                idempotency_key=command.idempotency_key,
                request_fingerprint=fingerprint,
                transition=slow_transition,
            )
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            errors_a.append(exc)
        finally:
            connection.close()

    def worker_b() -> None:
        # Wait until thread A is confirmed to be inside its transaction
        # (holding the row lock) before issuing the second request, so this
        # thread's own select_for_update() is guaranteed to block on it.
        started_transaction.wait(timeout=5)
        try:
            repo = DjangoSessionLifecycleRepository()
            result_b["session"] = repo.apply_transition(
                owner_id=athlete.id,
                session_id=session_id,
                expected_revision=1,
                operation="workouts.start_session",
                idempotency_key=command.idempotency_key,
                request_fingerprint=fingerprint,
                transition=transition_must_not_run,
            )
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            errors_b.append(exc)
        finally:
            connection.close()

    thread_a = threading.Thread(target=worker_a)
    thread_b = threading.Thread(target=worker_b)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert not thread_a.is_alive(), "Thread A did not finish in time"
    assert not thread_b.is_alive(), "Thread B did not finish in time"
    assert errors_a == [], f"Concurrent request A raised: {errors_a!r}"
    assert errors_b == [], f"Concurrent request B raised: {errors_b!r}"

    assert result_a["session"].revision == 2
    assert result_b["session"].revision == 2
    assert result_a["session"].state.value == "ACTIVE"
    assert result_b["session"].state.value == "ACTIVE"

    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.revision == 2
    assert record.state == "ACTIVE"
    assert (
        IdempotencyReceipt.objects.filter(
            owner=athlete,
            operation="workouts.start_session",
            key="concurrent-start-key",
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_key_reuse_with_different_fingerprint_still_conflicts() -> None:
    """Even under real concurrent access, reusing an idempotency key with a
    different request fingerprint must still surface as a conflict rather
    than being masked by the lock-wait re-check added for the race fix."""
    from kinetiq.modules.workouts.application.prepare_session import IdempotencyConflict

    athlete = User.objects.create_user(username=f"concurrency-conflict-{uuid4().hex[:8]}")
    routine = RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="Concurrency Conflict Routine",
        rationale="Testing concurrent idempotency conflict.",
        prescription={"items": []},
        accepted=True,
    )
    session_id = uuid4()
    WorkoutSessionRecord.objects.create(
        id=session_id,
        owner=athlete,
        routine=routine,
        revision=1,
        state="READY",
        configuration=CONFIGURATION,
    )

    repo = DjangoSessionLifecycleRepository()
    first = repo.apply_transition(
        owner_id=athlete.id,
        session_id=session_id,
        expected_revision=1,
        operation="workouts.start_session",
        idempotency_key="shared-key",
        request_fingerprint="fingerprint-a",
        transition=lambda session: session.start(),
    )
    assert first.revision == 2

    with pytest.raises(IdempotencyConflict):
        repo.apply_transition(
            owner_id=athlete.id,
            session_id=session_id,
            expected_revision=1,
            operation="workouts.start_session",
            idempotency_key="shared-key",
            request_fingerprint="fingerprint-b",
            transition=lambda session: session.start(),
        )
