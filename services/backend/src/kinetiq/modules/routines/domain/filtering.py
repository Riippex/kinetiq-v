from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet

from kinetiq.modules.catalog.domain.entities import Exercise, RoutineTemplate
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria


def normalize_excluded_exercise_codes(
    raw_exclusions: Sequence[str],
    known_exercise_codes: AbstractSet[str],
) -> frozenset[str]:
    """Normalize athlete-declared exclusions to stable catalog exercise identifiers.

    Only exact matches against known catalog exercise codes are honored: this
    performs no fuzzy or free-text matching and infers no medical meaning from
    the exclusion values. An exclusion that does not name a real catalog
    exercise code is dropped rather than guessed at.
    """
    return frozenset(
        code.strip()
        for code in raw_exclusions
        if code and code.strip() in known_exercise_codes
    )


def template_satisfies_non_item_constraints(
    template: RoutineTemplate,
    criteria: RoutineEligibilityCriteria,
) -> bool:
    """Check template-level constraints that do not depend on individual items:
    target goal, workout space, experience level, and limitation adaptations.

    Equipment and exclusion checks are per-item and handled separately, since
    they require resolving each item's exercise from the catalog.
    """
    if (
        criteria.target_goal_code is not None
        and template.target_goal_code != criteria.target_goal_code
    ):
        return False

    supported_spaces = {space.upper() for space in template.supported_workout_spaces}
    if (
        supported_spaces
        and criteria.workout_space is not None
        and criteria.workout_space.strip().upper() not in supported_spaces
    ):
        return False

    supported_experience = {
        level.upper() for level in template.supported_experience_levels
    }
    normalized_experience = criteria.experience_level.strip().upper()
    if supported_experience and normalized_experience not in supported_experience:
        return False

    if not criteria.limitations.issubset(template.supported_limitation_adaptations):
        return False

    return True


def exercise_item_is_eligible(
    exercise_code: str,
    exercise: Exercise | None,
    available_equipment: AbstractSet[str],
    excluded_exercise_codes: AbstractSet[str],
) -> bool:
    """Check a single template/edit item against exclusion and equipment constraints."""
    if exercise_code in excluded_exercise_codes:
        return False
    if exercise is None:
        return False
    if exercise.equipment.upper() not in available_equipment:
        return False
    return True


def filter_eligible_templates(
    templates: Sequence[RoutineTemplate],
    exercises_by_code: Mapping[str, Exercise],
    criteria: RoutineEligibilityCriteria,
) -> list[RoutineTemplate]:
    """Filter catalog routine templates deterministically against athlete criteria.

    A template is eligible if and only if:
    1. It matches the athlete's target goal code (when specified).
    2. It supports the athlete's workout space and experience level, when the
       template declares explicit constraints for them.
    3. It has an explicit catalog adaptation for every limitation the athlete
       self-reported; a template with no declared adaptation for a reported
       limitation is never eligible.
    4. Every prescribed exercise exists in the catalog, is not one of the
       athlete's explicitly excluded exercises, and requires equipment
       available to the athlete (the 'NONE' equipment requirement is
       universally satisfied).

    Results are sorted deterministically:
    - Primary key: Closeness of estimated_duration_minutes to the athlete's target.
    - Secondary key: Template code ascending (guarantees tie-break consistency).
    """
    eligible: list[RoutineTemplate] = []
    # Normalize available equipment to uppercase and always include NONE
    available_equipment = {eq.upper() for eq in criteria.available_equipment} | {"NONE"}

    for template in templates:
        if not template_satisfies_non_item_constraints(template, criteria):
            continue

        all_exercises_eligible = all(
            exercise_item_is_eligible(
                item.exercise_code,
                exercises_by_code.get(item.exercise_code),
                available_equipment,
                criteria.excluded_exercise_codes,
            )
            for item in template.items
        )

        if all_exercises_eligible:
            eligible.append(template)

    # Deterministic ranking
    eligible.sort(
        key=lambda t: (
            abs(t.estimated_duration_minutes - criteria.target_duration_minutes),
            t.code,
        )
    )

    return eligible
