from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class PerformedSetDTO:
    exercise_id: str
    exercise_name: str
    set_order: int
    repetitions: int | None
    duration_seconds: int | None


@dataclass(frozen=True)
class SessionRecordDTO:
    session_id: UUID
    updated_at: datetime
    state: str
    performed_sets: tuple[PerformedSetDTO, ...]
    observation_coverage_ratio: float | None


@dataclass(frozen=True)
class GoalRecordDTO:
    goal_id: UUID
    description: str
    baseline: float | None
    target: float | None
    unit: str | None
    measure: str | None = None


class SessionHistoryLookup(Protocol):
    def get_sessions_in_range(
        self, *, owner_id: UUID, from_date: datetime, to_date: datetime
    ) -> tuple[SessionRecordDTO, ...]:
        ...


class GoalLookup(Protocol):
    def get_active_goal(self, *, owner_id: UUID) -> GoalRecordDTO | None:
        ...


class ProfileLookup(Protocol):
    def get_profile_availability(self, *, owner_id: UUID) -> int:
        ...
