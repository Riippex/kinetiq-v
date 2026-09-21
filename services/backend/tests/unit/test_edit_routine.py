from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from kinetiq.modules.catalog.application.ports import CatalogRepository
from kinetiq.modules.catalog.domain.entities import (
    Exercise,
    ExercisePrescription,
    GoalDefinition,
    PrescriptionType,
    RoutineTemplate,
    RoutineTemplateItem,
)
from kinetiq.modules.profiles.application.ports import ProfileRepository
from kinetiq.modules.profiles.domain.entities import ExperienceLevel, UserProfile
from kinetiq.modules.routines.application.edit_routine import (
    EditRoutineCommand,
    EditRoutineUseCase,
    RoutineEditItem,
)
from kinetiq.modules.routines.application.ports import RoutineRepository
from kinetiq.modules.routines.domain.entities import Routine
from kinetiq.modules.routines.domain.errors import (
    InvalidRoutineEditError,
    RoutineNotFoundError,
    UnsupportedLimitationError,
)
from kinetiq.modules.workouts.domain.session import CoachingTone

SQUAT = Exercise(
    code="ex-squat",
    version=1,
    slug="squat",
    name="Squat",
    category="LOWER_BODY",
    equipment="NONE",
    prescription=ExercisePrescription(
        prescription_type=PrescriptionType.REPETITIONS,
        default_sets=3,
        default_repetitions=10,
    ),
    vision_supported=True,
    vision_exercise_key="squat",
)
PUSH_UP = Exercise(
    code="ex-push-up",
    version=1,
    slug="push-up",
    name="Push-Up",
    category="UPPER_BODY",
    equipment="NONE",
    prescription=ExercisePrescription(
        prescription_type=PrescriptionType.REPETITIONS,
        default_sets=3,
        default_repetitions=8,
    ),
    vision_supported=True,
    vision_exercise_key="push_up",
)
PULL_UP = Exercise(
    code="ex-pull-up",
    version=1,
    slug="pull-up",
    name="Pull-Up",
    category="UPPER_BODY",
    equipment="PULL_UP_BAR",
    prescription=ExercisePrescription(
        prescription_type=PrescriptionType.REPETITIONS,
        default_sets=3,
        default_repetitions=5,
    ),
    vision_supported=False,
)


class InMemoryCatalogRepository(CatalogRepository):
    def __init__(self) -> None:
        self.goals: dict[str, GoalDefinition] = {}
        self.exercises: dict[str, Exercise] = {}
        self.templates: dict[str, RoutineTemplate] = {}

    def save_goal_definition(self, goal: GoalDefinition) -> None:
        self.goals[goal.code] = goal

    def get_goal_definition(self, code: str) -> GoalDefinition | None:
        return self.goals.get(code)

    def list_goal_definitions(self) -> list[GoalDefinition]:
        return list(self.goals.values())

    def save_exercise(self, exercise: Exercise) -> None:
        self.exercises[exercise.code] = exercise

    def get_exercise(self, code: str) -> Exercise | None:
        return self.exercises.get(code)

    def list_exercises(
        self, equipment: str | None = None, vision_supported: bool | None = None
    ) -> list[Exercise]:
        results = list(self.exercises.values())
        if equipment is not None:
            results = [e for e in results if e.equipment == equipment]
        if vision_supported is not None:
            results = [e for e in results if e.vision_supported == vision_supported]
        return results

    def save_routine_template(self, template: RoutineTemplate) -> None:
        self.templates[template.code] = template

    def get_routine_template(self, code: str) -> RoutineTemplate | None:
        return self.templates.get(code)

    def list_routine_templates(self) -> list[RoutineTemplate]:
        return list(self.templates.values())


class InMemoryProfileRepository(ProfileRepository):
    def __init__(self) -> None:
        self.profiles: dict[UUID, UserProfile] = {}

    def get_by_owner_id(self, owner_id: UUID) -> UserProfile | None:
        return self.profiles.get(owner_id)

    def save(self, profile: UserProfile) -> None:
        self.profiles[profile.owner_id] = profile


