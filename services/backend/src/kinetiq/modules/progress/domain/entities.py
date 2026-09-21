from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class EvidenceSource(StrEnum):
    MEASURED = "MEASURED"
    SELF_REPORTED = "SELF_REPORTED"
    ESTIMATED = "ESTIMATED"
    MISSING = "MISSING"


class PerformanceTrend(StrEnum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DECLINING = "DECLINING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ConsistencyMetric:
    total_sessions: int
    planned_sessions: int
    consistency_ratio: float
    current_streak_days: int
    completed_count: int
    abandoned_count: int
    skipped_count: int


@dataclass(frozen=True)
class PerformanceProjection:
    exercise_id: str
    exercise_name: str
    measured_volume: int
    self_reported_volume: int
    estimated_1rm: float | None
    evidence_source: EvidenceSource
    trend: PerformanceTrend


@dataclass(frozen=True)
class GoalProgress:
    goal_id: str | None
    description: str | None
    baseline: float | None
    target: float | None
    current_value: float | None
    unit: str | None
    progress_ratio: float | None
    evidence_source: EvidenceSource


@dataclass(frozen=True)
class ProgressSummary:
    from_date: datetime
    to_date: datetime
    consistency: ConsistencyMetric
    performance_projections: tuple[PerformanceProjection, ...]
    goal_progress: GoalProgress | None = None
