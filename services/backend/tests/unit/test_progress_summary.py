from datetime import UTC, datetime, timedelta
from uuid import uuid4

from kinetiq.modules.progress.application.get_progress_summary import GetProgressSummaryUseCase
from kinetiq.modules.progress.application.ports import (
    GoalRecordDTO,
    PerformedSetDTO,
    SessionRecordDTO,
)
from kinetiq.modules.progress.domain.entities import EvidenceSource


class DummySessionHistoryLookup:
    def __init__(self, sessions=()):
        self.sessions = sessions

    def get_sessions_in_range(self, *, owner_id, from_date, to_date):
        return self.sessions


class DummyProfileLookup:
    def __init__(self, availability=3):
        self.availability = availability

    def get_profile_availability(self, *, owner_id):
        return self.availability


class DummyGoalLookup:
    def __init__(self, goal=None):
        self.goal = goal

    def get_active_goal(self, *, owner_id):
        return self.goal


def test_progress_summary_empty_history():
    owner_id = uuid4()
    now = datetime.now(UTC)
    from_date = now - timedelta(days=7)
    to_date = now

    use_case = GetProgressSummaryUseCase(
        session_history_lookup=DummySessionHistoryLookup(()),
        profile_lookup=DummyProfileLookup(3),
        goal_lookup=DummyGoalLookup(None),
    )

    summary = use_case.execute(owner_id=owner_id, from_date=from_date, to_date=to_date)

    assert summary.consistency.total_sessions == 0
    assert summary.consistency.completed_count == 0
    assert summary.consistency.planned_sessions >= 3
    assert summary.consistency.consistency_ratio == 0.0
    assert len(summary.performance_projections) == 0
    assert summary.goal_progress is None


def test_progress_summary_with_measured_and_self_reported_evidence():
    owner_id = uuid4()
    now = datetime.now(UTC)
    from_date = now - timedelta(days=7)
    to_date = now

    sess1 = SessionRecordDTO(
        session_id=uuid4(),
        updated_at=now - timedelta(days=2),
        state="COMPLETED",
        performed_sets=(
            PerformedSetDTO("exercise-squat", "Squat", 1, 10, None),
            PerformedSetDTO("exercise-squat", "Squat", 2, 12, None),
        ),
        observation_coverage_ratio=0.9,  # whole-session coverage never upgrades sets to MEASURED
    )

    sess2 = SessionRecordDTO(
        session_id=uuid4(),
        updated_at=now - timedelta(days=1),
        state="COMPLETED",
        performed_sets=(PerformedSetDTO("exercise-pushup", "Pushup", 1, 15, None),),
        observation_coverage_ratio=None,  # No Vision tracking -> self-reported
    )

    goal = GoalRecordDTO(
        goal_id=uuid4(),
        description="Build leg volume",
        measure="exercise-squat",
        baseline=10.0,
        target=30.0,
        unit="reps",
    )

    use_case = GetProgressSummaryUseCase(
        session_history_lookup=DummySessionHistoryLookup((sess1, sess2)),
        profile_lookup=DummyProfileLookup(3),
        goal_lookup=DummyGoalLookup(goal),
    )

    summary = use_case.execute(owner_id=owner_id, from_date=from_date, to_date=to_date)

    assert summary.consistency.total_sessions == 2
    assert summary.consistency.completed_count == 2
    assert summary.consistency.consistency_ratio > 0.0

    projections = {p.exercise_id: p for p in summary.performance_projections}
    assert "exercise-squat" in projections
    assert projections["exercise-squat"].evidence_source == EvidenceSource.SELF_REPORTED
    assert projections["exercise-squat"].measured_volume == 0
    assert projections["exercise-squat"].self_reported_volume == 22
    assert projections["exercise-squat"].estimated_1rm is None

    assert "exercise-pushup" in projections
    assert projections["exercise-pushup"].evidence_source == EvidenceSource.SELF_REPORTED
    assert projections["exercise-pushup"].self_reported_volume == 15

    assert summary.goal_progress is not None
    assert summary.goal_progress.current_value == 22.0
    assert summary.goal_progress.progress_ratio == 0.6
    assert summary.goal_progress.evidence_source == EvidenceSource.SELF_REPORTED


