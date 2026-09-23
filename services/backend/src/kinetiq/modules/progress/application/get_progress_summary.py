from datetime import datetime, timedelta
from uuid import UUID

from kinetiq.modules.progress.application.ports import (
    GoalLookup,
    ProfileLookup,
    SessionHistoryLookup,
)
from kinetiq.modules.progress.domain.entities import (
    ConsistencyMetric,
    EvidenceSource,
    GoalProgress,
    PerformanceProjection,
    PerformanceTrend,
    ProgressSummary,
)

# Goal measure produced by onboarding: completed sessions in the relevant week.
WEEKLY_COMPLETED_SESSIONS_MEASURE = "weekly_completed_sessions"
_WEEK_DAYS = 7

# A relative volume change smaller than this is noise, not a trend.
_TREND_CHANGE_THRESHOLD = 0.1


def _compute_trend(session_volumes: list[int]) -> PerformanceTrend:
    """Compare chronological first-half vs. second-half average volume.

    Requires at least two data points -- a single session's volume has no
    "before" to compare against, so it is insufficient data, not STABLE.
    """
    if len(session_volumes) < 2:
        return PerformanceTrend.INSUFFICIENT_DATA

    midpoint = len(session_volumes) // 2
    first_half = session_volumes[:midpoint]
    second_half = session_volumes[midpoint:]
    first_avg = sum(first_half) / len(first_half)
    second_avg = sum(second_half) / len(second_half)

    if first_avg == 0:
        return PerformanceTrend.IMPROVING if second_avg > 0 else PerformanceTrend.INSUFFICIENT_DATA

    relative_change = (second_avg - first_avg) / first_avg
    if relative_change >= _TREND_CHANGE_THRESHOLD:
        return PerformanceTrend.IMPROVING
    if relative_change <= -_TREND_CHANGE_THRESHOLD:
        return PerformanceTrend.DECLINING
    return PerformanceTrend.STABLE


