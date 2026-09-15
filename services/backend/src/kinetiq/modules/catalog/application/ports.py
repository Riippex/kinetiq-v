from __future__ import annotations

from typing import Protocol

from kinetiq.modules.catalog.domain.entities import Exercise, GoalDefinition, RoutineTemplate


class CatalogRepository(Protocol):
    def save_goal_definition(self, goal: GoalDefinition) -> None:
        ...

    def get_goal_definition(self, code: str) -> GoalDefinition | None:
        ...

    def list_goal_definitions(self) -> list[GoalDefinition]:
        ...

    def save_exercise(self, exercise: Exercise) -> None:
        ...

    def get_exercise(self, code: str) -> Exercise | None:
        ...

    def list_exercises(
        self, equipment: str | None = None, vision_supported: bool | None = None
    ) -> list[Exercise]:
        ...

    def save_routine_template(self, template: RoutineTemplate) -> None:
        ...

    def get_routine_template(self, code: str) -> RoutineTemplate | None:
        ...

    def list_routine_templates(self) -> list[RoutineTemplate]:
        ...


class VisionCapabilities(Protocol):
    def get_supported_exercise_keys(self) -> set[str]:
        ...

    def is_exercise_supported(self, exercise_key: str) -> bool:
        ...
