import pytest

from kinetiq.modules.catalog.application.ports import CatalogRepository, VisionCapabilities
from kinetiq.modules.catalog.application.seed_catalog import (
    InvalidTemplateError,
    SeedCatalogUseCase,
    VisionCapabilityMismatchError,
)
from kinetiq.modules.catalog.domain.entities import (
    Exercise,
    ExercisePrescription,
    GoalDefinition,
    PrescriptionType,
    RoutineTemplate,
    RoutineTemplateItem,
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


class StubVisionCapabilities(VisionCapabilities):
    def __init__(self, supported_keys: set[str]) -> None:
        self._keys = supported_keys

    def get_supported_exercise_keys(self) -> set[str]:
        return set(self._keys)

    def is_exercise_supported(self, exercise_key: str) -> bool:
        return exercise_key in self._keys


def test_goal_definition_requires_target_greater_than_baseline() -> None:
    with pytest.raises(ValueError, match="strictly greater than baseline"):
        GoalDefinition(
            code="goal-test",
            revision=1,
            name="Test",
            description="desc",
            measure="sessions",
            baseline=3.0,
            target=2.0,
            unit="sessions",
        )


def test_exercise_prescription_validation() -> None:
    # Repetition prescription requires repetitions
    with pytest.raises(ValueError, match="requires positive default_repetitions"):
        ExercisePrescription(
            prescription_type=PrescriptionType.REPETITIONS,
            default_sets=3,
            default_repetitions=None,
        )

    # Duration prescription requires duration_seconds
    with pytest.raises(ValueError, match="requires positive default_duration_seconds"):
        ExercisePrescription(
            prescription_type=PrescriptionType.DURATION,
            default_sets=3,
            default_duration_seconds=None,
        )


def test_exercise_entity_vision_invariants() -> None:
    # Vision supported must define vision_exercise_key
    with pytest.raises(ValueError, match="must specify vision_exercise_key"):
        Exercise(
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
            vision_exercise_key=None,
        )

    # Vision unsupported must NOT define vision_exercise_key
    with pytest.raises(ValueError, match="cannot define vision_exercise_key"):
        Exercise(
            code="ex-pullup",
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
            vision_exercise_key="pull_up",
        )


def test_routine_template_requires_unique_order_items() -> None:
    with pytest.raises(ValueError, match="unique order"):
        RoutineTemplate(
            code="tmpl-1",
            version=1,
            title="Title",
            description="Desc",
            target_goal_code="goal-1",
            estimated_duration_minutes=15,
            items=(
                RoutineTemplateItem(exercise_code="ex-1", order=1, sets=3, repetitions=10),
                RoutineTemplateItem(exercise_code="ex-2", order=1, sets=3, repetitions=10),
            ),
        )


def test_seed_catalog_rejects_unsupported_exercise_marked_as_vision_supported() -> None:
    repo = InMemoryCatalogRepository()
    # Vision only supports squat
    vision = StubVisionCapabilities(supported_keys={"bodyweight_squat"})

    exercises = [
        Exercise(
            code="exercise-flying-kick",
            version=1,
            slug="flying-kick",
            name="Flying Kick",
            category="LOWER_BODY",
            equipment="NONE",
            prescription=ExercisePrescription(
                prescription_type=PrescriptionType.REPETITIONS,
                default_sets=3,
                default_repetitions=5,
            ),
            vision_supported=True,
            vision_exercise_key="flying_kick",  # NOT in Vision capabilities
        )
    ]

    use_case = SeedCatalogUseCase(catalog_repo=repo, vision_capabilities=vision)
    with pytest.raises(VisionCapabilityMismatchError) as excinfo:
        use_case.execute(goals=(), exercises=exercises, templates=())

    assert "flying_kick" in str(excinfo.value)
    assert len(repo.exercises) == 0


def test_seed_catalog_rejects_template_with_unknown_exercise() -> None:
    repo = InMemoryCatalogRepository()
    vision = StubVisionCapabilities(supported_keys={"bodyweight_squat"})

    template = RoutineTemplate(
        code="tmpl-1",
        version=1,
        title="Template",
        description="Desc",
        target_goal_code="goal-1",
        estimated_duration_minutes=10,
        items=(
            RoutineTemplateItem(exercise_code="exercise-unknown", order=1, sets=3, repetitions=10),
        ),
    )

    use_case = SeedCatalogUseCase(catalog_repo=repo, vision_capabilities=vision)
    with pytest.raises(InvalidTemplateError, match="exercise-unknown"):
        use_case.execute(goals=(), exercises=(), templates=(template,))
