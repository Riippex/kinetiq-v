import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from kinetiq.modules.workouts.application.ports import (
    RoutineItemLookup,
    SessionLifecycleRepository,
    UnknownVisionCandidateError,
    VisionCandidateInfo,
    VisionSessionAnalysisPort,
)
from kinetiq.modules.workouts.domain import (
    ObservationCoverage,
    PauseReason,
    PerformedSet,
    SessionFeedback,
    WorkoutSession,
)


class SessionNotFound(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


class UnknownRoutineExerciseError(ValueError):
    """Raised when a performed set names an exercise that is not part of the
    exact accepted routine version the session was prepared against."""


class InconsistentPerformedSetMeasurementError(ValueError):
    """Raised when a performed set's measurement (repetitions vs. duration)
    does not match how the accepted routine prescribes that exercise."""


class VisionAnalysisNotStartedError(ValueError):
    """Raised when confirming a target before a Vision analysis has been
    started and persisted for the session via
    StartSessionVisionAnalysisUseCase. Confirming a target requires an
    analysis_id to address on Vision's side; there is no implicit fallback
    that creates one, since that would reintroduce the "confirm creates a
    fresh analysis on every retry" defect this split was meant to remove."""

    def __init__(self, session_id: UUID) -> None:
        super().__init__(
            f"Session '{session_id}' has no Vision analysis started; call "
            "startSessionVisionAnalysis before confirming a target"
        )
        self.session_id = session_id


VISION_LEASE_TTL_SECONDS = 30
"""How long a Vision lease may be held before another request may steal it.

Must comfortably exceed the slowest expected Vision call (create_analysis
or select_target); if a process holding the lease crashes or hangs, the
lease self-expires after this many seconds rather than blocking that
session's Vision operations forever."""


class VisionOperationInProgressError(ValueError):
    """Raised when a Vision-mutating command (startSessionVisionAnalysis,
    confirmSessionTarget) cannot acquire the session's Vision lease because
    another such command is already in flight for the same session.

    This is the actual fix for the check-then-act race: `check_transition_
    precondition` validates revision/idempotency but releases its row lock
    before the Vision network call, so two different commands with the
    same `expected_revision` could previously both pass that check and
    both call Vision before the loser's local transition failed --
    potentially leaving Vision holding a different target than the one
    Product ultimately persisted. The lease makes the Vision call itself
    exclusive per session: only the command holding the lease may call
    Vision, so a second concurrent command fails fast here, before it
    ever reaches Vision, rather than racing it."""

    def __init__(self, session_id: UUID) -> None:
        super().__init__(
            f"Another Vision operation is already in progress for session '{session_id}'; "
            "retry shortly"
        )
        self.session_id = session_id


@dataclass(frozen=True, slots=True)
class SessionLifecycleCommand:
    session_id: UUID
    expected_revision: int
    idempotency_key: str

    def fingerprint(self) -> str:
        payload = {
            "session_id": str(self.session_id),
            "expected_revision": self.expected_revision,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class FinishSessionCommand(SessionLifecycleCommand):
    performed_sets: tuple[PerformedSet, ...] = ()
    observation_coverage: ObservationCoverage | None = None
    feedback: SessionFeedback | None = None

    def fingerprint(self) -> str:
        sets_data = [
            {
                "exercise_id": s.exercise_id,
                "set_order": s.set_order,
                "repetitions": s.repetitions,
                "duration_seconds": s.duration_seconds,
            }
            for s in self.performed_sets
        ]
        coverage_data = (
            {
                "coverage_ratio": self.observation_coverage.coverage_ratio,
                "tracked_seconds": self.observation_coverage.tracked_seconds,
                "total_seconds": self.observation_coverage.total_seconds,
                "fully_visible_ratio": self.observation_coverage.fully_visible_ratio,
                "untracked_reasons": list(self.observation_coverage.untracked_reasons),
            }
            if self.observation_coverage
            else None
        )
        feedback_data = (
            {
                "perceived_effort": self.feedback.perceived_effort,
                "comments": self.feedback.comments,
            }
            if self.feedback
            else None
        )
        payload = {
            "session_id": str(self.session_id),
            "expected_revision": self.expected_revision,
            "performed_sets": sets_data,
            "observation_coverage": coverage_data,
            "feedback": feedback_data,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RecordSessionFeedbackCommand(SessionLifecycleCommand):
    feedback: SessionFeedback = SessionFeedback()

    def fingerprint(self) -> str:
        payload = {
            "session_id": str(self.session_id),
            "expected_revision": self.expected_revision,
            "feedback": {
                "perceived_effort": self.feedback.perceived_effort,
                "comments": self.feedback.comments,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfirmTargetCommand(SessionLifecycleCommand):
    target_person_id: str = ""

    def fingerprint(self) -> str:
        payload = {
            "session_id": str(self.session_id),
            "expected_revision": self.expected_revision,
            "target_person_id": self.target_person_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


class BaseSessionLifecycleUseCase:
    def __init__(self, repository: SessionLifecycleRepository) -> None:
        self._repository = repository

    def _execute_transition(
        self,
        *,
        owner_id: UUID,
        command: SessionLifecycleCommand,
        operation: str,
        transition: Callable[[WorkoutSession], WorkoutSession],
    ) -> WorkoutSession:
        if not command.idempotency_key.strip():
            raise ValueError("An idempotency key is required")
        if command.expected_revision < 1:
            raise ValueError("Expected revision must be positive")

        return self._repository.apply_transition(
            owner_id=owner_id,
            session_id=command.session_id,
            expected_revision=command.expected_revision,
            operation=operation,
            idempotency_key=command.idempotency_key,
            request_fingerprint=command.fingerprint(),
            transition=transition,
        )


class StartWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.start_session",
            transition=lambda session: session.start(),
        )


class PauseWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(
        self,
        *,
        owner_id: UUID,
        command: SessionLifecycleCommand,
        reason: PauseReason = PauseReason.USER_REQUEST,
    ) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.pause_session",
            transition=lambda session: session.pause(reason=reason),
        )


class ResumeWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.resume_session",
            transition=lambda session: session.resume(),
        )


class DisableDynamicModeUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.disable_dynamic_mode",
            transition=lambda session: session.disable_dynamic_mode(),
        )


class FinishWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def __init__(
        self,
        repository: SessionLifecycleRepository,
        routine_lookup: RoutineItemLookup,
    ) -> None:
        super().__init__(repository)
        self._routine_lookup = routine_lookup

    def execute(
        self, *, owner_id: UUID, command: FinishSessionCommand | SessionLifecycleCommand
    ) -> WorkoutSession:
        def transition(session: WorkoutSession) -> WorkoutSession:
            if isinstance(command, FinishSessionCommand):
                if command.performed_sets:
                    self._validate_performed_sets(
                        owner_id=owner_id,
                        session=session,
                        performed_sets=command.performed_sets,
                    )
                return session.finish(
                    performed_sets=command.performed_sets,
                    observation_coverage=command.observation_coverage,
                    feedback=command.feedback,
                )
            return session.finish()

        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.finish_session",
            transition=transition,
        )

    def _validate_performed_sets(
        self,
        *,
        owner_id: UUID,
        session: WorkoutSession,
        performed_sets: tuple[PerformedSet, ...],
    ) -> None:
        """Verify every performed set names an exercise from the exact accepted
        routine version the session was prepared against, with a measurement
        (repetitions vs. duration) consistent with that routine's prescription.
        """
        items = self._routine_lookup.get_accepted_routine_items(
            owner_id=owner_id,
            routine_id=session.routine_id,
            version=session.routine_version,
        )
        if items is None:
            raise UnknownRoutineExerciseError(
                f"Accepted routine {session.routine_id} version {session.routine_version} "
                "is unavailable for activity validation"
            )
        items_by_exercise_id = {item.exercise_id: item for item in items}

        for performed_set in performed_sets:
            item = items_by_exercise_id.get(performed_set.exercise_id)
            if item is None:
                raise UnknownRoutineExerciseError(
                    f"Exercise '{performed_set.exercise_id}' is not part of the accepted "
                    f"routine version {session.routine_version}"
                )

            expects_duration = item.duration_seconds is not None
            expects_repetitions = item.repetitions is not None

            if expects_duration and performed_set.duration_seconds is None:
                raise InconsistentPerformedSetMeasurementError(
                    f"Exercise '{performed_set.exercise_id}' is prescribed by duration; "
                    "a duration measurement is required"
                )
            if expects_repetitions and performed_set.repetitions is None:
                raise InconsistentPerformedSetMeasurementError(
                    f"Exercise '{performed_set.exercise_id}' is prescribed by repetitions; "
                    "a repetitions measurement is required"
                )
            if expects_duration and performed_set.repetitions is not None:
                raise InconsistentPerformedSetMeasurementError(
                    f"Exercise '{performed_set.exercise_id}' is prescribed by duration; "
                    "repetitions must not be provided"
                )
            if expects_repetitions and performed_set.duration_seconds is not None:
                raise InconsistentPerformedSetMeasurementError(
                    f"Exercise '{performed_set.exercise_id}' is prescribed by repetitions; "
                    "duration must not be provided"
                )


class RecordSessionFeedbackUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: RecordSessionFeedbackCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.record_session_feedback",
            transition=lambda session: session.record_feedback(command.feedback),
        )


class AbandonWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.abandon_session",
            transition=lambda session: session.abandon(),
        )


def _resolve_exercise_key(
    *, routine_items: RoutineItemLookup, owner_id: UUID, session: WorkoutSession
) -> str:
    items = routine_items.get_accepted_routine_items(
        owner_id=owner_id, routine_id=session.routine_id, version=session.routine_version
    )
    if not items:
        raise ValueError(
            f"No accepted routine items found for session '{session.id}'; "
            "cannot determine which exercise to start a Vision analysis for"
        )
    # Simplification, disclosed: one Vision analysis per session is
    # started against the routine's first prescribed exercise. Catalog
    # exercise IDs and Vision's exercise_key vocabulary are the same
    # reconciled strings (bodyweight_squat, push_up, plank,
    # glute_bridge -- see VV-101/contract adoption), so this is a
    # direct pass-through, not a guess. Per-exercise Vision analysis
    # switching as the session progresses through the routine is not
    # implemented; the same analysis (and its exercise_key) is reused
    # for the whole session until VV-501 exercise engines exist.
    return items[0].exercise_id


class StartSessionVisionAnalysisUseCase(BaseSessionLifecycleUseCase):
    """Starts (idempotently) the Vision analysis for a session's capture
    device -- the first step of the target-enrollment lifecycle, split out
    from confirmation so a client can start an analysis, let frames stream
    into it on the Vision side (populating candidates via Vision's own
    frame-ingestion endpoint), query the detected candidates, and only then
    confirm one -- instead of one combined mutation that both starts and
    confirms, which cannot express "no candidates yet" without either
    failing outright or silently creating a fresh Vision analysis on every
    retry.

    Validates the local revision and idempotency command against
    PostgreSQL (`check_transition_precondition`) BEFORE calling Vision, so
    a stale `expected_revision` or a replayed idempotency key never reaches
    Vision at all.
    """

    def __init__(
        self,
        repository: SessionLifecycleRepository,
        vision_client: VisionSessionAnalysisPort,
        routine_items: RoutineItemLookup,
    ) -> None:
        super().__init__(repository)
        self._vision = vision_client
        self._routine_items = routine_items

    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        if not command.idempotency_key.strip():
            raise ValueError("An idempotency key is required")
        if command.expected_revision < 1:
            raise ValueError("Expected revision must be positive")

        # Acquire the lease BEFORE checking the precondition, not after:
        # holding it across the whole precondition-check-through-Vision-
        # through-apply_transition sequence means no other Vision-mutating
        # command for this session can even read a revision that is about
        # to become stale while we are mid-flight -- it fails fast on the
        # lease instead. See VisionOperationInProgressError.
        lease_token = self._repository.acquire_vision_lease(
            owner_id=owner_id, session_id=command.session_id, ttl_seconds=VISION_LEASE_TTL_SECONDS
        )
        if lease_token is None:
            raise VisionOperationInProgressError(command.session_id)

        try:
            precondition = self._repository.check_transition_precondition(
                owner_id=owner_id,
                session_id=command.session_id,
                expected_revision=command.expected_revision,
                operation="workouts.start_vision_analysis",
                idempotency_key=command.idempotency_key,
                request_fingerprint=command.fingerprint(),
            )
            if precondition.already_applied:
                return precondition.session

            session = precondition.session
            if session.vision_analysis_id is not None:
                # Already started -- nothing to do locally, and calling
                # Vision again would be redundant (Vision's own idempotency
                # key would just resolve to the same analysis, but the
                # point of this early return is to avoid the network call
                # altogether).
                return session

            exercise_key = _resolve_exercise_key(
                routine_items=self._routine_items, owner_id=owner_id, session=session
            )
            # Deterministic idempotency key: retries or concurrent requests
            # for the same session must not create duplicate Vision
            # analyses -- Vision's contract guarantees POST /v1/analyses is
            # idempotent on this key.
            created = self._vision.create_analysis(
                session_id=session.id,
                source_id=session.configuration.capture_device_id,
                exercise_key=exercise_key,
                exercise_version=1,
                idempotency_key=f"session-analysis-{session.id}",
            )

            return self._execute_transition(
                owner_id=owner_id,
                command=command,
                operation="workouts.start_vision_analysis",
                transition=lambda s: s.attach_vision_analysis(
                    vision_analysis_id=created.analysis_id, vision_epoch=created.epoch
                ),
            )
        finally:
            self._repository.release_vision_lease(
                owner_id=owner_id, session_id=command.session_id, lease_token=lease_token
            )


