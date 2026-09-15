from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from kinetiq.modules.profiles.application.ports import ProfileRepository
from kinetiq.modules.profiles.domain.entities import ExperienceLevel, UserProfile
from kinetiq.modules.workouts.domain.session import CoachingTone


class GetProfileUseCase:
    def __init__(self, profile_repo: ProfileRepository) -> None:
        self._repo = profile_repo

    def execute(self, owner_id: UUID, default_display_name: str = "Athlete") -> UserProfile:
        profile = self._repo.get_by_owner_id(owner_id)
        if profile is not None:
            return profile

        # Initialize clean defaults for returning exerciser
        new_profile = UserProfile(
            owner_id=owner_id,
            display_name=default_display_name,
            timezone="UTC",
            experience_level=ExperienceLevel.RETURNING,
            availability_days_per_week=3,
            target_session_minutes=15,
            available_equipment=("NONE",),
            workout_space="LIVING_ROOM",
            preferences=(),
            exclusions=(),
            limitations=(),
            coaching_tone=CoachingTone.CALM,
            updated_at=datetime.now(UTC),
        )
        self._repo.save(new_profile)
        return new_profile
