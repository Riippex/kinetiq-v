import pytest

from kinetiq.modules.catalog.application.seed_catalog import SeedCatalogUseCase
from kinetiq.modules.catalog.infrastructure.canonical_data import (
    CANONICAL_EXERCISES,
    CANONICAL_GOALS,
    CANONICAL_TEMPLATES,
)
from kinetiq.modules.catalog.infrastructure.models import (
    ExerciseRecord,
    GoalDefinitionRecord,
    RoutineTemplateRecord,
)
from kinetiq.modules.catalog.infrastructure.repositories import DjangoCatalogRepository
from kinetiq.modules.catalog.infrastructure.vision_contract_adapter import (
    FileBasedVisionCapabilities,
)


@pytest.mark.django_db
def test_canonical_catalog_seeds_idempotently_with_vision_contract() -> None:
    repo = DjangoCatalogRepository()
    vision = FileBasedVisionCapabilities()

    use_case = SeedCatalogUseCase(catalog_repo=repo, vision_capabilities=vision)

    # First run
    result1 = use_case.execute(
        goals=CANONICAL_GOALS,
        exercises=CANONICAL_EXERCISES,
        templates=CANONICAL_TEMPLATES,
    )
    assert result1.goals_seeded == 1
    assert result1.exercises_seeded == 5
    assert result1.templates_seeded == 1

    assert GoalDefinitionRecord.objects.count() == 1
    assert ExerciseRecord.objects.count() == 5
    assert RoutineTemplateRecord.objects.count() == 1

    # Verify goal record
    goal = GoalDefinitionRecord.objects.get(code="goal-habit-consistency-v1")
    assert goal.measure == "weekly_completed_sessions"
    assert goal.baseline == 0.0
    assert goal.target == 3.0
    assert goal.unit == "sessions/week"

    # Verify vision supported vs unsupported boundary
    vision_exercises = repo.list_exercises(vision_supported=True)
    assert len(vision_exercises) == 4
    vision_keys = {ex.vision_exercise_key for ex in vision_exercises}
    assert vision_keys == {"bodyweight_squat", "push_up", "plank", "glute_bridge"}

    unsupported_exercises = repo.list_exercises(vision_supported=False)
    assert len(unsupported_exercises) == 1
    assert unsupported_exercises[0].slug == "pull-up"
    assert unsupported_exercises[0].equipment == "PULL_UP_BAR"

    # Verify template
    template = repo.get_routine_template("template-full-body-foundation-v1")
    assert template is not None
    assert template.estimated_duration_minutes == 15
    assert len(template.items) == 4
    assert [item.order for item in template.items] == [1, 2, 3, 4]

    # Second run (idempotency verification)
    result2 = use_case.execute(
        goals=CANONICAL_GOALS,
        exercises=CANONICAL_EXERCISES,
        templates=CANONICAL_TEMPLATES,
    )
    assert result2.goals_seeded == 1
    assert result2.exercises_seeded == 5
    assert result2.templates_seeded == 1

    # Row counts remain unchanged
    assert GoalDefinitionRecord.objects.count() == 1
    assert ExerciseRecord.objects.count() == 5
    assert RoutineTemplateRecord.objects.count() == 1
