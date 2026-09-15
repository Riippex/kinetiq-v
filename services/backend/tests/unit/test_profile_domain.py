from datetime import UTC, datetime
from uuid import uuid4

import pytest

from kinetiq.modules.profiles.application import (
    GetProfileUseCase,
    ProfileRepository,
    UpdateProfileCommand,
    UpdateProfileUseCase,
)
from kinetiq.modules.profiles.domain import ExperienceLevel, UserProfile
from kinetiq.modules.workouts.domain.session import CoachingTone


class InMemoryProfileRepository(ProfileRepository):
    def __init__(self) -> None:
        self.profiles: dict[str, UserProfile] = {}

    def get_by_owner_id(self, owner_id):
        return self.profiles.get(str(owner_id))

    def save(self, profile: UserProfile) -> None:
        self.profiles[str(profile.owner_id)] = profile


def test_user_profile_invariants() -> None:
    owner_id = uuid4()
    now = datetime.now(UTC)

    # Empty display name rejected
    with pytest.raises(ValueError, match="Display name cannot be empty"):
        UserProfile(
            owner_id=owner_id,
            display_name="",
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
            updated_at=now,
        )

    # Days per week must be between 1 and 7
    with pytest.raises(ValueError, match="Availability must be between 1 and 7"):
        UserProfile(
            owner_id=owner_id,
            display_name="Athlete",
            timezone="UTC",
            experience_level=ExperienceLevel.RETURNING,
            availability_days_per_week=8,
            target_session_minutes=15,
            available_equipment=("NONE",),
            workout_space="LIVING_ROOM",
            preferences=(),
            exclusions=(),
            limitations=(),
            coaching_tone=CoachingTone.CALM,
            updated_at=now,
        )


def test_get_profile_auto_initializes_clean_default() -> None:
    repo = InMemoryProfileRepository()
    use_case = GetProfileUseCase(repo)
    owner_id = uuid4()

    profile = use_case.execute(owner_id, default_display_name="Sam")
    assert profile.owner_id == owner_id
    assert profile.display_name == "Sam"
    assert profile.experience_level == ExperienceLevel.RETURNING
    assert profile.available_equipment == ("NONE",)


def test_update_profile_updates_selected_fields() -> None:
    repo = InMemoryProfileRepository()
    get_use_case = GetProfileUseCase(repo)
    update_use_case = UpdateProfileUseCase(repo)
    owner_id = uuid4()

    get_use_case.execute(owner_id)

    updated = update_use_case.execute(
        owner_id,
        UpdateProfileCommand(
            display_name="Alex",
            experience_level=ExperienceLevel.REGULAR,
            availability_days_per_week=4,
            available_equipment=("NONE", "RESISTANCE_BANDS"),
            exclusions=("exercise-burpee-v1",),
        ),
    )

    assert updated.display_name == "Alex"
    assert updated.experience_level == ExperienceLevel.REGULAR
    assert updated.availability_days_per_week == 4
    assert updated.available_equipment == ("NONE", "RESISTANCE_BANDS")
    assert updated.exclusions == ("exercise-burpee-v1",)
    assert updated.target_session_minutes == 15  # Preserved from existing
