import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from kinetiq.modules.workouts.application.ports import (
    RoutineItemLookup,
    SessionLifecycleRepository,
    UnknownVisionCandidateError,
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
    def execute(
        self, *, owner_id: UUID, command: RecordSessionFeedbackCommand
    ) -> WorkoutSession:
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


class ConfirmSessionTargetUseCase(BaseSessionLifecycleUseCase):
    """Confirms a Vision-detected candidate as the session's target.

    Unlike the other lifecycle transitions, this one has a genuine external
    dependency: it must select a candidate that Vision actually detected
    for an active analysis, not merely persist whatever string a client
    supplies. It creates (idempotently, reusing an already-attached
    analysis if one exists) a Vision analysis for the session's capture
    device, verifies the requested candidate_id is currently among
    Vision's detected candidates, and only then confirms it via Vision's
    own `/v1/analyses/{id}/target` (which independently enforces
    expected_epoch and can raise VisionStaleEpochError), before persisting
    the result. The Vision calls happen outside `_execute_transition`'s
    locked retry loop -- they are not pure and must not run more than the
    minimum necessary times per request.
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

    def execute(self, *, owner_id: UUID, command: ConfirmTargetCommand) -> WorkoutSession:
        session = self._repository.get_session(owner_id=owner_id, session_id=command.session_id)
        if session is None:
            raise SessionNotFound(f"Workout session '{command.session_id}' not found")

        analysis_id, epoch = self._ensure_vision_analysis(owner_id=owner_id, session=session)

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
                vision_analysis_id=analysis_id,
                vision_epoch=confirmation.epoch,
            ),
        )

    def _ensure_vision_analysis(
        self, *, owner_id: UUID, session: WorkoutSession
    ) -> tuple[str, int]:
        if session.vision_analysis_id is not None:
            return session.vision_analysis_id, session.vision_epoch or 1

        exercise_key = self._resolve_exercise_key(owner_id=owner_id, session=session)
        # Deterministic idempotency key: retries or concurrent requests for
        # the same session must not create duplicate Vision analyses --
        # Vision's contract guarantees POST /v1/analyses is idempotent on
        # this key.
        created = self._vision.create_analysis(
            session_id=session.id,
            source_id=session.configuration.capture_device_id,
            exercise_key=exercise_key,
            exercise_version=1,
            idempotency_key=f"session-analysis-{session.id}",
        )
        return created.analysis_id, created.epoch

    def _resolve_exercise_key(self, *, owner_id: UUID, session: WorkoutSession) -> str:
        items = self._routine_items.get_accepted_routine_items(
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



class GetWorkoutSessionUseCase:
    """Reads a single owner-scoped workout session through the repository
    port, so interface-layer resolvers never query workouts tables directly.
    """

    def __init__(self, repository: SessionLifecycleRepository) -> None:
        self._repository = repository

    def execute(self, *, owner_id: UUID, session_id: UUID) -> WorkoutSession | None:
        return self._repository.get_session(owner_id=owner_id, session_id=session_id)
