from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SessionState(StrEnum):
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class SessionMode(StrEnum):
    NORMAL = "NORMAL"
    DYNAMIC = "DYNAMIC"


class SessionIntensity(StrEnum):
    LIGHTER = "LIGHTER"
    PLANNED = "PLANNED"
    CHALLENGING = "CHALLENGING"


class CoachingTone(StrEnum):
    CALM = "CALM"
    TECHNICAL = "TECHNICAL"
    MOTIVATIONAL = "MOTIVATIONAL"
    EDGY = "EDGY"


class DynamicChallengeType(StrEnum):
    HOLD_POSE = "HOLD_POSE"
    MIRROR_POSE = "MIRROR_POSE"
    QUICK_REPS = "QUICK_REPS"
    RECOVERY = "RECOVERY"


class DynamicChallengeFrequency(StrEnum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class DynamicSessionConfiguration:
    frequency: DynamicChallengeFrequency
    allowed_challenge_types: tuple[DynamicChallengeType, ...]
    scoring_enabled: bool
    narration_enabled: bool
    policy_version: int
    random_seed: UUID

    def __post_init__(self) -> None:
        if not self.allowed_challenge_types:
            raise ValueError("Dynamic mode requires at least one challenge type")
        if len(set(self.allowed_challenge_types)) != len(self.allowed_challenge_types):
            raise ValueError("Dynamic challenge types must be unique")
        if self.policy_version < 1:
            raise ValueError("Dynamic challenge policy version must be positive")


@dataclass(frozen=True, slots=True)
class SessionConfiguration:
    requested_mode: SessionMode
    active_mode: SessionMode
    intensity: SessionIntensity
    coaching_tone: CoachingTone
    capture_device_id: str
    display_device_id: str | None
    prompt_for_progress_photo: bool
    dynamic: DynamicSessionConfiguration | None

    def __post_init__(self) -> None:
        if not self.capture_device_id.strip():
            raise ValueError("A capture device is required")
        if self.requested_mode is SessionMode.NORMAL and self.dynamic is not None:
            raise ValueError("Normal mode cannot include Dynamic configuration")
        if self.requested_mode is SessionMode.DYNAMIC and self.dynamic is None:
            raise ValueError("Dynamic mode requires Dynamic configuration")
        if (
            self.active_mode is SessionMode.DYNAMIC
            and self.requested_mode is not SessionMode.DYNAMIC
        ):
            raise ValueError("Dynamic mode must be selected during preparation")


class PauseReason(StrEnum):
    USER_REQUEST = "USER_REQUEST"
    VISIBILITY = "VISIBILITY"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    CAMERA_DISCONNECTED = "CAMERA_DISCONNECTED"


class InvalidSessionStateTransition(ValueError):
    pass


class DuplicatePerformedSetError(ValueError):
    """Raised when finishing a session with more than one performed set
    sharing the same (exercise_id, set_order) pair."""


@dataclass(frozen=True, slots=True)
class PerformedSet:
    exercise_id: str
    set_order: int
    repetitions: int | None = None
    duration_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.exercise_id.strip():
            raise ValueError("Exercise ID cannot be empty")
        if self.set_order < 1:
            raise ValueError("Set order must be at least 1")
        if self.repetitions is not None and self.repetitions < 0:
            raise ValueError("Repetitions cannot be negative")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise ValueError("Duration seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class ObservationCoverage:
    coverage_ratio: float
    tracked_seconds: int
    total_seconds: int
    fully_visible_ratio: float = 1.0
    untracked_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (0.0 <= self.coverage_ratio <= 1.0):
            raise ValueError("Coverage ratio must be between 0.0 and 1.0")
        if self.tracked_seconds < 0:
            raise ValueError("Tracked seconds cannot be negative")
        if self.total_seconds < 0:
            raise ValueError("Total seconds cannot be negative")
        if not (0.0 <= self.fully_visible_ratio <= 1.0):
            raise ValueError("Fully visible ratio must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class SessionFeedback:
    perceived_effort: int | None = None
    comments: str | None = None

    def __post_init__(self) -> None:
        if self.perceived_effort is not None and not (1 <= self.perceived_effort <= 10):
            raise ValueError("Perceived effort must be between 1 and 10")


@dataclass(frozen=True, slots=True)
class WorkoutSession:
    id: UUID
    owner_id: UUID
    routine_id: UUID
    routine_version: int
    revision: int
    state: SessionState
    configuration: SessionConfiguration
    pause_reason: PauseReason | None = None
    confirmed_repetitions: int = 0
    performed_sets: tuple[PerformedSet, ...] = ()
    observation_coverage: ObservationCoverage | None = None
    feedback: SessionFeedback | None = None
    target_person_id: str | None = None
    # Vision analysis context (kinetiq-v-vision `/v1/analyses`): tracked so
    # confirmSessionTarget and later target reconfirmation can address the
    # same analysis and detect a stale epoch rather than blindly persisting
    # a client-supplied target_person_id with no Vision-side association.
    vision_analysis_id: str | None = None
    vision_epoch: int | None = None
    vision_observation_cursor: str | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.routine_version < 1:
            raise ValueError("Routine version must be positive")
        if self.revision < 1:
            raise ValueError("Session revision must be positive")
        if self.confirmed_repetitions < 0:
            raise ValueError("Confirmed repetitions cannot be negative")

    @classmethod
    def prepare(
        cls,
        *,
        session_id: UUID,
        owner_id: UUID,
        routine_id: UUID,
        routine_version: int,
        configuration: SessionConfiguration,
    ) -> WorkoutSession:
        if configuration.active_mode is not configuration.requested_mode:
            raise ValueError("A prepared session must begin in its requested mode")
        return cls(
            id=session_id,
            owner_id=owner_id,
            routine_id=routine_id,
            routine_version=routine_version,
            revision=1,
            state=SessionState.READY,
            configuration=configuration,
            pause_reason=None,
            confirmed_repetitions=0,
            performed_sets=(),
            observation_coverage=None,
            feedback=None,
            target_person_id=None,
        )

    def confirm_target(
        self,
        target_person_id: str,
        *,
        vision_analysis_id: str | None = None,
        vision_epoch: int | None = None,
    ) -> WorkoutSession:
        if not target_person_id.strip():
            raise ValueError("Target person ID cannot be empty")
        if self.state in (SessionState.COMPLETED, SessionState.ABANDONED):
            raise InvalidSessionStateTransition("Cannot confirm target on a finished session")
        return replace(
            self,
            target_person_id=target_person_id,
            vision_analysis_id=(
                vision_analysis_id if vision_analysis_id is not None else self.vision_analysis_id
            ),
            vision_epoch=vision_epoch if vision_epoch is not None else self.vision_epoch,
            revision=self.revision + 1,
        )

    def start(self) -> WorkoutSession:

        if self.state is not SessionState.READY:
            raise InvalidSessionStateTransition("Only a ready session can start")
        return replace(
            self,
            state=SessionState.ACTIVE,
            revision=self.revision + 1,
            pause_reason=None,
        )

    def pause(self, reason: PauseReason = PauseReason.USER_REQUEST) -> WorkoutSession:
        if self.state is not SessionState.ACTIVE:
            raise InvalidSessionStateTransition("Only an active session can be paused")
        return replace(
            self,
            state=SessionState.PAUSED,
            revision=self.revision + 1,
            pause_reason=reason,
        )

    def resume(self) -> WorkoutSession:
        if self.state is not SessionState.PAUSED:
            raise InvalidSessionStateTransition("Only a paused session can be resumed")
        return replace(
            self,
            state=SessionState.ACTIVE,
            revision=self.revision + 1,
            pause_reason=None,
        )

    def disable_dynamic_mode(self) -> WorkoutSession:
        if self.state not in (SessionState.ACTIVE, SessionState.PAUSED):
            raise InvalidSessionStateTransition(
                "Dynamic mode can only be disabled during a session"
            )
        if self.configuration.active_mode is not SessionMode.DYNAMIC:
            return self
        configuration = replace(self.configuration, active_mode=SessionMode.NORMAL)
        return replace(self, configuration=configuration, revision=self.revision + 1)

    def finish(
        self,
        *,
        performed_sets: tuple[PerformedSet, ...] = (),
        observation_coverage: ObservationCoverage | None = None,
        feedback: SessionFeedback | None = None,
    ) -> WorkoutSession:
        if self.state not in (SessionState.ACTIVE, SessionState.PAUSED):
            raise InvalidSessionStateTransition("Only an active or paused session can be finished")

        if performed_sets:
            seen_keys: set[tuple[str, int]] = set()
            for performed_set in performed_sets:
                key = (performed_set.exercise_id, performed_set.set_order)
                if key in seen_keys:
                    raise DuplicatePerformedSetError(
                        f"Duplicate performed set for exercise '{performed_set.exercise_id}' "
                        f"set {performed_set.set_order}"
                    )
                seen_keys.add(key)

        new_repetitions = (
            sum(s.repetitions or 0 for s in performed_sets)
            if performed_sets
            else self.confirmed_repetitions
        )

        return replace(
            self,
            state=SessionState.COMPLETED,
            revision=self.revision + 1,
            pause_reason=None,
            confirmed_repetitions=new_repetitions,
            performed_sets=performed_sets if performed_sets else self.performed_sets,
            observation_coverage=(
                observation_coverage
                if observation_coverage is not None
                else self.observation_coverage
            ),
            feedback=feedback if feedback is not None else self.feedback,
        )

    def record_feedback(self, feedback: SessionFeedback) -> WorkoutSession:
        if self.state is not SessionState.COMPLETED:
            raise InvalidSessionStateTransition(
                "Feedback can only be recorded for a completed session"
            )
        return replace(
            self,
            revision=self.revision + 1,
            feedback=feedback,
        )

    def abandon(self) -> WorkoutSession:
        if self.state not in (SessionState.READY, SessionState.ACTIVE, SessionState.PAUSED):
            raise InvalidSessionStateTransition(
                "Cannot abandon a completed or already abandoned session"
            )
        return replace(
            self,
            state=SessionState.ABANDONED,
            revision=self.revision + 1,
            pause_reason=None,
        )
