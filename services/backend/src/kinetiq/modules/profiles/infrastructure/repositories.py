from __future__ import annotations

from uuid import UUID

from kinetiq.modules.profiles.application.ports import ProfileRepository
from kinetiq.modules.profiles.domain.entities import ExperienceLevel, UserProfile
from kinetiq.modules.profiles.infrastructure.models import UserProfileRecord
from kinetiq.modules.workouts.domain.session import CoachingTone


class DjangoProfileRepository(ProfileRepository):
    def get_by_owner_id(self, owner_id: UUID) -> UserProfile | None:
        try:
            record = UserProfileRecord.objects.get(owner_id=owner_id)
            return self._to_entity(record)
        except UserProfileRecord.DoesNotExist:
            return None

    def save(self, profile: UserProfile) -> None:
        UserProfileRecord.objects.update_or_create(
            owner_id=profile.owner_id,
            defaults={
                "display_name": profile.display_name,
                "timezone": profile.timezone,
                "experience_level": profile.experience_level.value,
                "availability_days_per_week": profile.availability_days_per_week,
                "target_session_minutes": profile.target_session_minutes,
                "available_equipment": list(profile.available_equipment),
                "workout_space": profile.workout_space,
                "preferences": list(profile.preferences),
                "exclusions": list(profile.exclusions),
                "limitations": list(profile.limitations),
                "coaching_tone": profile.coaching_tone.value,
            },
        )

    @staticmethod
    def _to_entity(record: UserProfileRecord) -> UserProfile:
        return UserProfile(
            owner_id=record.owner_id,
            display_name=record.display_name,
            timezone=record.timezone,
            experience_level=ExperienceLevel(record.experience_level),
            availability_days_per_week=record.availability_days_per_week,
            target_session_minutes=record.target_session_minutes,
            available_equipment=tuple(record.available_equipment),
            workout_space=record.workout_space,
            preferences=tuple(record.preferences),
            exclusions=tuple(record.exclusions),
            limitations=tuple(record.limitations),
            coaching_tone=CoachingTone(record.coaching_tone),
            updated_at=record.updated_at,
        )
