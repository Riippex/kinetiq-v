from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PrescriptionType(StrEnum):
    REPETITIONS = "REPETITIONS"
    DURATION = "DURATION"


@dataclass(frozen=True, slots=True)
class GoalDefinition:
    code: str
    revision: int
    name: str
    description: str
    measure: str
    baseline: float
    target: float
    unit: str

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("Goal definition code cannot be empty")
        if self.revision < 1:
            raise ValueError("Goal definition revision must be positive")
        if self.target <= self.baseline:
            raise ValueError("Goal target must be strictly greater than baseline")


@dataclass(frozen=True, slots=True)
class ExercisePrescription:
    prescription_type: PrescriptionType
    default_sets: int
    default_repetitions: int | None = None
    default_duration_seconds: int | None = None
    default_rest_seconds: int = 60

    def __post_init__(self) -> None:
        if self.default_sets < 1:
            raise ValueError("Prescription sets must be positive")
        if self.default_rest_seconds < 0:
            raise ValueError("Rest seconds cannot be negative")
        if self.prescription_type is PrescriptionType.REPETITIONS:
            if self.default_repetitions is None or self.default_repetitions < 1:
                raise ValueError("Repetition prescription requires positive default_repetitions")
            if self.default_duration_seconds is not None:
                raise ValueError("Repetition prescription cannot define duration_seconds")
        elif self.prescription_type is PrescriptionType.DURATION:
            if self.default_duration_seconds is None or self.default_duration_seconds < 1:
                raise ValueError("Duration prescription requires positive default_duration_seconds")
            if self.default_repetitions is not None:
                raise ValueError("Duration prescription cannot define repetitions")


@dataclass(frozen=True, slots=True)
class Exercise:
    code: str
    version: int
    slug: str
    name: str
    category: str
    equipment: str
    prescription: ExercisePrescription
    vision_supported: bool
    vision_exercise_key: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("Exercise code cannot be empty")
        if self.version < 1:
            raise ValueError("Exercise version must be positive")
        if not self.name.strip():
            raise ValueError("Exercise name cannot be empty")
        if self.vision_supported:
            if not self.vision_exercise_key or not self.vision_exercise_key.strip():
                raise ValueError("Vision-supported exercise must specify vision_exercise_key")
        else:
            if self.vision_exercise_key is not None:
                raise ValueError(
                    "Exercise without vision support cannot define vision_exercise_key"
                )


@dataclass(frozen=True, slots=True)
class RoutineTemplateItem:
    exercise_code: str
    order: int
    sets: int
    repetitions: int | None = None
    duration_seconds: int | None = None
    rest_seconds: int = 60

    def __post_init__(self) -> None:
        if not self.exercise_code.strip():
            raise ValueError("Template item exercise_code cannot be empty")
        if self.order < 1:
            raise ValueError("Template item order must be positive")
        if self.sets < 1:
            raise ValueError("Template item sets must be positive")
        if self.repetitions is None and self.duration_seconds is None:
            raise ValueError("Template item must prescribe either repetitions or duration_seconds")
        if self.repetitions is not None and self.repetitions < 1:
            raise ValueError("Template item repetitions must be positive")
        if self.duration_seconds is not None and self.duration_seconds < 1:
            raise ValueError("Template item duration_seconds must be positive")


@dataclass(frozen=True, slots=True)
class RoutineTemplate:
    code: str
    version: int
    title: str
    description: str
    target_goal_code: str
    estimated_duration_minutes: int
    items: tuple[RoutineTemplateItem, ...]

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("Template code cannot be empty")
        if self.version < 1:
            raise ValueError("Template version must be positive")
        if self.estimated_duration_minutes < 1:
            raise ValueError("Estimated duration minutes must be positive")
        if not self.items:
            raise ValueError("Routine template must contain at least one item")
        orders = [item.order for item in self.items]
        if len(orders) != len(set(orders)):
            raise ValueError("Template items must have unique order numbers")
