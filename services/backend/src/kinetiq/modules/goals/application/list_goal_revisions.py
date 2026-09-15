from __future__ import annotations

from uuid import UUID

from kinetiq.modules.goals.application.ports import GoalRepository
from kinetiq.modules.goals.domain.entities import GoalRevision


class ListGoalRevisionsUseCase:
    def __init__(self, goal_repo: GoalRepository) -> None:
        self._repo = goal_repo

    def execute(self, owner_id: UUID) -> list[GoalRevision]:
        return self._repo.list_revisions(owner_id)
