import pytest

from kinetiq.modules.catalog.domain.entities import (
    Exercise,
    ExercisePrescription,
    PrescriptionType,
    RoutineTemplate,
    RoutineTemplateItem,
)
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria
from kinetiq.modules.routines.domain.filtering import (
    filter_eligible_templates,
    normalize_excluded_exercise_codes,
)


@pytest.fixture
def catalog_exercises() -> dict[str, Exercise]:
    return {
        "ex-squat": Exercise(
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
        ),
        "ex-push-up": Exercise(
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
        ),
        "ex-pull-up": Exercise(
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
        ),
    }


@pytest.fixture
def sample_templates() -> list[RoutineTemplate]:
    return [
        RoutineTemplate(
            code="template-bodyweight-15",
            version=1,
            title="Bodyweight Foundation",
            description="15 min bodyweight workout",
            target_goal_code="goal-habit-consistency",
            estimated_duration_minutes=15,
            items=(
                RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),
                RoutineTemplateItem(exercise_code="ex-push-up", order=2, sets=3, repetitions=8),
            ),
        ),
        RoutineTemplate(
            code="template-pullup-20",
            version=1,
            title="Upper Body Pull",
            description="20 min bar workout",
            target_goal_code="goal-habit-consistency",
            estimated_duration_minutes=20,
            items=(
                RoutineTemplateItem(exercise_code="ex-pull-up", order=1, sets=3, repetitions=5),
                RoutineTemplateItem(exercise_code="ex-push-up", order=2, sets=3, repetitions=8),
            ),
        ),
        RoutineTemplate(
            code="template-other-goal-15",
            version=1,
            title="Strength Peak",
            description="Different goal",
            target_goal_code="goal-strength-peak",
            estimated_duration_minutes=15,
            items=(
                RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),
            ),
        ),
    ]


def test_filters_out_equipment_user_does_not_own(
    sample_templates: list[RoutineTemplate],
    catalog_exercises: dict[str, Exercise],
) -> None:
    # User only has no equipment
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit-consistency",
    )

    eligible = filter_eligible_templates(sample_templates, catalog_exercises, criteria)

    # template-pullup-20 is filtered out because user lacks PULL_UP_BAR
    # template-other-goal-15 is filtered out because goal does not match
    assert len(eligible) == 1
    assert eligible[0].code == "template-bodyweight-15"


def test_includes_equipment_templates_when_user_has_required_equipment(
    sample_templates: list[RoutineTemplate],
    catalog_exercises: dict[str, Exercise],
) -> None:
    # User has pull-up bar
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE", "PULL_UP_BAR"}),
        target_duration_minutes=20,
        experience_level="RETURNING",
        target_goal_code="goal-habit-consistency",
    )

    eligible = filter_eligible_templates(sample_templates, catalog_exercises, criteria)

    assert len(eligible) == 2
    # 20m target matches template-pullup-20 exactly (diff=0), so it comes first
    assert eligible[0].code == "template-pullup-20"
    # template-bodyweight-15 (diff=5) comes second
    assert eligible[1].code == "template-bodyweight-15"


def test_deterministic_tie_breaking_by_template_code(
    catalog_exercises: dict[str, Exercise],
) -> None:
    # Two templates with identical duration difference
    t_b = RoutineTemplate(
        code="template-b",
        version=1,
        title="B Routine",
        description="test",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
    )
    t_a = RoutineTemplate(
        code="template-a",
        version=1,
        title="A Routine",
        description="test",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
    )

    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
    )

    # Regardless of input order:
    result1 = filter_eligible_templates([t_b, t_a], catalog_exercises, criteria)
    result2 = filter_eligible_templates([t_a, t_b], catalog_exercises, criteria)

    assert [t.code for t in result1] == ["template-a", "template-b"]
    assert [t.code for t in result2] == ["template-a", "template-b"]


def test_filters_out_template_with_missing_catalog_exercise(
    catalog_exercises: dict[str, Exercise],
) -> None:
    corrupted_template = RoutineTemplate(
        code="template-corrupted",
        version=1,
        title="Corrupted",
        description="References nonexistent exercise",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(
            RoutineTemplateItem(
                exercise_code="ex-nonexistent",
                order=1,
                sets=1,
                repetitions=5,
            ),
        ),
    )

    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
    )

    eligible = filter_eligible_templates([corrupted_template], catalog_exercises, criteria)
    assert eligible == []


def test_excludes_template_containing_an_excluded_exercise(
    sample_templates: list[RoutineTemplate],
    catalog_exercises: dict[str, Exercise],
) -> None:
    """A profile exclusion must remove any template proposing that exercise,
    even when equipment and goal otherwise match."""
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE", "PULL_UP_BAR"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit-consistency",
        excluded_exercise_codes=frozenset({"ex-push-up"}),
    )

    eligible = filter_eligible_templates(sample_templates, catalog_exercises, criteria)

    # Both remaining goal-matching templates include ex-push-up, so neither is eligible.
    assert eligible == []


