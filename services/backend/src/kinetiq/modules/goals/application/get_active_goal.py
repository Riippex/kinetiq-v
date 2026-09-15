from __future__ import annotations

from uuid import UUID

from kinetiq.modules.goals.application.ports import GoalRepository
from kinetiq.modules.goals.domain.entities import GoalRevision


class GetActiveGoalUseCase:
    def __init__(self, goal_repo: GoalRepository) -> None:
        self._repo = goal_repo

    def execute(self, owner_id: UUID) -> GoalRevision | None:
        return self._repo.get_active_goal(owner_id)
