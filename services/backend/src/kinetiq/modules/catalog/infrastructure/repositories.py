from __future__ import annotations

from kinetiq.modules.catalog.application.ports import CatalogRepository
from kinetiq.modules.catalog.domain.entities import (
    Exercise,
    ExercisePrescription,
    GoalDefinition,
    PrescriptionType,
    RoutineTemplate,
    RoutineTemplateItem,
)
from kinetiq.modules.catalog.infrastructure.models import (
    ExerciseRecord,
    GoalDefinitionRecord,
    RoutineTemplateRecord,
)


class DjangoCatalogRepository(CatalogRepository):
    def save_goal_definition(self, goal: GoalDefinition) -> None:
        GoalDefinitionRecord.objects.update_or_create(
            code=goal.code,
            defaults={
                "revision": goal.revision,
                "name": goal.name,
                "description": goal.description,
                "measure": goal.measure,
                "baseline": goal.baseline,
                "target": goal.target,
                "unit": goal.unit,
            },
        )

    def get_goal_definition(self, code: str) -> GoalDefinition | None:
        try:
            record = GoalDefinitionRecord.objects.get(code=code)
            return self._to_goal_entity(record)
        except GoalDefinitionRecord.DoesNotExist:
            return None

    def list_goal_definitions(self) -> list[GoalDefinition]:
        records = GoalDefinitionRecord.objects.all().order_by("code")
        return [self._to_goal_entity(record) for record in records]

    def save_exercise(self, exercise: Exercise) -> None:
        prescription_data = {
            "default_sets": exercise.prescription.default_sets,
            "default_repetitions": exercise.prescription.default_repetitions,
            "default_duration_seconds": exercise.prescription.default_duration_seconds,
            "default_rest_seconds": exercise.prescription.default_rest_seconds,
        }
        ExerciseRecord.objects.update_or_create(
            code=exercise.code,
            defaults={
                "version": exercise.version,
                "slug": exercise.slug,
                "name": exercise.name,
                "category": exercise.category,
                "equipment": exercise.equipment,
                "prescription_type": exercise.prescription.prescription_type.value,
                "default_prescription": prescription_data,
                "vision_supported": exercise.vision_supported,
                "vision_exercise_key": exercise.vision_exercise_key,
            },
        )

    def get_exercise(self, code: str) -> Exercise | None:
        try:
            record = ExerciseRecord.objects.get(code=code)
            return self._to_exercise_entity(record)
        except ExerciseRecord.DoesNotExist:
            return None

    def list_exercises(
        self, equipment: str | None = None, vision_supported: bool | None = None
    ) -> list[Exercise]:
        qs = ExerciseRecord.objects.all()
        if equipment is not None:
            qs = qs.filter(equipment=equipment)
        if vision_supported is not None:
            qs = qs.filter(vision_supported=vision_supported)
        return [self._to_exercise_entity(record) for record in qs.order_by("code")]

    def save_routine_template(self, template: RoutineTemplate) -> None:
        items_data = [
            {
                "exercise_code": item.exercise_code,
                "order": item.order,
                "sets": item.sets,
                "repetitions": item.repetitions,
                "duration_seconds": item.duration_seconds,
                "rest_seconds": item.rest_seconds,
            }
            for item in template.items
        ]
        RoutineTemplateRecord.objects.update_or_create(
            code=template.code,
            defaults={
                "version": template.version,
                "title": template.title,
                "description": template.description,
                "target_goal_code": template.target_goal_code,
                "estimated_duration_minutes": template.estimated_duration_minutes,
                "items": items_data,
                "supported_workout_spaces": sorted(template.supported_workout_spaces),
                "supported_experience_levels": sorted(template.supported_experience_levels),
                "supported_limitation_adaptations": sorted(
                    template.supported_limitation_adaptations
                ),
            },
        )

    def get_routine_template(self, code: str) -> RoutineTemplate | None:
        try:
            record = RoutineTemplateRecord.objects.get(code=code)
            return self._to_template_entity(record)
        except RoutineTemplateRecord.DoesNotExist:
            return None

    def list_routine_templates(self) -> list[RoutineTemplate]:
        records = RoutineTemplateRecord.objects.all().order_by("code")
        return [self._to_template_entity(record) for record in records]

    @staticmethod
    def _to_goal_entity(record: GoalDefinitionRecord) -> GoalDefinition:
        return GoalDefinition(
            code=record.code,
            revision=record.revision,
            name=record.name,
            description=record.description,
            measure=record.measure,
            baseline=record.baseline,
            target=record.target,
            unit=record.unit,
        )

    @staticmethod
    def _to_exercise_entity(record: ExerciseRecord) -> Exercise:
        data = record.default_prescription
        prescription = ExercisePrescription(
            prescription_type=PrescriptionType(record.prescription_type),
            default_sets=data["default_sets"],
            default_repetitions=data.get("default_repetitions"),
            default_duration_seconds=data.get("default_duration_seconds"),
            default_rest_seconds=data.get("default_rest_seconds", 60),
        )
        return Exercise(
            code=record.code,
            version=record.version,
            slug=record.slug,
            name=record.name,
            category=record.category,
            equipment=record.equipment,
            prescription=prescription,
            vision_supported=record.vision_supported,
            vision_exercise_key=record.vision_exercise_key,
        )

    @staticmethod
    def _to_template_entity(record: RoutineTemplateRecord) -> RoutineTemplate:
        items = tuple(
            RoutineTemplateItem(
                exercise_code=item["exercise_code"],
                order=item["order"],
                sets=item["sets"],
                repetitions=item.get("repetitions"),
                duration_seconds=item.get("duration_seconds"),
                rest_seconds=item.get("rest_seconds", 60),
            )
            for item in record.items
        )
        return RoutineTemplate(
            code=record.code,
            version=record.version,
            title=record.title,
            description=record.description,
            target_goal_code=record.target_goal_code,
            estimated_duration_minutes=record.estimated_duration_minutes,
            items=items,
            supported_workout_spaces=frozenset(record.supported_workout_spaces),
            supported_experience_levels=frozenset(record.supported_experience_levels),
            supported_limitation_adaptations=frozenset(
                record.supported_limitation_adaptations
            ),
        )
