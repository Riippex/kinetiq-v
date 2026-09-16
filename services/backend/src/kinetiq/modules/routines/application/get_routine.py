from __future__ import annotations

from uuid import UUID

from kinetiq.modules.routines.application.ports import RoutineRepository
from kinetiq.modules.routines.domain.entities import Routine


class GetCurrentRoutineUseCase:
    """Retrieves the athlete's current active accepted routine, falling back to latest proposal."""

    def __init__(self, routine_repo: RoutineRepository) -> None:
        self._routine_repo = routine_repo

    def execute(self, athlete_id: UUID) -> Routine | None:
        # Prefer active accepted routine
        accepted = self._routine_repo.get_active_accepted(athlete_id)
        if accepted is not None:
            return accepted
        # Fall back to latest proposal
        return self._routine_repo.get_latest_for_owner(athlete_id)


class GetRoutineVersionUseCase:
    """Retrieves a specific routine version owned by the athlete."""

    def __init__(self, routine_repo: RoutineRepository) -> None:
        self._routine_repo = routine_repo

    def execute(self, athlete_id: UUID, routine_id: UUID, version: int) -> Routine | None:
        return self._routine_repo.get_by_routine_id(athlete_id, routine_id, version)