def test_progress_summary_goal_without_matching_measurements_reports_missing_evidence():
    owner_id = uuid4()
    now = datetime.now(UTC)
    from_date = now - timedelta(days=7)
    to_date = now

    sess1 = SessionRecordDTO(
        session_id=uuid4(),
        updated_at=now - timedelta(days=1),
        state="COMPLETED",
        performed_sets=(PerformedSetDTO("exercise-squat", "Squat", 1, 10, None),),
        observation_coverage_ratio=0.9,
    )

    # Goal tracks an exercise that has never actually been performed.
    goal = GoalRecordDTO(
        goal_id=uuid4(),
        description="Bench press volume",
        measure="exercise-bench-press",
        baseline=10.0,
        target=30.0,
        unit="reps",
    )

    use_case = GetProgressSummaryUseCase(
        session_history_lookup=DummySessionHistoryLookup((sess1,)),
        profile_lookup=DummyProfileLookup(3),
        goal_lookup=DummyGoalLookup(goal),
    )

    summary = use_case.execute(owner_id=owner_id, from_date=from_date, to_date=to_date)

    assert summary.goal_progress is not None
    assert summary.goal_progress.current_value is None
    assert summary.goal_progress.progress_ratio is None
    assert summary.goal_progress.evidence_source == EvidenceSource.MISSING


def test_progress_summary_trend_requires_at_least_two_sessions():
    owner_id = uuid4()
    now = datetime.now(UTC)
    from_date = now - timedelta(days=7)
    to_date = now

    sess1 = SessionRecordDTO(
        session_id=uuid4(),
        updated_at=now - timedelta(days=1),
        state="COMPLETED",
        performed_sets=(PerformedSetDTO("exercise-squat", "Squat", 1, 10, None),),
        observation_coverage_ratio=0.9,
    )

    use_case = GetProgressSummaryUseCase(
        session_history_lookup=DummySessionHistoryLookup((sess1,)),
        profile_lookup=DummyProfileLookup(3),
        goal_lookup=DummyGoalLookup(None),
    )

    summary = use_case.execute(owner_id=owner_id, from_date=from_date, to_date=to_date)

    projections = {p.exercise_id: p for p in summary.performance_projections}
    assert projections["exercise-squat"].trend.value == "INSUFFICIENT_DATA"


def test_progress_summary_never_infers_per_set_measured_from_session_coverage():
    """Whole-session coverage cannot say which sets Vision saw, and performed
    sets carry no per-set provenance, so reps stay conservatively
    SELF_REPORTED whether coverage is tiny or near-total."""
    owner_id = uuid4()
    now = datetime.now(UTC)

    def _session(days_ago: int, ratio: float | None) -> SessionRecordDTO:
        return SessionRecordDTO(
            session_id=uuid4(),
            updated_at=now - timedelta(days=days_ago),
            state="COMPLETED",
            performed_sets=(PerformedSetDTO("exercise-squat", "Squat", 1, 10, None),),
            observation_coverage_ratio=ratio,
        )

    for ratio in (None, 0.1, 0.99):
        use_case = GetProgressSummaryUseCase(
            session_history_lookup=DummySessionHistoryLookup((_session(1, ratio),)),
            profile_lookup=DummyProfileLookup(3),
            goal_lookup=DummyGoalLookup(None),
        )
        summary = use_case.execute(
            owner_id=owner_id, from_date=now - timedelta(days=7), to_date=now
        )
        projection = summary.performance_projections[0]
        assert projection.evidence_source == EvidenceSource.SELF_REPORTED
        assert projection.measured_volume == 0
        assert projection.self_reported_volume == 10


