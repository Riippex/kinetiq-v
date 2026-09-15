from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from kinetiq.modules.catalog.domain.entities import RoutineTemplateItem


@dataclass(frozen=True, slots=True)
class RoutineEligibilityCriteria:
    available_equipment: frozenset[str]
    target_duration_minutes: int
    experience_level: str
    target_goal_code: str | None = None
    workout_space: str | None = None

    def __post_init__(self) -> None:
        if self.target_duration_minutes < 1:
            raise ValueError("Target duration minutes must be positive")
        if not self.experience_level.strip():
            raise ValueError("Experience level cannot be empty")


@dataclass(frozen=True, slots=True)
class RoutineProposal:
    proposal_id: UUID
    athlete_id: UUID
    template_code: str
    template_version: int
    title: str
    description: str
    estimated_duration_minutes: int
    items: tuple[RoutineTemplateItem, ...]
    rationale: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.template_code.strip():
            raise ValueError("Template code cannot be empty")
        if self.template_version < 1:
            raise ValueError("Template version must be positive")
        if not self.title.strip():
            raise ValueError("Title cannot be empty")
        if self.estimated_duration_minutes < 1:
            raise ValueError("Estimated duration minutes must be positive")
        if not self.items:
            raise ValueError("Routine proposal must include at least one item")
        if not self.rationale.strip():
            raise ValueError("Proposal rationale cannot be empty")
