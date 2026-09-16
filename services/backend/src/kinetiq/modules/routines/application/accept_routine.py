from __future__ import annotations

from uuid import UUID

from kinetiq.modules.routines.application.ports import RoutineRepository
from kinetiq.modules.routines.domain.entities import Routine
from kinetiq.modules.routines.domain.errors import RoutineNotFoundError


class AcceptRoutineUseCase:
    """Marks an exact immutable routine revision as accepted by the athlete."""

    def __init__(self, routine_repo: RoutineRepository) -> None:
        self._routine_repo = routine_repo

    def execute(self, athlete_id: UUID, routine_id: UUID, version: int) -> Routine:
        routine = self._routine_repo.get_by_routine_id(
            owner_id=athlete_id,
            routine_id=routine_id,
            version=version,
        )

        if routine is None or routine.owner_id != athlete_id:
            raise RoutineNotFoundError(
                f"Routine {routine_id} revision {version} not found for athlete {athlete_id}"
            )

        accepted_routine = Routine(
            id=routine.id,
            routine_id=routine.routine_id,
            owner_id=routine.owner_id,
            version=routine.version,
            title=routine.title,
            rationale=routine.rationale,
            prescription=routine.prescription,
            accepted=True,
            created_at=routine.created_at,
        )

        self._routine_repo.save(accepted_routine)
        return accepted_routine