class ListVisionCandidatesUseCase:
    """Read-only boundary onto Vision's currently detected candidates for
    the analysis already attached to a session. Returns an empty tuple,
    never an error, when no analysis has been started yet or Vision has
    not detected anyone so far -- letting a client poll this safely while
    frames are still streaming in, without special-casing "not started"."""

    def __init__(
        self, repository: SessionLifecycleRepository, vision_client: VisionSessionAnalysisPort
    ) -> None:
        self._repository = repository
        self._vision = vision_client

    def execute(self, *, owner_id: UUID, session_id: UUID) -> tuple[VisionCandidateInfo, ...]:
        session = self._repository.get_session(owner_id=owner_id, session_id=session_id)
        if session is None:
            raise SessionNotFound(f"Workout session '{session_id}' not found")
        if session.vision_analysis_id is None:
            return ()
        return self._vision.list_candidates(analysis_id=session.vision_analysis_id)


class ConfirmSessionTargetUseCase(BaseSessionLifecycleUseCase):
    """Confirms a Vision-detected candidate as the session's target.

    Requires a Vision analysis to already be attached to the session (via
    StartSessionVisionAnalysisUseCase) -- this use case no longer creates
    one itself; see that class and ListVisionCandidatesUseCase for the
    preceding steps of the split target-enrollment lifecycle.

    Validates the local revision and idempotency command against
    PostgreSQL (`check_transition_precondition`) BEFORE calling Vision, so
    a stale `expected_revision` is caught before Vision's own
    `/v1/analyses/{id}/target` is ever called. Then verifies the requested
    candidate_id is currently among Vision's detected candidates, confirms
    it via Vision (which independently enforces expected_epoch and can
    raise VisionStaleEpochError), and only then completes the local
    transition. The Vision calls happen outside `_execute_transition`'s
    locked retry loop -- they are not pure and must not run more than the
    minimum necessary times per request.
    """

    def __init__(
        self,
        repository: SessionLifecycleRepository,
        vision_client: VisionSessionAnalysisPort,
    ) -> None:
        super().__init__(repository)
        self._vision = vision_client

    def execute(self, *, owner_id: UUID, command: ConfirmTargetCommand) -> WorkoutSession:
        if not command.idempotency_key.strip():
            raise ValueError("An idempotency key is required")
        if command.expected_revision < 1:
            raise ValueError("Expected revision must be positive")

        # Acquire the lease BEFORE checking the precondition -- see the
        # identical comment in StartSessionVisionAnalysisUseCase.execute().
        # This is what makes two different candidates racing on the same
        # expected_revision safe: only the lease holder ever reaches
        # Vision's list_candidates/select_target, so a losing concurrent
        # request fails on VisionOperationInProgressError before it can
        # mutate Vision at all.
        lease_token = self._repository.acquire_vision_lease(
            owner_id=owner_id, session_id=command.session_id, ttl_seconds=VISION_LEASE_TTL_SECONDS
        )
        if lease_token is None:
            raise VisionOperationInProgressError(command.session_id)

        try:
            precondition = self._repository.check_transition_precondition(
                owner_id=owner_id,
                session_id=command.session_id,
                expected_revision=command.expected_revision,
                operation="workouts.confirm_target",
                idempotency_key=command.idempotency_key,
                request_fingerprint=command.fingerprint(),
            )
            if precondition.already_applied:
                return precondition.session

            session = precondition.session
            if session.vision_analysis_id is None:
                raise VisionAnalysisNotStartedError(session.id)

            analysis_id = session.vision_analysis_id
            epoch = session.vision_epoch or 1

            candidates = self._vision.list_candidates(analysis_id=analysis_id)
            if command.target_person_id not in {c.candidate_id for c in candidates}:
                raise UnknownVisionCandidateError(command.target_person_id, analysis_id)

            confirmation = self._vision.select_target(
                analysis_id=analysis_id,
                candidate_id=command.target_person_id,
                expected_epoch=epoch,
                idempotency_key=command.idempotency_key,
            )

            return self._execute_transition(
                owner_id=owner_id,
                command=command,
                operation="workouts.confirm_target",
                transition=lambda s: s.confirm_target(
                    confirmation.target_person_id,
                    vision_epoch=confirmation.epoch,
                ),
            )
        finally:
            self._repository.release_vision_lease(
                owner_id=owner_id, session_id=command.session_id, lease_token=lease_token
            )


class GetWorkoutSessionUseCase:
    """Reads a single owner-scoped workout session through the repository
    port, so interface-layer resolvers never query workouts tables directly.
    """

    def __init__(self, repository: SessionLifecycleRepository) -> None:
        self._repository = repository

    def execute(self, *, owner_id: UUID, session_id: UUID) -> WorkoutSession | None:
        return self._repository.get_session(owner_id=owner_id, session_id=session_id)
