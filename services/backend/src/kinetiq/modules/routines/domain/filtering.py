from __future__ import annotations

from collections.abc import Mapping, Sequence

from kinetiq.modules.catalog.domain.entities import Exercise, RoutineTemplate
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria


def filter_eligible_templates(
    templates: Sequence[RoutineTemplate],
    exercises_by_code: Mapping[str, Exercise],
    criteria: RoutineEligibilityCriteria,
) -> list[RoutineTemplate]:
    """Filter catalog routine templates deterministically against athlete criteria.

    A template is eligible if and only if:
    1. It matches the athlete's target goal code (when specified).
    2. Every prescribed exercise exists in the catalog.
    3. Every prescribed exercise requires equipment available to the athlete
       (the 'NONE' equipment requirement is universally satisfied).

    Results are sorted deterministically:
    - Primary key: Closeness of estimated_duration_minutes to the athlete's target.
    - Secondary key: Template code ascending (guarantees tie-break consistency).
    """
    eligible: list[RoutineTemplate] = []
    # Normalize available equipment to uppercase and always include NONE
    available_equipment = {eq.upper() for eq in criteria.available_equipment} | {"NONE"}

    for template in templates:
        # 1. Goal match
        if (
            criteria.target_goal_code is not None
            and template.target_goal_code != criteria.target_goal_code
        ):
            continue

        # 2. Exercise existence and equipment match
        all_exercises_eligible = True
        for item in template.items:
            exercise = exercises_by_code.get(item.exercise_code)
            if exercise is None:
                all_exercises_eligible = False
                break
            if exercise.equipment.upper() not in available_equipment:
                all_exercises_eligible = False
                break

        if all_exercises_eligible:
            eligible.append(template)

    # 3. Deterministic ranking
    eligible.sort(
        key=lambda t: (
            abs(t.estimated_duration_minutes - criteria.target_duration_minutes),
            t.code,
        )
    )

    return eligible
