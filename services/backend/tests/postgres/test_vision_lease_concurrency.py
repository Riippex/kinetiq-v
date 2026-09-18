"""Real-concurrency regression test for the Vision command lease.

Must run against a real PostgreSQL server:

    DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres \\
        uv run pytest tests/postgres -q

Proves the fix for the Block 4 finding: two different confirmSessionTarget
commands, both targeting different candidates with the same
expected_revision, must not both mutate Vision. Before the lease, each
command's `check_transition_precondition` released its PostgreSQL row lock
before calling Vision, so both requests could pass that check and both
call Vision's select_target before either persisted locally -- leaving
Vision holding whichever candidate was sent last, independent of which
local write ultimately won. The lease (`acquire_vision_lease`) is held
across the whole precondition-check-through-apply_transition sequence, so
only the lease holder ever reaches Vision; the loser fails immediately on
VisionOperationInProgressError without touching Vision at all.
"""

import threading
from uuid import uuid4

import pytest
from django.db import connection

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application.ports import (
    VisionCandidateInfo,
    VisionTargetConfirmation,
)
from kinetiq.modules.workouts.application.session_lifecycle import (
    ConfirmSessionTargetUseCase,
    ConfirmTargetCommand,
    VisionOperationInProgressError,
)
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord
from kinetiq.modules.workouts.infrastructure.repositories import DjangoSessionLifecycleRepository

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
    "vision_analysis_id": "an_race_1",
    "vision_epoch": 1,
}


class SlowTwoCandidateVisionPort:
    """A Vision double whose select_target call is slow enough (and
    signals a shared Event when it starts) to let a real concurrent test
    reliably force the second thread's lease-acquisition attempt to land
    while the first thread is still inside its own call -- otherwise the
    race would be too fast to reproduce deterministically."""

    def __init__(self, *, select_target_started: threading.Event) -> None:
        self._select_target_started = select_target_started
        self.candidates = (
            VisionCandidateInfo(candidate_id="candidate-x", confidence=0.9),
            VisionCandidateInfo(candidate_id="candidate-y", confidence=0.9),
        )
        self.select_target_calls: list[tuple[str, str, int]] = []

    def list_candidates(self, *, analysis_id: str) -> tuple[VisionCandidateInfo, ...]:
        return self.candidates

    def select_target(
        self, *, analysis_id: str, candidate_id: str, expected_epoch: int, idempotency_key: str
    ) -> VisionTargetConfirmation:
        self.select_target_calls.append((analysis_id, candidate_id, expected_epoch))
        self._select_target_started.set()
        threading.Event().wait(timeout=1.0)
        return VisionTargetConfirmation(
            target_person_id=candidate_id, epoch=expected_epoch, state="TRACKING"
        )


@pytest.mark.django_db(transaction=True)
def test_two_different_candidates_racing_never_both_reach_vision() -> None:
    athlete = User.objects.create_user(username=f"vision-race-athlete-{uuid4().hex[:8]}")
    routine = RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="Vision Race Routine",
        rationale="Testing concurrent target confirmation under real PostgreSQL locking.",
        prescription={"items": []},
        accepted=True,
    )
    session_id = uuid4()
    WorkoutSessionRecord.objects.create(
        id=session_id,
        owner=athlete,
        routine=routine,
        revision=1,
        state="ACTIVE",
        configuration=CONFIGURATION,
    )

    select_target_started = threading.Event()
    vision = SlowTwoCandidateVisionPort(select_target_started=select_target_started)

    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def confirm(candidate_id: str, idempotency_key: str, result_key: str) -> None:
        try:
            repo = DjangoSessionLifecycleRepository()
            use_case = ConfirmSessionTargetUseCase(repo, vision)
            command = ConfirmTargetCommand(
                session_id=session_id,
                expected_revision=1,
                idempotency_key=idempotency_key,
                target_person_id=candidate_id,
            )
            results[result_key] = use_case.execute(owner_id=athlete.id, command=command)
        except BaseException as exc:  # noqa: BLE001 - captured for assertions below
            errors[result_key] = exc
        finally:
            connection.close()

    def worker_a() -> None:
        confirm("candidate-x", "confirm-x", "a")

    def worker_b() -> None:
        # Wait until thread A is confirmed to be inside Vision's
        # select_target (holding the lease) before issuing the second
        # request, so this thread's own lease acquisition is guaranteed
        # to contend with a live lease rather than possibly running first.
        select_target_started.wait(timeout=5)
        confirm("candidate-y", "confirm-y", "b")

    thread_a = threading.Thread(target=worker_a)
    thread_b = threading.Thread(target=worker_b)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=10)
    thread_b.join(timeout=10)

    assert not thread_a.is_alive(), "Thread A did not finish in time"
    assert not thread_b.is_alive(), "Thread B did not finish in time"

    # Exactly one thread must have succeeded, and the other must have
    # failed fast on the lease -- never on a Vision error, and never by
    # both silently succeeding.
    assert set(results.keys()) | set(errors.keys()) == {"a", "b"}
    assert len(results) == 1, f"expected exactly one success, got results={results} errors={errors}"
    assert len(errors) == 1, f"expected exactly one failure, got results={results} errors={errors}"

    failed_key = next(iter(errors))
    assert isinstance(errors[failed_key], VisionOperationInProgressError), (
        f"the losing request must fail on the lease, not on: {errors[failed_key]!r}"
    )

    # Vision must have been mutated exactly once -- the race is closed
    # before it ever reaches Vision, not merely resolved afterward.
    assert len(vision.select_target_calls) == 1
    winning_analysis_id, winning_candidate_id, winning_epoch = vision.select_target_calls[0]

    succeeded_key = next(iter(results))
    winning_session = results[succeeded_key]
    assert winning_session.target_person_id == winning_candidate_id
    assert winning_session.vision_epoch == winning_epoch

    # Product's persisted state must agree exactly with what was sent to
    # Vision -- proving Product and Vision end with the same target and
    # epoch, not just that a local write won.
    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.configuration["target_person_id"] == winning_candidate_id
    assert record.configuration["vision_epoch"] == winning_epoch
    assert record.configuration["vision_analysis_id"] == winning_analysis_id

    # The lease itself must be fully released, not left held after the
    # race (which would incorrectly block a later, legitimate retry).
    record.refresh_from_db()
    assert record.vision_lease_token is None
    assert record.vision_lease_expires_at is None
