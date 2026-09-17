from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from kinetiq.modules.workouts.application.ports import AcceptedRoutineItem
from kinetiq.modules.workouts.application.session_lifecycle import (
    FinishSessionCommand,
    FinishWorkoutSessionUseCase,
    InconsistentPerformedSetMeasurementError,
    UnknownRoutineExerciseError,
)
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DuplicatePerformedSetError,
    PerformedSet,
    SessionConfiguration,
    SessionIntensity,
    SessionMode,
    WorkoutSession,
)

ROUTINE_ID = uuid4()
ROUTINE_VERSION = 1


class FakeSessionLifecycleRepository:
    def __init__(self, session: WorkoutSession) -> None:
        self.session = session

    def get_session(self, *, owner_id: UUID, session_id: UUID) -> WorkoutSession | None:
        return self.session

    def apply_transition(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_revision: int,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        transition: Callable[[WorkoutSession], WorkoutSession],
    ) -> WorkoutSession:
        self.session = transition(self.session)
        return self.session


class FakeRoutineItemLookup:
    def __init__(self, items: tuple[AcceptedRoutineItem, ...] | None) -> None:
        self._items = items
        self.calls: list[tuple[UUID, UUID, int]] = []

    def get_accepted_routine_items(
        self, *, owner_id: UUID, routine_id: UUID, version: int
    ) -> tuple[AcceptedRoutineItem, ...] | None:
        self.calls.append((owner_id, routine_id, version))
        return self._items


def active_session() -> WorkoutSession:
    configuration = SessionConfiguration(
        requested_mode=SessionMode.NORMAL,
        active_mode=SessionMode.NORMAL,
        intensity=SessionIntensity.PLANNED,
        coaching_tone=CoachingTone.CALM,
        capture_device_id="phone-camera",
        display_device_id=None,
        prompt_for_progress_photo=False,
        dynamic=None,
    )
    return WorkoutSession.prepare(
        session_id=uuid4(),
        owner_id=uuid4(),
        routine_id=ROUTINE_ID,
        routine_version=ROUTINE_VERSION,
        configuration=configuration,
    ).start()


def make_command(performed_sets: tuple[PerformedSet, ...]) -> FinishSessionCommand:
    return FinishSessionCommand(
        session_id=uuid4(),
        expected_revision=2,
        idempotency_key="finish-key",
        performed_sets=performed_sets,
    )


def test_finish_accepts_performed_sets_matching_routine_prescription() -> None:
    session = active_session()
    lookup = FakeRoutineItemLookup(
        (
            AcceptedRoutineItem(
                exercise_id="exercise-push-up-v1", repetitions=10, duration_seconds=None
            ),
            AcceptedRoutineItem(
                exercise_id="exercise-plank-v1", repetitions=None, duration_seconds=45
            ),
        )
    )
    repo = FakeSessionLifecycleRepository(session)
    use_case = FinishWorkoutSessionUseCase(repo, lookup)

    performed = (
        PerformedSet(exercise_id="exercise-push-up-v1", set_order=1, repetitions=12),
        PerformedSet(exercise_id="exercise-plank-v1", set_order=1, duration_seconds=50),
    )

    finished = use_case.execute(owner_id=session.owner_id, command=make_command(performed))

    assert finished.confirmed_repetitions == 12
    assert len(finished.performed_sets) == 2
    assert lookup.calls == [(session.owner_id, ROUTINE_ID, ROUTINE_VERSION)]


def test_finish_rejects_exercise_not_in_accepted_routine() -> None:
    """Regression test: a performed set naming an exercise absent from the
    exact accepted routine version must be rejected."""
    session = active_session()
    lookup = FakeRoutineItemLookup(
        (
            AcceptedRoutineItem(
                exercise_id="exercise-push-up-v1", repetitions=10, duration_seconds=None
            ),
        )
    )
    use_case = FinishWorkoutSessionUseCase(FakeSessionLifecycleRepository(session), lookup)

    performed = (PerformedSet(exercise_id="exercise-unrelated-v1", set_order=1, repetitions=5),)

    with pytest.raises(UnknownRoutineExerciseError, match="exercise-unrelated-v1"):
        use_case.execute(owner_id=session.owner_id, command=make_command(performed))


def test_finish_rejects_when_accepted_routine_is_unavailable() -> None:
    session = active_session()
    lookup = FakeRoutineItemLookup(None)
    use_case = FinishWorkoutSessionUseCase(FakeSessionLifecycleRepository(session), lookup)

    performed = (PerformedSet(exercise_id="exercise-push-up-v1", set_order=1, repetitions=5),)

    with pytest.raises(UnknownRoutineExerciseError):
        use_case.execute(owner_id=session.owner_id, command=make_command(performed))


def test_finish_rejects_missing_duration_for_duration_prescribed_exercise() -> None:
    session = active_session()
    lookup = FakeRoutineItemLookup(
        (
            AcceptedRoutineItem(
                exercise_id="exercise-plank-v1", repetitions=None, duration_seconds=45
            ),
        )
    )
    use_case = FinishWorkoutSessionUseCase(FakeSessionLifecycleRepository(session), lookup)

    # Repetitions provided instead of the required duration.
    performed = (PerformedSet(exercise_id="exercise-plank-v1", set_order=1, repetitions=10),)

    with pytest.raises(InconsistentPerformedSetMeasurementError, match="duration"):
        use_case.execute(owner_id=session.owner_id, command=make_command(performed))


def test_finish_rejects_missing_repetitions_for_repetitions_prescribed_exercise() -> None:
    session = active_session()
    lookup = FakeRoutineItemLookup(
        (
            AcceptedRoutineItem(
                exercise_id="exercise-push-up-v1", repetitions=10, duration_seconds=None
            ),
        )
    )
    use_case = FinishWorkoutSessionUseCase(FakeSessionLifecycleRepository(session), lookup)

    # Duration provided instead of the required repetitions.
    performed = (PerformedSet(exercise_id="exercise-push-up-v1", set_order=1, duration_seconds=30),)

    with pytest.raises(InconsistentPerformedSetMeasurementError, match="repetitions"):
        use_case.execute(owner_id=session.owner_id, command=make_command(performed))


def test_finish_rejects_duplicate_performed_set_via_use_case() -> None:
    session = active_session()
    lookup = FakeRoutineItemLookup(
        (
            AcceptedRoutineItem(
                exercise_id="exercise-push-up-v1", repetitions=10, duration_seconds=None
            ),
        )
    )
    use_case = FinishWorkoutSessionUseCase(FakeSessionLifecycleRepository(session), lookup)

    performed = (
        PerformedSet(exercise_id="exercise-push-up-v1", set_order=1, repetitions=10),
        PerformedSet(exercise_id="exercise-push-up-v1", set_order=1, repetitions=8),
    )

    with pytest.raises(DuplicatePerformedSetError):
        use_case.execute(owner_id=session.owner_id, command=make_command(performed))
