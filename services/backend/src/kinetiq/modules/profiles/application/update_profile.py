from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from kinetiq.modules.profiles.application.ports import ProfileRepository
from kinetiq.modules.profiles.domain.entities import ExperienceLevel, UserProfile
from kinetiq.modules.workouts.domain.session import CoachingTone


@dataclass(frozen=True, slots=True)
class UpdateProfileCommand:
    display_name: str | None = None
    timezone_name: str | None = None
    experience_level: ExperienceLevel | None = None
    availability_days_per_week: int | None = None
    target_session_minutes: int | None = None
    available_equipment: tuple[str, ...] | None = None
    workout_space: str | None = None
    preferences: tuple[str, ...] | None = None
    exclusions: tuple[str, ...] | None = None
    limitations: tuple[str, ...] | None = None
    coaching_tone: CoachingTone | None = None


class UpdateProfileUseCase:
    def __init__(self, profile_repo: ProfileRepository) -> None:
        self._repo = profile_repo

    def execute(self, owner_id: UUID, command: UpdateProfileCommand) -> UserProfile:
        existing = self._repo.get_by_owner_id(owner_id)

        display_name = (
            command.display_name
            if command.display_name is not None
            else (existing.display_name if existing else "Athlete")
        )
        tz = (
            command.timezone_name
            if command.timezone_name is not None
            else (existing.timezone if existing else "UTC")
        )
        experience = (
            command.experience_level
            if command.experience_level is not None
            else (existing.experience_level if existing else ExperienceLevel.RETURNING)
        )
        days = (
            command.availability_days_per_week
            if command.availability_days_per_week is not None
            else (existing.availability_days_per_week if existing else 3)
        )
        minutes = (
            command.target_session_minutes
            if command.target_session_minutes is not None
            else (existing.target_session_minutes if existing else 15)
        )
        equipment = (
            command.available_equipment
            if command.available_equipment is not None
            else (existing.available_equipment if existing else ("NONE",))
        )
        space = (
            command.workout_space
            if command.workout_space is not None
            else (existing.workout_space if existing else "LIVING_ROOM")
        )
        preferences = (
            command.preferences
            if command.preferences is not None
            else (existing.preferences if existing else ())
        )
        exclusions = (
            command.exclusions
            if command.exclusions is not None
            else (existing.exclusions if existing else ())
        )
        limitations = (
            command.limitations
            if command.limitations is not None
            else (existing.limitations if existing else ())
        )
        tone = (
            command.coaching_tone
            if command.coaching_tone is not None
            else (existing.coaching_tone if existing else CoachingTone.CALM)
        )

        updated = UserProfile(
            owner_id=owner_id,
            display_name=display_name,
            timezone=tz,
            experience_level=experience,
            availability_days_per_week=days,
            target_session_minutes=minutes,
            available_equipment=equipment,
            workout_space=space,
            preferences=preferences,
            exclusions=exclusions,
            limitations=limitations,
            coaching_tone=tone,
            updated_at=datetime.now(UTC),
        )

        self._repo.save(updated)
        return updated
