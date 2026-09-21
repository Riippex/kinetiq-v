from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from kinetiq.modules.goals.application.set_goal import SetGoalCommand, SetGoalUseCase
from kinetiq.modules.goals.infrastructure.repositories import DjangoGoalRepository
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.profiles.application.get_profile import GetProfileUseCase
from kinetiq.modules.profiles.infrastructure.repositories import DjangoProfileRepository
from kinetiq.modules.progress.application.get_progress_summary import GetProgressSummaryUseCase
from kinetiq.modules.progress.domain.entities import EvidenceSource
from kinetiq.modules.progress.infrastructure.repositories import (
    DjangoGoalLookup,
    DjangoProfileLookup,
    DjangoSessionHistoryLookup,
)
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import (
    ObservationCoverageRecord,
    PerformedSetRecord,
    WorkoutSessionRecord,
)


def _use_case() -> GetProgressSummaryUseCase:
    return GetProgressSummaryUseCase(
        session_history_lookup=DjangoSessionHistoryLookup(),
        profile_lookup=DjangoProfileLookup(),
        goal_lookup=DjangoGoalLookup(),
    )


def _user() -> User:
    return User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com", username=f"athlete-{uuid4()}"
    )


def _session(user: User, state: str, days_ago: int) -> WorkoutSessionRecord:
    routine_id = uuid4()
    routine = RoutineRecord.objects.create(
        id=routine_id, routine_id=routine_id, owner=user, title="R", version=1, prescription={}
    )
    session = WorkoutSessionRecord.objects.create(
        id=uuid4(), owner=user, routine=routine, revision=1, state=state, configuration={}
    )
    # updated_at is auto-managed; backdate it with a queryset update.
    WorkoutSessionRecord.objects.filter(id=session.id).update(
        updated_at=datetime.now(UTC) - timedelta(days=days_ago)
    )
    return session


@pytest.mark.django_db
def test_weekly_completed_sessions_goal_tracks_real_completed_sessions() -> None:
    """The real onboarding goal (measure `weekly_completed_sessions`) must
    update its current value and ratio from completed sessions in the
    relevant week -- not stay empty because no exercise has that name."""
    user = _user()
    GetProfileUseCase(DjangoProfileRepository()).execute(user.id)
    SetGoalUseCase(DjangoGoalRepository()).execute(
        owner_id=user.id,
        command=SetGoalCommand(
            description="Build daily movement consistency",
            measure="weekly_completed_sessions",
            baseline=0.0,
            target=3.0,
            unit="sessions/week",
        ),
    )
    now = datetime.now(UTC)
    window = {"from_date": now - timedelta(days=30), "to_date": now}

    before = _use_case().execute(owner_id=user.id, **window)
    assert before.goal_progress is not None
    assert before.goal_progress.current_value == 0.0
    assert before.goal_progress.progress_ratio == 0.0

    _session(user, "COMPLETED", days_ago=2)
    _session(user, "COMPLETED", days_ago=5)
    _session(user, "ABANDONED", days_ago=1)  # never counts
    _session(user, "COMPLETED", days_ago=20)  # outside the relevant week

    after = _use_case().execute(owner_id=user.id, **window)
    goal = after.goal_progress
    assert goal is not None
    assert goal.current_value == 2.0
    assert goal.progress_ratio == 0.67
    assert goal.evidence_source == EvidenceSource.MEASURED

    _session(user, "COMPLETED", days_ago=1)
    reached = _use_case().execute(owner_id=user.id, **window).goal_progress
    assert reached is not None
    assert reached.current_value == 3.0
    assert reached.progress_ratio == 1.0


@pytest.mark.django_db
def test_repetitions_are_never_labeled_measured_from_session_coverage() -> None:
    """A session with near-total observation coverage still cannot say which
    individual sets Vision saw, and performed sets carry no per-set
    provenance -- so its repetitions stay conservatively SELF_REPORTED."""
    user = _user()
    session = _session(user, "COMPLETED", days_ago=1)
    PerformedSetRecord.objects.create(
        session=session, exercise_id="exercise-push-up-v1", set_order=1, repetitions=12
    )
    ObservationCoverageRecord.objects.create(
        session=session, coverage_ratio=0.98, tracked_seconds=590, total_seconds=600
    )
    now = datetime.now(UTC)

    summary = _use_case().execute(
        owner_id=user.id, from_date=now - timedelta(days=7), to_date=now
    )

    projection = summary.performance_projections[0]
    assert projection.exercise_id == "exercise-push-up-v1"
    assert projection.evidence_source == EvidenceSource.SELF_REPORTED
    assert projection.measured_volume == 0
    assert projection.self_reported_volume == 12
