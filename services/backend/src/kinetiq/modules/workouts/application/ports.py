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


class SessionLifecycleRepository(Protocol):
    def get_session(
        self, *, owner_id: UUID, session_id: UUID
    ) -> WorkoutSession | None: ...

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


@dataclass(frozen=True, slots=True)
class TransientSessionUpdate:
    session_id: UUID
    active_exercise_id: str | None = None
    current_repetitions: int | None = None
    current_duration_seconds: int | None = None
    pose_confidence: float | None = None
    visibility_status: str = "VISIBLE"
    timestamp: str | None = None


class SessionTransientStore(Protocol):
    """Port for writing and reading transient session updates backed by Redis,
    guaranteeing graceful fallbacks when Redis is unpopulated or offline.
    """

    def publish_transient_update(self, update: TransientSessionUpdate) -> bool: ...

    def get_transient_update(self, session_id: UUID) -> TransientSessionUpdate | None: ...



