from collections.abc import Callable
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from kinetiq.modules.integrations.vision_adapter import VisionStaleEpochError
from kinetiq.modules.workouts.application.ports import (
    AcceptedRoutineItem,
    TransitionPrecondition,
    UnknownVisionCandidateError,
    VisionAnalysisHandle,
    VisionCandidateInfo,
    VisionTargetConfirmation,
)
from kinetiq.modules.workouts.application.prepare_session import IdempotencyConflict
from kinetiq.modules.workouts.application.session_lifecycle import (
    ConfirmSessionTargetUseCase,
    ConfirmTargetCommand,
    RevisionConflict,
    SessionLifecycleCommand,
    SessionNotFound,
    StartSessionVisionAnalysisUseCase,
    VisionAnalysisNotStartedError,
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
    """In-memory double mirroring DjangoSessionLifecycleRepository's
    revision + idempotency-receipt semantics closely enough to test
    check_transition_precondition's "validate before mutating Vision"
    contract and apply_transition's final safe-completion contract."""

    def __init__(self, session: WorkoutSession | None) -> None:
        self.session = session
        self._receipts: dict[tuple[str, str], tuple[str, WorkoutSession]] = {}

    def get_session(self, *, owner_id: UUID, session_id: UUID) -> WorkoutSession | None:
        return self.session

    def check_transition_precondition(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_revision: int,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> TransitionPrecondition:
        receipt = self._receipts.get((operation, idempotency_key))
        if receipt is not None:
            fingerprint, resolved_session = receipt
            if fingerprint != request_fingerprint:
                raise IdempotencyConflict(
                    "The idempotency key was already used for another command"
                )
            return TransitionPrecondition(already_applied=True, session=resolved_session)

        if self.session is None:
            raise SessionNotFound(f"Workout session '{session_id}' not found")
        if self.session.revision != expected_revision:
            raise RevisionConflict(
                f"Session revision conflict: expected {expected_revision}, "
                f"current is {self.session.revision}"
            )
        return TransitionPrecondition(already_applied=False, session=self.session)

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
        receipt = self._receipts.get((operation, idempotency_key))
        if receipt is not None:
            fingerprint, resolved_session = receipt
            if fingerprint != request_fingerprint:
                raise IdempotencyConflict(
                    "The idempotency key was already used for another command"
                )
            return resolved_session

        if self.session is None:
            raise SessionNotFound(f"Workout session '{session_id}' not found")
        if self.session.revision != expected_revision:
            raise RevisionConflict(
                f"Session revision conflict: expected {expected_revision}, "
                f"current is {self.session.revision}"
            )
        self.session = transition(self.session)
        self._receipts[(operation, idempotency_key)] = (request_fingerprint, self.session)
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
        self.list_candidates_calls = 0
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
        self.list_candidates_calls += 1
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


def session_with_analysis(analysis_id: str = "an_existing", epoch: int = 1) -> WorkoutSession:
    return replace(ready_session(), vision_analysis_id=analysis_id, vision_epoch=epoch)


def make_start_command(
    session: WorkoutSession, *, idempotency_key: str = "start-analysis-1"
) -> SessionLifecycleCommand:
    return SessionLifecycleCommand(
        session_id=session.id,
        expected_revision=session.revision,
        idempotency_key=idempotency_key,
    )


def make_confirm_command(
    session: WorkoutSession, target_person_id: str = "cand_1", idempotency_key: str = "confirm-1"
) -> ConfirmTargetCommand:
    return ConfirmTargetCommand(
        session_id=session.id,
        expected_revision=session.revision,
        idempotency_key=idempotency_key,
        target_person_id=target_person_id,
    )


ROUTINE_ITEMS = (
    AcceptedRoutineItem(exercise_id="bodyweight_squat", repetitions=10, duration_seconds=None),
)


# --- StartSessionVisionAnalysisUseCase ---------------------------------


def test_start_vision_analysis_creates_and_persists_analysis() -> None:
    session = ready_session()
    vision = FakeVisionSessionAnalysisPort()
    use_case = StartSessionVisionAnalysisUseCase(
        FakeSessionLifecycleRepository(session), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    started = use_case.execute(owner_id=session.owner_id, command=make_start_command(session))

    assert started.vision_analysis_id == "an_fake_1"
    assert started.vision_epoch == 1
    assert started.revision == session.revision + 1
    assert vision.create_analysis_calls == 1


def test_start_vision_analysis_retry_does_not_leak_a_second_analysis() -> None:
    """Regression test: retrying the exact same start command (same
    idempotency key) must resolve to the already-persisted analysis, not
    create a second one on Vision's side."""
    session = ready_session()
    vision = FakeVisionSessionAnalysisPort()
    repo = FakeSessionLifecycleRepository(session)
    use_case = StartSessionVisionAnalysisUseCase(repo, vision, FakeRoutineItemLookup(ROUTINE_ITEMS))

    command = make_start_command(session)
    first = use_case.execute(owner_id=session.owner_id, command=command)
    second = use_case.execute(owner_id=session.owner_id, command=command)

    assert first.vision_analysis_id == second.vision_analysis_id
    assert second.revision == first.revision
    assert vision.create_analysis_calls == 1


def test_start_vision_analysis_rejects_stale_revision_without_calling_vision() -> None:
    """Regression test for the Product/Vision split-brain defect: a stale
    expected_revision must be caught against PostgreSQL before Vision is
    ever called, not after."""
    session = ready_session()
    vision = FakeVisionSessionAnalysisPort()
    use_case = StartSessionVisionAnalysisUseCase(
        FakeSessionLifecycleRepository(session), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    stale_command = SessionLifecycleCommand(
        session_id=session.id,
        expected_revision=session.revision + 5,
        idempotency_key="start-analysis-stale",
    )

    with pytest.raises(RevisionConflict):
        use_case.execute(owner_id=session.owner_id, command=stale_command)

    assert vision.create_analysis_calls == 0


def test_start_vision_analysis_already_started_is_a_local_no_op() -> None:
    session = session_with_analysis(analysis_id="an_existing", epoch=3)
    vision = FakeVisionSessionAnalysisPort()
    use_case = StartSessionVisionAnalysisUseCase(
        FakeSessionLifecycleRepository(session), vision, FakeRoutineItemLookup(ROUTINE_ITEMS)
    )

    result = use_case.execute(owner_id=session.owner_id, command=make_start_command(session))

    assert result.vision_analysis_id == "an_existing"
    assert result.revision == session.revision
    assert vision.create_analysis_calls == 0


# --- ConfirmSessionTargetUseCase ----------------------------------------


def test_confirm_target_selects_detected_candidate_on_started_analysis() -> None:
    session = session_with_analysis(analysis_id="an_existing", epoch=3)
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_1", confidence=0.9),)
    )
    use_case = ConfirmSessionTargetUseCase(FakeSessionLifecycleRepository(session), vision)

    confirmed = use_case.execute(owner_id=session.owner_id, command=make_confirm_command(session))

    assert confirmed.target_person_id == "cand_1"
    assert confirmed.vision_analysis_id == "an_existing"
    assert confirmed.revision == session.revision + 1
    assert vision.select_target_calls == [("an_existing", "cand_1", 3)]


def test_confirm_target_requires_analysis_to_already_be_started() -> None:
    """No implicit fallback that creates a Vision analysis on confirm --
    that responsibility moved to StartSessionVisionAnalysisUseCase."""
    session = ready_session()
    vision = FakeVisionSessionAnalysisPort()
    use_case = ConfirmSessionTargetUseCase(FakeSessionLifecycleRepository(session), vision)

    with pytest.raises(VisionAnalysisNotStartedError):
        use_case.execute(owner_id=session.owner_id, command=make_confirm_command(session))

    assert vision.create_analysis_calls == 0
    assert vision.list_candidates_calls == 0
    assert vision.select_target_calls == []


def test_confirm_target_rejects_candidate_vision_did_not_detect() -> None:
    """Regression test for the reviewed defect: confirmSessionTarget must
    not persist an arbitrary client-supplied string as the target."""
    session = session_with_analysis()
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_real", confidence=0.9),)
    )
    use_case = ConfirmSessionTargetUseCase(FakeSessionLifecycleRepository(session), vision)

    with pytest.raises(UnknownVisionCandidateError, match="cand_fabricated"):
        use_case.execute(
            owner_id=session.owner_id,
            command=make_confirm_command(session, target_person_id="cand_fabricated"),
        )

    # Rejected before ever calling Vision's own target-confirmation route.
    assert vision.select_target_calls == []


def test_confirm_target_propagates_stale_epoch_from_vision() -> None:
    session = session_with_analysis()
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_1", confidence=0.9),),
        select_target_error=VisionStaleEpochError(
            "stale", expected_epoch=1, current_epoch=2
        ),
    )
    use_case = ConfirmSessionTargetUseCase(FakeSessionLifecycleRepository(session), vision)

    with pytest.raises(VisionStaleEpochError):
        use_case.execute(owner_id=session.owner_id, command=make_confirm_command(session))


def test_confirm_target_raises_session_not_found() -> None:
    vision = FakeVisionSessionAnalysisPort()
    use_case = ConfirmSessionTargetUseCase(FakeSessionLifecycleRepository(None), vision)

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


def test_confirm_target_rejects_stale_revision_without_calling_vision() -> None:
    """Regression test for the Product/Vision split-brain defect: a stale
    expected_revision attempting to select a candidate must be caught
    against PostgreSQL before Vision's list_candidates/select_target are
    ever called -- proving Vision is not mutated on a doomed request."""
    session = session_with_analysis(analysis_id="an_existing", epoch=3)
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_1", confidence=0.9),)
    )
    use_case = ConfirmSessionTargetUseCase(FakeSessionLifecycleRepository(session), vision)

    stale_command = ConfirmTargetCommand(
        session_id=session.id,
        expected_revision=session.revision + 5,
        idempotency_key="confirm-stale",
        target_person_id="cand_1",
    )

    with pytest.raises(RevisionConflict):
        use_case.execute(owner_id=session.owner_id, command=stale_command)

    assert vision.list_candidates_calls == 0
    assert vision.select_target_calls == []


def test_confirm_target_idempotent_retry_does_not_recall_vision() -> None:
    session = session_with_analysis(analysis_id="an_existing", epoch=3)
    vision = FakeVisionSessionAnalysisPort(
        candidates=(VisionCandidateInfo(candidate_id="cand_1", confidence=0.9),)
    )
    repo = FakeSessionLifecycleRepository(session)
    use_case = ConfirmSessionTargetUseCase(repo, vision)

    command = make_confirm_command(session)
    first = use_case.execute(owner_id=session.owner_id, command=command)
    second = use_case.execute(owner_id=session.owner_id, command=command)

    assert first.target_person_id == second.target_person_id == "cand_1"
    assert second.revision == first.revision
    assert vision.select_target_calls == [("an_existing", "cand_1", 3)]
