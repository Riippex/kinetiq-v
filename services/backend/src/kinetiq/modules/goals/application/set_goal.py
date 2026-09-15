from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from kinetiq.modules.goals.application.ports import GoalRepository
from kinetiq.modules.goals.domain.entities import GoalRevision


@dataclass(frozen=True, slots=True)
class SetGoalCommand:
    description: str
    goal_id: UUID | None = None
    measure: str | None = None
    baseline: float | None = None
    target: float | None = None
    unit: str | None = None


class SetGoalUseCase:
    def __init__(self, goal_repo: GoalRepository) -> None:
        self._repo = goal_repo

    def execute(self, owner_id: UUID, command: SetGoalCommand) -> GoalRevision:
        existing = self._repo.get_active_goal(owner_id)

        if existing is not None:
            # If user already has a goal, preserve the logical goal_id unless explicitly changing
            goal_id = command.goal_id or existing.goal_id
            revision_number = existing.revision + 1
        else:
            goal_id = command.goal_id or uuid4()
            revision_number = 1

        new_revision = GoalRevision(
            id=uuid4(),
            owner_id=owner_id,
            goal_id=goal_id,
            revision=revision_number,
            description=command.description,
            measure=command.measure,
            baseline=command.baseline,
            target=command.target,
            unit=command.unit,
            created_at=datetime.now(UTC),
        )

        self._repo.save_revision(new_revision)
        return new_revision
