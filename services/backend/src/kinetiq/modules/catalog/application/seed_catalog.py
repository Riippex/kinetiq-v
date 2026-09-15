from collections.abc import Sequence
from dataclasses import dataclass

from kinetiq.modules.catalog.application.ports import CatalogRepository, VisionCapabilities
from kinetiq.modules.catalog.domain.entities import Exercise, GoalDefinition, RoutineTemplate


class VisionCapabilityMismatchError(ValueError):
    """Raised when an exercise claims vision support not backed by the Vision contract."""


class InvalidTemplateError(ValueError):
    """Raised when a routine template references unknown or incompatible exercises."""


@dataclass(frozen=True, slots=True)
class SeedCatalogResult:
    goals_seeded: int
    exercises_seeded: int
    templates_seeded: int


class SeedCatalogUseCase:
    def __init__(
        self,
        catalog_repo: CatalogRepository,
        vision_capabilities: VisionCapabilities,
    ) -> None:
        self._repo = catalog_repo
        self._vision = vision_capabilities

    def execute(
        self,
        goals: Sequence[GoalDefinition],
        exercises: Sequence[Exercise],
        templates: Sequence[RoutineTemplate],
    ) -> SeedCatalogResult:
        # 1. Validate exercises against the Vision capabilities contract
        supported_keys = self._vision.get_supported_exercise_keys()
        for exercise in exercises:
            if exercise.vision_supported:
                assert exercise.vision_exercise_key is not None
                if exercise.vision_exercise_key not in supported_keys:
                    raise VisionCapabilityMismatchError(
                        f"Exercise '{exercise.code}' claims vision support for "
                        f"'{exercise.vision_exercise_key}', but the Vision service does not "
                        "support it."
                    )
            self._repo.save_exercise(exercise)

        # 2. Save goals
        for goal in goals:
            self._repo.save_goal_definition(goal)

        # 3. Validate template items reference saved exercises
        saved_exercise_codes = {ex.code for ex in exercises}
        for template in templates:
            for item in template.items:
                if item.exercise_code not in saved_exercise_codes:
                    raise InvalidTemplateError(
                        f"Routine template '{template.code}' references unknown exercise "
                        f"'{item.exercise_code}'."
                    )
            self._repo.save_routine_template(template)

        return SeedCatalogResult(
            goals_seeded=len(goals),
            exercises_seeded=len(exercises),
            templates_seeded=len(templates),
        )
