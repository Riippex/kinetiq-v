import pytest

from kinetiq.modules.catalog.domain.entities import (
    Exercise,
    ExercisePrescription,
    PrescriptionType,
    RoutineTemplate,
    RoutineTemplateItem,
)
from kinetiq.modules.routines.domain.entities import RoutineEligibilityCriteria
from kinetiq.modules.routines.domain.filtering import filter_eligible_templates


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
