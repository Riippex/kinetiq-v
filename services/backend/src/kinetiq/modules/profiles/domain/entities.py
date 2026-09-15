from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from kinetiq.modules.workouts.domain.session import CoachingTone


class ExperienceLevel(StrEnum):
    STARTING = "STARTING"
    RETURNING = "RETURNING"
    REGULAR = "REGULAR"


@dataclass(frozen=True, slots=True)
class UserProfile:
    owner_id: UUID
    display_name: str
    timezone: str
    experience_level: ExperienceLevel
    availability_days_per_week: int
    target_session_minutes: int
    available_equipment: tuple[str, ...]
    workout_space: str
    preferences: tuple[str, ...]
    exclusions: tuple[str, ...]
    limitations: tuple[str, ...]
    coaching_tone: CoachingTone
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("Display name cannot be empty")
        if not self.timezone.strip():
            raise ValueError("Timezone cannot be empty")
        if not 1 <= self.availability_days_per_week <= 7:
            raise ValueError("Availability must be between 1 and 7 days per week")
        if not 5 <= self.target_session_minutes <= 180:
            raise ValueError("Target session duration must be between 5 and 180 minutes")
