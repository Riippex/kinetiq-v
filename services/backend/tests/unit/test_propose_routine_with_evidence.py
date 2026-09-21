from datetime import UTC, datetime
from uuid import uuid4

from kinetiq.modules.catalog.domain.entities import (
    Exercise,
    ExercisePrescription,
    GoalDefinition,
    PrescriptionType,
    RoutineTemplate,
    RoutineTemplateItem,
)
from kinetiq.modules.goals.domain.entities import GoalRevision
from kinetiq.modules.profiles.domain.entities import ExperienceLevel, UserProfile
from kinetiq.modules.progress.domain.entities import (
    ConsistencyMetric,
    EvidenceSource,
    GoalProgress,
    PerformanceProjection,
    PerformanceTrend,
    ProgressSummary,
)
from kinetiq.modules.routines.application.propose_routine import ProposeRoutineUseCase
from kinetiq.modules.routines.domain.provider import DeterministicCoachingProvider
from kinetiq.modules.workouts.domain.session import CoachingTone


class DummyCatalogRepository:
    def list_exercises(self):
        p = ExercisePrescription(
            prescription_type=PrescriptionType.REPETITIONS,
            default_sets=3,
            default_repetitions=10,
        )
        return (
            Exercise(
                code="ex-squat",
                version=1,
                slug="ex-squat",
                name="Squat",
                category="STRENGTH",
                equipment="NONE",
                prescription=p,
                vision_supported=True,
                vision_exercise_key="squat",
            ),
            Exercise(
                code="ex-pushup",
                version=1,
                slug="ex-pushup",
                name="Pushup",
                category="STRENGTH",
                equipment="NONE",
                prescription=p,
                vision_supported=True,
                vision_exercise_key="pushup",
            ),
        )

    def list_routine_templates(self):
        return (
            RoutineTemplate(
                code="tpl-fullbody-standard",
                version=1,
                title="Full Body Standard",
                description="Standard full body routine",
                target_goal_code="habit-consistency",
                estimated_duration_minutes=15,
                items=(
                    RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),
                    RoutineTemplateItem(exercise_code="ex-pushup", order=2, sets=3, repetitions=10),
                ),
            ),
            RoutineTemplate(
                code="tpl-fullbody-progressive",
                version=1,
                title="Full Body Progressive Overload",
                description="Higher volume progressive routine",
                target_goal_code="habit-consistency",
                estimated_duration_minutes=15,
                items=(
                    RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=4, repetitions=12),
                    RoutineTemplateItem(exercise_code="ex-pushup", order=2, sets=4, repetitions=12),
                ),
            ),
        )

    def list_goal_definitions(self):
        return (
            GoalDefinition(
                code="habit-consistency",
                revision=1,
                name="Habit & Consistency",
                description="Build habit",
                measure="consistency",
                baseline=0.0,
                target=0.8,
                unit="ratio",
            ),
        )


class DummyProfileRepository:
    def get_by_owner_id(self, owner_id):
        return UserProfile(
            owner_id=owner_id,
            display_name="Athlete",
            timezone="UTC",
            experience_level=ExperienceLevel.RETURNING,
            availability_days_per_week=3,
            target_session_minutes=15,
            available_equipment=(),
            workout_space="LIVING_ROOM",
            preferences=(),
            exclusions=(),
            limitations=(),
            coaching_tone=CoachingTone.CALM,
            updated_at=datetime.now(UTC),
        )


class DummyGoalRepository:
    def get_active_goal(self, owner_id):
        return GoalRevision(
            id=uuid4(),
            goal_id=uuid4(),
            owner_id=owner_id,
            revision=1,
            description="Build consistency",
            measure="consistency",
            baseline=0.0,
            target=0.8,
            unit="ratio",
            created_at=datetime.now(UTC),
        )


class DummyProgressSummaryUseCase:
    def __init__(self, summary):
        self.summary = summary

    def execute(self, owner_id, from_date, to_date):
        return self.summary


def test_propose_routine_without_history():
    athlete_id = uuid4()
    use_case = ProposeRoutineUseCase(
        catalog_repo=DummyCatalogRepository(),
        profile_repo=DummyProfileRepository(),
        goal_repo=DummyGoalRepository(),
        coaching_provider=DeterministicCoachingProvider(),
        progress_summary_use_case=None,
    )

    proposal = use_case.execute(athlete_id)

    assert proposal.accepted is False
    assert proposal.template_code == "tpl-fullbody-progressive"
    assert "Selected 'Full Body Progressive Overload'" in proposal.rationale
    assert "consistency" not in proposal.rationale.lower()


def test_propose_routine_with_high_consistency_and_improving_trend():
    athlete_id = uuid4()

    summary = ProgressSummary(
        from_date=datetime.now(UTC),
        to_date=datetime.now(UTC),
        consistency=ConsistencyMetric(
            total_sessions=4,
            planned_sessions=4,
            consistency_ratio=1.0,
            current_streak_days=4,
            completed_count=4,
            abandoned_count=0,
            skipped_count=0,
        ),
        performance_projections=(
            PerformanceProjection(
                exercise_id="ex-squat",
                exercise_name="Squat",
                measured_volume=120,
                self_reported_volume=0,
                estimated_1rm=95.0,
                evidence_source=EvidenceSource.MEASURED,
                trend=PerformanceTrend.IMPROVING,
            ),
        ),
        goal_progress=GoalProgress(
            goal_id=uuid4(),
            description="Build strength",
            baseline=0.0,
            target=100.0,
            current_value=80.0,
            unit="kg",
            progress_ratio=0.8,
            evidence_source=EvidenceSource.MEASURED,
        ),
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=DummyCatalogRepository(),
        profile_repo=DummyProfileRepository(),
        goal_repo=DummyGoalRepository(),
        coaching_provider=DeterministicCoachingProvider(),
        progress_summary_use_case=DummyProgressSummaryUseCase(summary),
    )

    proposal = use_case.execute(athlete_id)

    assert proposal.accepted is False
    assert proposal.template_code == "tpl-fullbody-progressive"
    assert "100% consistency" in proposal.rationale
    assert "4-day streak" in proposal.rationale
    assert "Squat" in proposal.rationale
    assert "80% of your active goal" in proposal.rationale


def test_propose_routine_with_low_consistency():
    athlete_id = uuid4()

    summary = ProgressSummary(
        from_date=datetime.now(UTC),
        to_date=datetime.now(UTC),
        consistency=ConsistencyMetric(
            total_sessions=4,
            planned_sessions=6,
            consistency_ratio=0.33,
            current_streak_days=0,
            completed_count=1,
            abandoned_count=1,
            skipped_count=2,
        ),
        performance_projections=(),
        goal_progress=None,
    )

    use_case = ProposeRoutineUseCase(
        catalog_repo=DummyCatalogRepository(),
        profile_repo=DummyProfileRepository(),
        goal_repo=DummyGoalRepository(),
        coaching_provider=DeterministicCoachingProvider(),
        progress_summary_use_case=DummyProgressSummaryUseCase(summary),
    )

    proposal = use_case.execute(athlete_id)

    assert proposal.accepted is False
    assert "rebuild workout consistency" in proposal.rationale
