from datetime import datetime
from uuid import UUID

from kinetiq.modules.goals.infrastructure.models import GoalRevisionRecord
from kinetiq.modules.profiles.infrastructure.models import UserProfileRecord
from kinetiq.modules.progress.application.ports import (
    GoalRecordDTO,
    PerformedSetDTO,
    SessionRecordDTO,
)
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord


class DjangoSessionHistoryLookup:
    def get_sessions_in_range(
        self, *, owner_id: UUID, from_date: datetime, to_date: datetime
    ) -> tuple[SessionRecordDTO, ...]:
        records = (
            WorkoutSessionRecord.objects.filter(
                owner_id=owner_id, updated_at__gte=from_date, updated_at__lte=to_date
            )
            .select_related("routine", "observation_coverage")
            .prefetch_related("performed_sets")
            .order_by("updated_at")
        )

        results: list[SessionRecordDTO] = []
        for record in records:
            coverage = getattr(record, "observation_coverage", None)
            coverage_ratio = coverage.coverage_ratio if coverage is not None else None

            sets: list[PerformedSetDTO] = []
            for pset in record.performed_sets.all():
                sets.append(
                    PerformedSetDTO(
                        exercise_id=str(pset.exercise_id),
                        exercise_name=str(pset.exercise_id).replace("-", " ").title(),
                        set_order=pset.set_order,
                        repetitions=pset.repetitions,
                        duration_seconds=pset.duration_seconds,
                    )
                )

            results.append(
                SessionRecordDTO(
                    session_id=record.id,
                    updated_at=record.updated_at,
                    state=record.state,
                    performed_sets=tuple(sets),
                    observation_coverage_ratio=coverage_ratio,
                )
            )

        return tuple(results)


class DjangoGoalLookup:
    def get_active_goal(self, *, owner_id: UUID) -> GoalRecordDTO | None:
        record = GoalRevisionRecord.objects.filter(owner_id=owner_id).order_by("-revision").first()
        if record is None:
            return None
        return GoalRecordDTO(
            goal_id=record.goal_id,
            description=record.description,
            baseline=record.baseline,
            target=record.target,
            unit=record.unit,
            measure=record.measure,
        )


class DjangoProfileLookup:
    def get_profile_availability(self, *, owner_id: UUID) -> int:
        record = UserProfileRecord.objects.filter(owner_id=owner_id).first()
        if record is None or record.availability_days_per_week is None:
            return 3
        return record.availability_days_per_week