class InMemoryRoutineRepository(RoutineRepository):
    def __init__(self) -> None:
        self.records: list[Routine] = []

    def save(self, routine: Routine) -> None:
        self.records.append(routine)

    def get_by_id(self, record_id: UUID) -> Routine | None:
        for r in self.records:
            if r.id == record_id:
                return r
        return None

    def get_by_routine_id(self, owner_id: UUID, routine_id: UUID, version: int) -> Routine | None:
        for r in self.records:
            if r.owner_id == owner_id and r.routine_id == routine_id and r.version == version:
                return r
        return None

    def get_latest_for_owner(self, owner_id: UUID) -> Routine | None:
        owned = [r for r in self.records if r.owner_id == owner_id]
        if not owned:
            return None
        return max(owned, key=lambda r: r.version)

    def get_active_accepted(self, owner_id: UUID) -> Routine | None:
        for r in reversed(self.records):
            if r.owner_id == owner_id and r.accepted:
                return r
        return None

    def list_for_owner(self, owner_id: UUID) -> list[Routine]:
        return [r for r in self.records if r.owner_id == owner_id]


def make_profile(
    owner_id: UUID,
    *,
    available_equipment: tuple[str, ...] = ("NONE",),
    workout_space: str = "LIVING_ROOM",
    exclusions: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    experience_level: ExperienceLevel = ExperienceLevel.RETURNING,
) -> UserProfile:
    return UserProfile(
        owner_id=owner_id,
        display_name="Athlete",
        timezone="UTC",
        experience_level=experience_level,
        availability_days_per_week=3,
        target_session_minutes=15,
        available_equipment=available_equipment,
        workout_space=workout_space,
        preferences=(),
        exclusions=exclusions,
        limitations=limitations,
        coaching_tone=CoachingTone.CALM,
        updated_at=datetime.now(UTC),
    )


