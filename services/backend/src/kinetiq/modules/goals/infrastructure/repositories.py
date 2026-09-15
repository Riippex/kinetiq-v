from __future__ import annotations

from uuid import UUID

from kinetiq.modules.goals.application.ports import GoalRepository
from kinetiq.modules.goals.domain.entities import GoalRevision
from kinetiq.modules.goals.infrastructure.models import GoalRevisionRecord


class DjangoGoalRepository(GoalRepository):
    def get_active_goal(self, owner_id: UUID) -> GoalRevision | None:
        record = (
            GoalRevisionRecord.objects.filter(owner_id=owner_id)
            .order_by("-revision", "-created_at")
            .first()
        )
        if record is None:
            return None
        return self._to_entity(record)

    def list_revisions(self, owner_id: UUID) -> list[GoalRevision]:
        records = GoalRevisionRecord.objects.filter(owner_id=owner_id).order_by(
            "-revision", "-created_at"
        )
        return [self._to_entity(record) for record in records]

    def save_revision(self, revision: GoalRevision) -> None:
        GoalRevisionRecord.objects.create(
            id=revision.id,
            owner_id=revision.owner_id,
            goal_id=revision.goal_id,
            revision=revision.revision,
            description=revision.description,
            measure=revision.measure,
            baseline=revision.baseline,
            target=revision.target,
            unit=revision.unit,
        )

    @staticmethod
    def _to_entity(record: GoalRevisionRecord) -> GoalRevision:
        return GoalRevision(
            id=record.id,
            owner_id=record.owner_id,
            goal_id=record.goal_id,
            revision=record.revision,
            description=record.description,
            measure=record.measure,
            baseline=record.baseline,
            target=record.target,
            unit=record.unit,
            created_at=record.created_at,
        )