class GetProgressSummaryUseCase:
    def __init__(
        self,
        session_history_lookup: SessionHistoryLookup,
        profile_lookup: ProfileLookup,
        goal_lookup: GoalLookup,
    ) -> None:
        self._session_history_lookup = session_history_lookup
        self._profile_lookup = profile_lookup
        self._goal_lookup = goal_lookup

    def execute(self, *, owner_id: UUID, from_date: datetime, to_date: datetime) -> ProgressSummary:
        sessions = self._session_history_lookup.get_sessions_in_range(
            owner_id=owner_id, from_date=from_date, to_date=to_date
        )
        availability_days = self._profile_lookup.get_profile_availability(owner_id=owner_id)
        active_goal = self._goal_lookup.get_active_goal(owner_id=owner_id)

        # 1. Consistency calculation
        days_span = max(1, (to_date.date() - from_date.date()).days + 1)
        weeks_span = max(1.0, days_span / 7.0)
        planned_sessions = int(round(weeks_span * availability_days))

        completed_sessions = [s for s in sessions if s.state == "COMPLETED"]
        abandoned_sessions = [s for s in sessions if s.state == "ABANDONED"]
        completed_count = len(completed_sessions)
        abandoned_count = len(abandoned_sessions)
        skipped_count = max(0, planned_sessions - completed_count)

        consistency_ratio = (
            min(1.0, round(completed_count / planned_sessions, 2)) if planned_sessions > 0 else 0.0
        )

        # Calculate streak days ending at to_date
        streak_days = 0
        completed_dates = {s.updated_at.date() for s in completed_sessions}
        check_date = to_date.date()
        while check_date in completed_dates or (check_date == to_date.date() and streak_days == 0):
            if check_date in completed_dates:
                streak_days += 1
            elif check_date != to_date.date():
                break
            check_date -= timedelta(days=1)

        consistency = ConsistencyMetric(
            total_sessions=len(sessions),
            planned_sessions=planned_sessions,
            consistency_ratio=consistency_ratio,
            current_streak_days=streak_days,
            completed_count=completed_count,
            abandoned_count=abandoned_count,
            skipped_count=skipped_count,
        )

        # 2. Performance Projections by Exercise
        exercise_names: dict[str, str] = {}
        exercise_session_volumes: dict[str, list[int]] = {}
        exercise_self_reported_vol: dict[str, int] = {}

        # `sessions` is already ordered chronologically (ascending updated_at),
        # so appending one entry per session per exercise below preserves that
        # order for the trend calculation.
        # Repetitions are conservatively labeled SELF_REPORTED: performed sets
        # are submitted by the client at finish time and carry no per-set
        # provenance, while observation coverage is a whole-session average
        # that cannot say which sets Vision actually saw. Inferring per-set
        # MEASURED evidence from it would overstate what is known.
        for s in sessions:
            session_reps_by_exercise: dict[str, int] = {}
            for pset in s.performed_sets:
                ex_id = pset.exercise_id
                exercise_names.setdefault(ex_id, pset.exercise_name)
                reps = pset.repetitions or 0
                session_reps_by_exercise[ex_id] = session_reps_by_exercise.get(ex_id, 0) + reps
                exercise_self_reported_vol[ex_id] = exercise_self_reported_vol.get(ex_id, 0) + reps

            for ex_id, reps in session_reps_by_exercise.items():
                exercise_session_volumes.setdefault(ex_id, []).append(reps)

        projections: list[PerformanceProjection] = []
        for ex_id, exercise_name in exercise_names.items():
            measured_vol = 0
            self_reported_vol = exercise_self_reported_vol.get(ex_id, 0)

            if self_reported_vol > 0:
                evidence = EvidenceSource.SELF_REPORTED
            else:
                evidence = EvidenceSource.MISSING

            # No load/weight measurement exists anywhere in this data model
            # (PerformedSetDTO only carries reps and duration), so a
            # reps-only "1RM" would be numerology rather than an estimate.
            estimated_1rm = None

            trend = _compute_trend(exercise_session_volumes[ex_id])

            projections.append(
                PerformanceProjection(
                    exercise_id=ex_id,
                    exercise_name=exercise_name,
                    measured_volume=measured_vol,
                    self_reported_volume=self_reported_vol,
                    estimated_1rm=estimated_1rm,
                    evidence_source=evidence,
                    trend=trend,
                )
            )

        # 3. Goal Progress
        goal_progress: GoalProgress | None = None
        if active_goal:
            b_line = active_goal.baseline
            target_val = active_goal.target

            current_val: float | None = None
            goal_evidence = EvidenceSource.MISSING

            if active_goal.measure == WEEKLY_COMPLETED_SESSIONS_MEASURE:
                # Completed-session state is the system of record, not a
                # Vision measurement or a self-report of reps, so a count of
                # COMPLETED sessions in the relevant (trailing) week is
                # genuine MEASURED evidence for this goal.
                week_start = to_date - timedelta(days=_WEEK_DAYS)
                # The requested range may be shorter than a week; load the
                # full trailing week separately so the count is never
                # understated by the caller's chosen window.
                weekly_sessions = (
                    sessions
                    if from_date <= week_start
                    else self._session_history_lookup.get_sessions_in_range(
                        owner_id=owner_id, from_date=week_start, to_date=to_date
                    )
                )
                current_val = float(
                    sum(
                        1
                        for s in weekly_sessions
                        if s.state == "COMPLETED" and week_start <= s.updated_at <= to_date
                    )
                )
                goal_evidence = EvidenceSource.MEASURED
            else:
                # Only a projection for the exercise this goal actually
                # tracks (goal.measure) counts as evidence of progress --
                # volume on an unrelated exercise says nothing about it.
                projections_by_exercise = {p.exercise_id: p for p in projections}
                matched = (
                    projections_by_exercise.get(active_goal.measure)
                    if active_goal.measure
                    else None
                )
                if matched is not None:
                    if matched.evidence_source == EvidenceSource.MEASURED:
                        current_val = float(matched.measured_volume)
                        goal_evidence = EvidenceSource.MEASURED
                    elif matched.evidence_source == EvidenceSource.SELF_REPORTED:
                        current_val = float(matched.self_reported_volume)
                        goal_evidence = EvidenceSource.SELF_REPORTED

            ratio = None
            if (
                b_line is not None
                and target_val is not None
                and target_val != b_line
                and current_val is not None
            ):
                raw_ratio = (current_val - b_line) / (target_val - b_line)
                ratio = min(1.0, max(0.0, round(raw_ratio, 2)))

            goal_progress = GoalProgress(
                goal_id=str(active_goal.goal_id),
                description=active_goal.description,
                baseline=b_line,
                target=target_val,
                current_value=current_val,
                unit=active_goal.unit,
                progress_ratio=ratio,
                evidence_source=goal_evidence,
            )

        return ProgressSummary(
            from_date=from_date,
            to_date=to_date,
            consistency=consistency,
            performance_projections=tuple(projections),
            goal_progress=goal_progress,
        )