def make_base_routine(
    owner_id: UUID,
    *,
    template_code: str = "template-foundation",
    items: tuple[dict[str, object], ...] | None = None,
) -> Routine:
    default_items = (
        {
            "exerciseId": "ex-squat",
            "exerciseVersion": 1,
            "name": "Squat",
            "visionSupported": True,
            "order": 1,
            "sets": 3,
            "repetitions": 10,
            "durationSeconds": None,
        },
    )
    return Routine(
        id=uuid4(),
        routine_id=uuid4(),
        owner_id=owner_id,
        version=1,
        title="Foundation",
        rationale="Initial proposal",
        prescription={
            "templateCode": template_code,
            "templateVersion": 1,
            "estimatedDurationMinutes": 15,
            "items": list(items if items is not None else default_items),
        },
        accepted=False,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def catalog() -> InMemoryCatalogRepository:
    repo = InMemoryCatalogRepository()
    repo.save_exercise(SQUAT)
    repo.save_exercise(PUSH_UP)
    repo.save_exercise(PULL_UP)
    repo.save_routine_template(
        RoutineTemplate(
            code="template-foundation",
            version=1,
            title="Foundation",
            description="Bodyweight foundation",
            target_goal_code="goal-habit",
            estimated_duration_minutes=15,
            items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
            supported_workout_spaces=frozenset({"LIVING_ROOM"}),
            supported_experience_levels=frozenset({"RETURNING"}),
        )
    )
    return repo


@pytest.fixture
def profile_repo() -> InMemoryProfileRepository:
    return InMemoryProfileRepository()


@pytest.fixture
def routine_repo() -> InMemoryRoutineRepository:
    return InMemoryRoutineRepository()


def test_edit_routine_succeeds_with_valid_items(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    athlete_id = uuid4()
    profile_repo.save(make_profile(athlete_id))
    base_routine = make_base_routine(athlete_id)
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)
    updated = use_case.execute(
        athlete_id,
        EditRoutineCommand(
            routine_id=base_routine.routine_id,
            items=(RoutineEditItem(exercise_id="ex-push-up", order=1, sets=3, repetitions=8),),
        ),
    )

    assert updated.version == base_routine.version + 1
    items = updated.prescription["items"]
    assert isinstance(items, list)
    assert items[0]["exerciseId"] == "ex-push-up"


def test_edit_routine_rejects_excluded_exercise(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    """Regression test: an excluded exercise must never enter an accepted
    routine through the edit flow, not only through proposal generation."""
    athlete_id = uuid4()
    profile_repo.save(make_profile(athlete_id, exclusions=("ex-push-up",)))
    base_routine = make_base_routine(athlete_id)
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)

    with pytest.raises(InvalidRoutineEditError, match="excluded"):
        use_case.execute(
            athlete_id,
            EditRoutineCommand(
                routine_id=base_routine.routine_id,
                items=(RoutineEditItem(exercise_id="ex-push-up", order=1, sets=3, repetitions=8),),
            ),
        )
    assert len(routine_repo.records) == 1  # No new revision was persisted


def test_edit_routine_ignores_exclusion_of_unrelated_exercise(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    athlete_id = uuid4()
    profile_repo.save(make_profile(athlete_id, exclusions=("ex-pull-up",)))
    base_routine = make_base_routine(athlete_id)
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)
    updated = use_case.execute(
        athlete_id,
        EditRoutineCommand(
            routine_id=base_routine.routine_id,
            items=(RoutineEditItem(exercise_id="ex-push-up", order=1, sets=3, repetitions=8),),
        ),
    )
    items = updated.prescription["items"]
    assert isinstance(items, list)
    assert items[0]["exerciseId"] == "ex-push-up"


def test_edit_routine_rejects_when_no_supported_limitation_adaptation(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    """Regression test: a self-reported limitation with no catalog adaptation
    must block the edit rather than silently persist an unsafe revision."""
    athlete_id = uuid4()
    profile_repo.save(make_profile(athlete_id, limitations=("KNEE_PAIN",)))
    base_routine = make_base_routine(athlete_id)
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)

    with pytest.raises(UnsupportedLimitationError, match="KNEE_PAIN"):
        use_case.execute(
            athlete_id,
            EditRoutineCommand(
                routine_id=base_routine.routine_id,
                items=(RoutineEditItem(exercise_id="ex-squat", order=1, sets=3, repetitions=10),),
            ),
        )
    assert len(routine_repo.records) == 1


def test_edit_routine_allows_limitation_with_matching_template_adaptation(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    catalog.save_routine_template(
        RoutineTemplate(
            code="template-adapted",
            version=1,
            title="Adapted",
            description="Knee-friendly",
            target_goal_code="goal-habit",
            estimated_duration_minutes=15,
            items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
            supported_workout_spaces=frozenset({"LIVING_ROOM"}),
            supported_experience_levels=frozenset({"RETURNING"}),
            supported_limitation_adaptations=frozenset({"KNEE_PAIN"}),
        )
    )
    athlete_id = uuid4()
    profile_repo.save(make_profile(athlete_id, limitations=("KNEE_PAIN",)))
    base_routine = make_base_routine(athlete_id, template_code="template-adapted")
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)
    updated = use_case.execute(
        athlete_id,
        EditRoutineCommand(
            routine_id=base_routine.routine_id,
            items=(RoutineEditItem(exercise_id="ex-squat", order=1, sets=3, repetitions=10),),
        ),
    )
    assert updated.version == 2


def test_edit_routine_rejects_when_workout_space_no_longer_supported(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    """The template only supports LIVING_ROOM; if the athlete's profile has
    since moved to a space the template does not support, edits must be
    blocked just as a fresh proposal would be."""
    athlete_id = uuid4()
    profile_repo.save(make_profile(athlete_id, workout_space="GYM"))
    base_routine = make_base_routine(athlete_id)
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)

    with pytest.raises(InvalidRoutineEditError, match="workout space"):
        use_case.execute(
            athlete_id,
            EditRoutineCommand(
                routine_id=base_routine.routine_id,
                items=(RoutineEditItem(exercise_id="ex-squat", order=1, sets=3, repetitions=10),),
            ),
        )


def test_edit_routine_still_rejects_unavailable_equipment(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    athlete_id = uuid4()
    profile_repo.save(make_profile(athlete_id, available_equipment=("NONE",)))
    base_routine = make_base_routine(athlete_id)
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)

    with pytest.raises(InvalidRoutineEditError, match="requires equipment"):
        use_case.execute(
            athlete_id,
            EditRoutineCommand(
                routine_id=base_routine.routine_id,
                items=(RoutineEditItem(exercise_id="ex-pull-up", order=1, sets=3, repetitions=5),),
            ),
        )


def test_edit_routine_enforces_owner_isolation(
    catalog: InMemoryCatalogRepository,
    profile_repo: InMemoryProfileRepository,
    routine_repo: InMemoryRoutineRepository,
) -> None:
    owner_id = uuid4()
    other_athlete_id = uuid4()
    profile_repo.save(make_profile(other_athlete_id))
    base_routine = make_base_routine(owner_id)
    routine_repo.save(base_routine)

    use_case = EditRoutineUseCase(routine_repo, catalog, profile_repo)

    with pytest.raises(RoutineNotFoundError):
        use_case.execute(
            other_athlete_id,
            EditRoutineCommand(
                routine_id=base_routine.routine_id,
                items=(RoutineEditItem(exercise_id="ex-squat", order=1, sets=3, repetitions=10),),
            ),
        )
