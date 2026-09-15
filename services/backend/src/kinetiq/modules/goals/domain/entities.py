from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GoalRevision:
    id: UUID
    owner_id: UUID
    goal_id: UUID
    revision: int
    description: str
    measure: str | None
    baseline: float | None
    target: float | None
    unit: str | None
    created_at: datetime

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("Goal revision must be a positive integer")
        if not self.description.strip():
            raise ValueError("Goal description cannot be empty")
        if self.baseline is not None and self.target is not None:
            if self.target <= self.baseline:
                raise ValueError("Goal target must be strictly greater than baseline")
