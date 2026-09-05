from __future__ import annotations

from dataclasses import dataclass, replace
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


@dataclass(frozen=True, slots=True)
class WorkoutSession:
    id: UUID
    owner_id: UUID
    routine_id: UUID
    routine_version: int
    revision: int
    state: SessionState
    configuration: SessionConfiguration

    def __post_init__(self) -> None:
        if self.routine_version < 1:
            raise ValueError("Routine version must be positive")
        if self.revision < 1:
            raise ValueError("Session revision must be positive")

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
        )

    def start(self) -> WorkoutSession:
        if self.state is not SessionState.READY:
            raise ValueError("Only a ready session can start")
        return replace(self, state=SessionState.ACTIVE, revision=self.revision + 1)

    def disable_dynamic_mode(self) -> WorkoutSession:
        if self.state not in (SessionState.ACTIVE, SessionState.PAUSED):
            raise ValueError("Dynamic mode can only be disabled during a session")
        if self.configuration.active_mode is not SessionMode.DYNAMIC:
            return self
        configuration = replace(self.configuration, active_mode=SessionMode.NORMAL)
        return replace(self, configuration=configuration, revision=self.revision + 1)
