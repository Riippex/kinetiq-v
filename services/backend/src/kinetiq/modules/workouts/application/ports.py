from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from kinetiq.modules.workouts.domain import WorkoutSession


@dataclass(frozen=True, slots=True)
class AcceptedRoutine:
    record_id: UUID
    routine_id: UUID
    version: int


class SessionPreparationRepository(Protocol):
    def find_accepted_routine(
        self, *, owner_id: UUID, routine_id: UUID, version: int
    ) -> AcceptedRoutine | None: ...

    def save_idempotently(
        self,
        *,
        session: WorkoutSession,
        routine: AcceptedRoutine,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> WorkoutSession: ...


@dataclass(frozen=True, slots=True)
class TransitionPrecondition:
    """Result of validating a lifecycle command against the persisted
    session before any external (e.g. Vision) side effect runs.

    `already_applied=True` means an idempotency receipt for this exact
    (operation, idempotency_key) already exists and `session` is its
    resolved result -- the caller must return it directly and must not
    call out to Vision again, or a retry would leak a duplicate Vision
    mutation (e.g. a second analysis) on every replay.

    `already_applied=False` means no receipt exists and `session.revision`
    matched `expected_revision` at the time of the check -- the caller may
    proceed to call Vision, then finish with `apply_transition`. This is a
    check-then-act validation, not a lock held across the network call: a
    concurrent write could still land between this check and the final
    `apply_transition`, which re-validates both conditions again before
    persisting. It closes the common case (a stale revision known upfront)
    rather than guaranteeing perfect cross-system atomicity, which would
    require holding a PostgreSQL row lock open across an external Vision
    HTTP call.
    """

    already_applied: bool
    session: WorkoutSession


class SessionLifecycleRepository(Protocol):
    def get_session(self, *, owner_id: UUID, session_id: UUID) -> WorkoutSession | None: ...

    def check_transition_precondition(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_revision: int,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> TransitionPrecondition: ...

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
    ) -> WorkoutSession: ...

    def acquire_vision_lease(
        self, *, owner_id: UUID, session_id: UUID, ttl_seconds: int
    ) -> str | None: ...

    def release_vision_lease(
        self, *, owner_id: UUID, session_id: UUID, lease_token: str
    ) -> None: ...

    def list_sessions_polling_vision(self) -> tuple[WorkoutSession, ...]: ...

    def acquire_vision_poll_lease(
        self, *, owner_id: UUID, session_id: UUID, ttl_seconds: int
    ) -> str | None: ...

    def release_vision_poll_lease(
        self, *, owner_id: UUID, session_id: UUID, lease_token: str
    ) -> None: ...

    def advance_vision_observation_cursor(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_previous_cursor: str | None,
        new_cursor: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class AcceptedRoutineItem:
    exercise_id: str
    repetitions: int | None
    duration_seconds: int | None


class RoutineItemLookup(Protocol):
    """Read-only boundary onto the routines module's accepted-routine
    prescription, scoped to exactly what session-finish validation needs.
    """

    def get_accepted_routine_items(
        self, *, owner_id: UUID, routine_id: UUID, version: int
    ) -> tuple[AcceptedRoutineItem, ...] | None: ...


class UserProfileLookup(Protocol):
    """Read-only boundary onto the profiles module, scoped to retrieving
    user exclusions for challenge policy evaluation.
    """

    def get_user_exclusions(self, *, owner_id: UUID) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class VisionCandidateInfo:
    candidate_id: str
    confidence: float


@dataclass(frozen=True, slots=True)
class VisionAnalysisHandle:
    analysis_id: str
    epoch: int
    state: str


@dataclass(frozen=True, slots=True)
class VisionTargetConfirmation:
    target_person_id: str
    epoch: int
    state: str


class UnknownVisionCandidateError(ValueError):
    """Raised when a client attempts to confirm a candidate_id that is not
    among the currently detected candidates for the active Vision analysis
    -- i.e. an arbitrary string rather than a real, Vision-detected person."""

    def __init__(self, candidate_id: str, analysis_id: str) -> None:
        super().__init__(
            f"Candidate '{candidate_id}' is not among the detected candidates "
            f"for Vision analysis '{analysis_id}'"
        )
        self.candidate_id = candidate_id
        self.analysis_id = analysis_id


class VisionSessionAnalysisPort(Protocol):
    """Read/write boundary onto the Vision service's canonical
    `/v1/analyses` REST contract, scoped to exactly what session target
    confirmation needs: create-or-reuse an analysis context for the
    session's capture device, list its currently detected candidates, and
    confirm one of them as the session's target.
    """

    def create_analysis(
        self,
        *,
        session_id: UUID,
        source_id: str,
        exercise_key: str,
        exercise_version: int,
        idempotency_key: str,
    ) -> VisionAnalysisHandle: ...

    def list_candidates(self, *, analysis_id: str) -> tuple[VisionCandidateInfo, ...]: ...

    def select_target(
        self,
        *,
        analysis_id: str,
        candidate_id: str,
        expected_epoch: int,
        idempotency_key: str,
    ) -> VisionTargetConfirmation: ...


VISIBILITY_STATUSES = frozenset({"VISIBLE", "PARTIALLY_VISIBLE", "NOT_VISIBLE"})
MAX_PLAUSIBLE_REPETITIONS = 10_000
MAX_PLAUSIBLE_DURATION_SECONDS = 86_400  # 24h: generous upper bound, not a real session length


@dataclass(frozen=True, slots=True)
class TransientSessionUpdate:
    session_id: UUID
    active_exercise_id: str | None = None
    current_repetitions: int | None = None
    current_duration_seconds: int | None = None
    pose_confidence: float | None = None
    visibility_status: str = "VISIBLE"
    timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.current_repetitions is not None and not (
            0 <= self.current_repetitions <= MAX_PLAUSIBLE_REPETITIONS
        ):
            raise ValueError(
                f"current_repetitions must be between 0 and {MAX_PLAUSIBLE_REPETITIONS}"
            )
        if self.current_duration_seconds is not None and not (
            0 <= self.current_duration_seconds <= MAX_PLAUSIBLE_DURATION_SECONDS
        ):
            raise ValueError(
                f"current_duration_seconds must be between 0 and {MAX_PLAUSIBLE_DURATION_SECONDS}"
            )
        if self.pose_confidence is not None and not (0.0 <= self.pose_confidence <= 1.0):
            raise ValueError("pose_confidence must be between 0.0 and 1.0")
        if self.visibility_status not in VISIBILITY_STATUSES:
            raise ValueError(
                f"visibility_status must be one of {sorted(VISIBILITY_STATUSES)}, "
                f"got {self.visibility_status!r}"
            )


class SessionTransientStore(Protocol):
    """Port for writing and reading transient session updates backed by Redis,
    guaranteeing graceful fallbacks when Redis is unpopulated or offline.
    """

    def publish_transient_update(self, update: TransientSessionUpdate) -> bool: ...

    def get_transient_update(self, session_id: UUID) -> TransientSessionUpdate | None: ...


@dataclass(frozen=True, slots=True)
class VisionObservationInfo:
    """Flattened read model of a single Vision observation, scoped to
    exactly what observation ingestion needs to derive a
    TransientSessionUpdate, reject stale/duplicate observations, and -- the
    trust-boundary check -- reject one that does not belong to this
    session/target at all. Deliberately decoupled from the Vision adapter's
    own DTOs (mirrors the same pattern as VisionCandidateInfo/
    VisionAnalysisHandle above): an infrastructure adapter translates into
    this shape."""

    session_id: str
    target_person_id: str
    exercise_key: str
    epoch: int
    sequence: int
    tracking_state: str
    visibility_state: str
    reason_code: str
    confirmed_repetitions: int
    hold_elapsed_seconds: float | None = None
    hold_confidence: float | None = None
    last_repetition_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class VisionObservationsPage:
    observations: tuple[VisionObservationInfo, ...]
    next_cursor: str | None
    has_more: bool


class VisionObservationSourcePort(Protocol):
    """Read boundary onto Vision's `/v1/analyses/{id}/observations` cursor
    feed, scoped to exactly what observation ingestion needs."""

    def poll_observations(
        self, *, analysis_id: str, after_cursor: str | None, limit: int
    ) -> VisionObservationsPage: ...


class LatestSessionReader(Protocol):
    """Owner-scoped read of the athlete's most recent workout session."""

    def get_latest_session(self, *, owner_id: UUID) -> WorkoutSession | None: ...