def test_excluded_exercise_does_not_affect_templates_without_it(
    catalog_exercises: dict[str, Exercise],
) -> None:
    squat_only_template = RoutineTemplate(
        code="template-squat-only",
        version=1,
        title="Squat Only",
        description="Just squats",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
    )
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
        excluded_exercise_codes=frozenset({"ex-push-up"}),
    )

    eligible = filter_eligible_templates([squat_only_template], catalog_exercises, criteria)
    assert len(eligible) == 1


def test_filters_out_template_that_does_not_support_workout_space(
    catalog_exercises: dict[str, Exercise],
) -> None:
    gym_only_template = RoutineTemplate(
        code="template-gym-only",
        version=1,
        title="Gym Only",
        description="Requires the gym",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
        supported_workout_spaces=frozenset({"GYM"}),
    )
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
        workout_space="LIVING_ROOM",
    )

    eligible = filter_eligible_templates([gym_only_template], catalog_exercises, criteria)
    assert eligible == []


def test_includes_template_when_workout_space_matches(
    catalog_exercises: dict[str, Exercise],
) -> None:
    gym_only_template = RoutineTemplate(
        code="template-gym-only",
        version=1,
        title="Gym Only",
        description="Requires the gym",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
        supported_workout_spaces=frozenset({"GYM"}),
    )
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
        workout_space="gym",  # Case-insensitive match
    )

    eligible = filter_eligible_templates([gym_only_template], catalog_exercises, criteria)
    assert len(eligible) == 1


def test_template_with_no_declared_workout_spaces_applies_everywhere(
    catalog_exercises: dict[str, Exercise],
) -> None:
    universal_template = RoutineTemplate(
        code="template-universal",
        version=1,
        title="Universal",
        description="No explicit space restriction",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
    )
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
        workout_space="ANY_UNUSUAL_SPACE",
    )

    eligible = filter_eligible_templates([universal_template], catalog_exercises, criteria)
    assert len(eligible) == 1


def test_filters_out_template_that_does_not_support_experience_level(
    catalog_exercises: dict[str, Exercise],
) -> None:
    advanced_template = RoutineTemplate(
        code="template-advanced",
        version=1,
        title="Advanced",
        description="Regulars only",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
        supported_experience_levels=frozenset({"REGULAR"}),
    )
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="STARTING",
        target_goal_code="goal-habit",
    )

    eligible = filter_eligible_templates([advanced_template], catalog_exercises, criteria)
    assert eligible == []


def test_filters_out_template_without_supported_adaptation_for_limitation(
    catalog_exercises: dict[str, Exercise],
) -> None:
    """A template with no declared adaptation for a reported limitation must
    never be eligible, even though it matches every other constraint."""
    plain_template = RoutineTemplate(
        code="template-plain",
        version=1,
        title="Plain",
        description="No limitation adaptations declared",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
    )
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
        limitations=frozenset({"KNEE_PAIN"}),
    )

    eligible = filter_eligible_templates([plain_template], catalog_exercises, criteria)
    assert eligible == []


def test_includes_template_with_matching_limitation_adaptation(
    catalog_exercises: dict[str, Exercise],
) -> None:
    adapted_template = RoutineTemplate(
        code="template-adapted",
        version=1,
        title="Knee-Friendly",
        description="Explicit knee pain adaptation",
        target_goal_code="goal-habit",
        estimated_duration_minutes=15,
        items=(RoutineTemplateItem(exercise_code="ex-squat", order=1, sets=3, repetitions=10),),
        supported_limitation_adaptations=frozenset({"KNEE_PAIN", "WRIST_PAIN"}),
    )
    criteria = RoutineEligibilityCriteria(
        available_equipment=frozenset({"NONE"}),
        target_duration_minutes=15,
        experience_level="RETURNING",
        target_goal_code="goal-habit",
        limitations=frozenset({"KNEE_PAIN"}),
    )

    eligible = filter_eligible_templates([adapted_template], catalog_exercises, criteria)
    assert len(eligible) == 1


def test_normalize_excluded_exercise_codes_keeps_only_known_catalog_codes() -> None:
    known_codes = {"ex-squat", "ex-push-up"}

    normalized = normalize_excluded_exercise_codes(
        ["ex-squat", " ex-push-up ", "not-a-real-exercise", "", "  "],
        known_codes,
    )

    assert normalized == frozenset({"ex-squat", "ex-push-up"})


def test_normalize_excluded_exercise_codes_never_infers_from_free_text() -> None:
    """Free-text medical descriptions must never be matched against catalog
    codes by inference; only exact, stable identifier matches are honored."""
    known_codes = {"ex-squat"}

    normalized = normalize_excluded_exercise_codes(
        ["no squats because of my knee", "squat"],
        known_codes,
    )

    assert normalized == frozenset()