def test_progress_summary_weekly_completed_sessions_goal_counts_completed_sessions():
    owner_id = uuid4()
    now = datetime.now(UTC)

    def _session(days_ago: int, state: str) -> SessionRecordDTO:
        return SessionRecordDTO(
            session_id=uuid4(),
            updated_at=now - timedelta(days=days_ago),
            state=state,
            performed_sets=(),
            observation_coverage_ratio=None,
        )

    sessions = (
        _session(20, "COMPLETED"),  # outside the trailing week
        _session(5, "COMPLETED"),
        _session(3, "ABANDONED"),  # not completed
        _session(2, "COMPLETED"),
    )
    goal = GoalRecordDTO(
        goal_id=uuid4(),
        description="Train 3 times a week",
        measure="weekly_completed_sessions",
        baseline=0.0,
        target=3.0,
        unit="sessions/week",
    )
    use_case = GetProgressSummaryUseCase(
        session_history_lookup=DummySessionHistoryLookup(sessions),
        profile_lookup=DummyProfileLookup(3),
        goal_lookup=DummyGoalLookup(goal),
    )

    summary = use_case.execute(owner_id=owner_id, from_date=now - timedelta(days=30), to_date=now)

    assert summary.goal_progress is not None
    assert summary.goal_progress.current_value == 2.0
    assert summary.goal_progress.progress_ratio == 0.67
    assert summary.goal_progress.evidence_source == EvidenceSource.MEASURED


def test_progress_summary_weekly_completed_sessions_goal_without_sessions_is_zero_progress():
    now = datetime.now(UTC)
    goal = GoalRecordDTO(
        goal_id=uuid4(),
        description="Train 3 times a week",
        measure="weekly_completed_sessions",
        baseline=0.0,
        target=3.0,
        unit="sessions/week",
    )
    use_case = GetProgressSummaryUseCase(
        session_history_lookup=DummySessionHistoryLookup(()),
        profile_lookup=DummyProfileLookup(3),
        goal_lookup=DummyGoalLookup(goal),
    )

    summary = use_case.execute(owner_id=uuid4(), from_date=now - timedelta(days=30), to_date=now)

    assert summary.goal_progress is not None
    assert summary.goal_progress.current_value == 0.0
    assert summary.goal_progress.progress_ratio == 0.0


class RangeAwareSessionHistoryLookup:
    def __init__(self, sessions):
        self.sessions = sessions

    def get_sessions_in_range(self, *, owner_id, from_date, to_date):
        return tuple(s for s in self.sessions if from_date <= s.updated_at <= to_date)


def test_progress_summary_weekly_goal_is_not_understated_by_a_short_range():
    """Querying fewer than seven days must still count the whole trailing
    week's completed sessions for the weekly goal."""
    now = datetime.now(UTC)
    sessions = tuple(
        SessionRecordDTO(
            session_id=uuid4(),
            updated_at=now - timedelta(days=days_ago),
            state="COMPLETED",
            performed_sets=(),
            observation_coverage_ratio=None,
        )
        for days_ago in (0.5, 3, 6)
    )
    goal = GoalRecordDTO(
        goal_id=uuid4(),
        description="Train 3 times a week",
        measure="weekly_completed_sessions",
        baseline=0.0,
        target=3.0,
        unit="sessions/week",
    )
    use_case = GetProgressSummaryUseCase(
        session_history_lookup=RangeAwareSessionHistoryLookup(sessions),
        profile_lookup=DummyProfileLookup(3),
        goal_lookup=DummyGoalLookup(goal),
    )

    summary = use_case.execute(owner_id=uuid4(), from_date=now - timedelta(days=1), to_date=now)

    assert summary.consistency.completed_count == 1  # only the requested range
    assert summary.goal_progress is not None
    assert summary.goal_progress.current_value == 3.0
    assert summary.goal_progress.progress_ratio == 1.0
