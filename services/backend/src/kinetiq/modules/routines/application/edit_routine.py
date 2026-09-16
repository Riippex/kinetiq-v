from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from kinetiq.modules.catalog.application.ports import CatalogRepository
from kinetiq.modules.profiles.application.ports import ProfileRepository
from kinetiq.modules.routines.application.ports import RoutineRepository
from kinetiq.modules.routines.domain.entities import Routine
from kinetiq.modules.routines.domain.errors import (
    InvalidRoutineEditError,
    RoutineNotFoundError,
)


@dataclass(frozen=True, slots=True)
class RoutineEditItem:
    exercise_id: str
    order: int
    sets: int
    repetitions: int | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class EditRoutineCommand:
    routine_id: UUID
    items: tuple[RoutineEditItem, ...]
    title: str | None = None
    base_version: int | None = None


class EditRoutineUseCase:
    """Allows an athlete to customize a routine while enforcing catalog constraints."""

    def __init__(
        self,
        routine_repo: RoutineRepository,
        catalog_repo: CatalogRepository,
        profile_repo: ProfileRepository,
    ) -> None:
        self._routine_repo = routine_repo
        self._catalog_repo = catalog_repo
        self._profile_repo = profile_repo

    def execute(self, athlete_id: UUID, command: EditRoutineCommand) -> Routine:
        if not command.items:
            raise InvalidRoutineEditError("Routine must contain at least one exercise item")

        # 1. Fetch base routine
        if command.base_version is not None:
            base_routine = self._routine_repo.get_by_routine_id(
                owner_id=athlete_id,
                routine_id=command.routine_id,
                version=command.base_version,
            )
        else:
            base_routine = self._routine_repo.get_latest_for_owner(owner_id=athlete_id)
            if base_routine is not None and base_routine.routine_id != command.routine_id:
                # Find specific latest revision for this routine_id
                routines = [
                    r
                    for r in self._routine_repo.list_for_owner(athlete_id)
                    if r.routine_id == command.routine_id
                ]
                base_routine = routines[0] if routines else None

        if base_routine is None or base_routine.owner_id != athlete_id:
            raise RoutineNotFoundError(
                f"Routine {command.routine_id} not found for athlete {athlete_id}"
            )

        # 2. Revalidate item orders
        orders = [item.order for item in command.items]
        if len(orders) != len(set(orders)):
            raise InvalidRoutineEditError("Exercise items must have unique order positions")

        # 3. Fetch athlete profile for equipment constraints
        profile = self._profile_repo.get_by_owner_id(athlete_id)
        available_equipment = (
            {eq.upper() for eq in profile.available_equipment} | {"NONE"}
            if profile is not None
            else {"NONE"}
        )

        # 4. Revalidate each exercise against catalog and equipment
        validated_items_data: list[dict[str, object]] = []
        for item in sorted(command.items, key=lambda x: x.order):
            exercise = self._catalog_repo.get_exercise(item.exercise_id)
            if exercise is None:
                raise InvalidRoutineEditError(
                    f"Exercise '{item.exercise_id}' does not exist in catalog"
                )

            if exercise.equipment.upper() not in available_equipment:
                raise InvalidRoutineEditError(
                    f"Exercise '{exercise.name}' requires equipment '{exercise.equipment}' "
                    f"which is not available in athlete's profile"
                )

            if item.sets < 1:
                raise InvalidRoutineEditError("Prescription sets must be positive")
            if item.repetitions is None and item.duration_seconds is None:
                raise InvalidRoutineEditError(
                    "Each item must specify either repetitions or duration_seconds"
                )
            if item.repetitions is not None and item.repetitions < 1:
                raise InvalidRoutineEditError("Repetitions must be positive")
            if item.duration_seconds is not None and item.duration_seconds < 1:
                raise InvalidRoutineEditError("Duration seconds must be positive")

            validated_items_data.append(
                {
                    "exerciseId": exercise.code,
                    "exerciseVersion": exercise.version,
                    "name": exercise.name,
                    "visionSupported": exercise.vision_supported,
                    "order": item.order,
                    "sets": item.sets,
                    "repetitions": item.repetitions,
                    "durationSeconds": item.duration_seconds,
                }
            )

        # 5. Create immutable next revision
        new_version = base_routine.version + 1
        new_title = (
            command.title.strip()
            if command.title and command.title.strip()
            else base_routine.title
        )
        updated_prescription: dict[str, object] = {
            "templateCode": base_routine.prescription.get("templateCode", "custom"),
            "templateVersion": base_routine.prescription.get("templateVersion", 1),
            "estimatedDurationMinutes": base_routine.prescription.get(
                "estimatedDurationMinutes", 15
            ),
            "items": validated_items_data,
        }

        updated_routine = Routine(
            id=uuid4(),
            routine_id=base_routine.routine_id,
            owner_id=athlete_id,
            version=new_version,
            title=new_title,
            rationale=f"Athlete-adjusted revision {new_version}",
            prescription=updated_prescription,
            accepted=False,
            created_at=datetime.now(UTC),
        )

        self._routine_repo.save(updated_routine)
        return updated_routine
