from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from kinetiq.modules.integrations.vision_adapter import VisionStaleEpochError
from kinetiq.modules.workouts.application.ports import (
    AcceptedRoutineItem,
    UnknownVisionCandidateError,
    VisionAnalysisHandle,
    VisionCandidateInfo,
    VisionTargetConfirmation,
)
from kinetiq.modules.workouts.application.session_lifecycle import (
    ConfirmSessionTargetUseCase,
    ConfirmTargetCommand,
    SessionNotFound,
)
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    SessionConfiguration,
    SessionIntensity,
    SessionMode,
    WorkoutSession,
)

ROUTINE_ID = uuid4()
ROUTINE_VERSION = 1


class FakeSessionLifecycleRepository:
    def __init__(self, session: WorkoutSession | None) -> None:
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
        assert self.session is not None
        self.session = transition(self.session)
        return self.session


class FakeRoutineItemLookup:
    def __init__(self, items: tuple[AcceptedRoutineItem, ...] | None) -> None:
        self._items = items

    def get_accepted_routine_items(
        self, *, owner_id: UUID, routine_id: UUID, version: int
    ) -> tuple[AcceptedRoutineItem, ...] | None:
        return self._items


class FakeVisionSessionAnalysisPort:
    def __init__(
        self,
        *,
        candidates: tuple[VisionCandidateInfo, ...] = (),
        select_target_error: Exception | None = None,
    ) -> None:
        self.candidates = candidates
        self.select_target_error = select_target_error
        self.create_analysis_calls = 0
        self.select_target_calls: list[tuple[str, str, int]] = []

    def create_analysis(
        self,
        *,
        session_id: UUID,
        source_id: str,
        exercise_key: str,
        exercise_version: int,
        idempotency_key: str,
    ) -> VisionAnalysisHandle:
        self.create_analysis_calls += 1
        return VisionAnalysisHandle(
            analysis_id="an_fake_1", epoch=1, state="AWAITING_SELECTION"
        )

    def list_candidates(self, *, analysis_id: str) -> tuple[VisionCandidateInfo, ...]:
        return self.candidates

    def select_target(
        self, *, analysis_id: str, candidate_id: str, expected_epoch: int, idempotency_key: str
    ) -> VisionTargetConfirmation:
        self.select_target_calls.append((analysis_id, candidate_id, expected_epoch))
        if self.select_target_error is not None:
            raise self.select_target_error
        return VisionTargetConfirmation(
            target_person_id=candidate_id, epoch=expected_epoch, state="TRACKING"
        )


def ready_session() -> WorkoutSession:
    configuration = SessionConfiguration(
        requested_mode=SessionMode.NORMAL,
        active_mode=SessionMode.NORMAL,
        intensity=SessionIntensity.PLANNED,
        coaching_tone=CoachingTone.CALM,
        capture_device_id="phone-camera-01",
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
    )


def make_command(session: WorkoutSession, target_person_id: str = "cand_1") -> ConfirmTargetCommand:
    return ConfirmTargetCommand(
        session_id=session.id,
        expected_revision=session.revision,
        idempotency_key="confirm-1",
        target_person_id=target_person_id,
    )


ROUTINE_ITEMS = (
    AcceptedRoutineItem(exercise_id="bodyweight_squat", repetitions=10, duration_seconds=None),
)


def test_confirm_target_creates_analysis_and_selects_detected_candidate() -> None:
    session = ready_session()
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_1", confidence=0.9),)
    )
    use_case = ConfirmSessionTargetUseCase(
        FakeSessionLifecycleRepository(session), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    confirmed = use_case.execute(owner_id=session.owner_id, command=make_command(session))

    assert confirmed.target_person_id == "cand_1"
    assert confirmed.vision_analysis_id == "an_fake_1"
    assert confirmed.vision_epoch == 1
    assert confirmed.revision == session.revision + 1
    assert vision.create_analysis_calls == 1
    assert vision.select_target_calls == [("an_fake_1", "cand_1", 1)]


def test_confirm_target_rejects_candidate_vision_did_not_detect() -> None:
    """Regression test for the reviewed defect: confirmSessionTarget must
    not persist an arbitrary client-supplied string as the target."""
    session = ready_session()
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_real", confidence=0.9),)
    )
    use_case = ConfirmSessionTargetUseCase(
        FakeSessionLifecycleRepository(session), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    with pytest.raises(UnknownVisionCandidateError, match="cand_fabricated"):
        use_case.execute(
            owner_id=session.owner_id,
            command=make_command(session, target_person_id="cand_fabricated"),
        )

    # Rejected before ever calling Vision's own target-confirmation route.
    assert vision.select_target_calls == []


def test_confirm_target_reuses_existing_analysis_without_recreating() -> None:
    configuration = SessionConfiguration(
        requested_mode=SessionMode.NORMAL,
        active_mode=SessionMode.NORMAL,
        intensity=SessionIntensity.PLANNED,
        coaching_tone=CoachingTone.CALM,
        capture_device_id="phone-camera-01",
        display_device_id=None,
        prompt_for_progress_photo=False,
        dynamic=None,
    )
    base = WorkoutSession.prepare(
        session_id=uuid4(),
        owner_id=uuid4(),
        routine_id=ROUTINE_ID,
        routine_version=ROUTINE_VERSION,
        configuration=configuration,
    )
    from dataclasses import replace

    session = replace(base, vision_analysis_id="an_existing", vision_epoch=3)

    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_1", confidence=0.9),)
    )
    use_case = ConfirmSessionTargetUseCase(
        FakeSessionLifecycleRepository(session), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    confirmed = use_case.execute(owner_id=session.owner_id, command=make_command(session))

    assert confirmed.vision_analysis_id == "an_existing"
    assert vision.create_analysis_calls == 0
    assert vision.select_target_calls == [("an_existing", "cand_1", 3)]


def test_confirm_target_propagates_stale_epoch_from_vision() -> None:
    session = ready_session()
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_1", confidence=0.9),),
        select_target_error=VisionStaleEpochError(
            "stale", expected_epoch=1, current_epoch=2
        ),
    )
    use_case = ConfirmSessionTargetUseCase(
        FakeSessionLifecycleRepository(session), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    with pytest.raises(VisionStaleEpochError):
        use_case.execute(owner_id=session.owner_id, command=make_command(session))


def test_confirm_target_raises_session_not_found() -> None:
    vision = FakeVisionSessionAnalysisPort()
    use_case = ConfirmSessionTargetUseCase(
        FakeSessionLifecycleRepository(None), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    with pytest.raises(SessionNotFound):
        use_case.execute(
            owner_id=uuid4(),
            command=ConfirmTargetCommand(
                session_id=uuid4(),
                expected_revision=1,
                idempotency_key="x",
                target_person_id="cand_1",
            ),
        )
