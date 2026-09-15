from kinetiq.modules.catalog.domain.entities import (
    Exercise,
    ExercisePrescription,
    GoalDefinition,
    PrescriptionType,
    RoutineTemplate,
    RoutineTemplateItem,
)

CANONICAL_GOALS: tuple[GoalDefinition, ...] = (
    GoalDefinition(
        code="goal-habit-consistency-v1",
        revision=1,
        name="Habit Consistency: Bodyweight Foundation",
        description=(
            "Build a regular habit of home movement with bodyweight exercises "
            "to restore movement consistency."
        ),
        measure="weekly_completed_sessions",
        baseline=0.0,
        target=3.0,
        unit="sessions/week",
    ),
)

CANONICAL_EXERCISES: tuple[Exercise, ...] = (
    Exercise(
        code="exercise-bodyweight-squat-v1",
        version=1,
        slug="bodyweight-squat",
        name="Bodyweight Squat",
        category="LOWER_BODY",
        equipment="NONE",
        prescription=ExercisePrescription(
            prescription_type=PrescriptionType.REPETITIONS,
            default_sets=3,
            default_repetitions=10,
            default_rest_seconds=60,
        ),
        vision_supported=True,
        vision_exercise_key="bodyweight_squat",
    ),
    Exercise(
        code="exercise-push-up-v1",
        version=1,
        slug="push-up",
        name="Push-Up",
        category="UPPER_BODY",
        equipment="NONE",
        prescription=ExercisePrescription(
            prescription_type=PrescriptionType.REPETITIONS,
            default_sets=3,
            default_repetitions=8,
            default_rest_seconds=60,
        ),
        vision_supported=True,
        vision_exercise_key="push_up",
    ),
    Exercise(
        code="exercise-plank-v1",
        version=1,
        slug="plank",
        name="Plank",
        category="CORE",
        equipment="NONE",
        prescription=ExercisePrescription(
            prescription_type=PrescriptionType.DURATION,
            default_sets=3,
            default_duration_seconds=30,
            default_rest_seconds=45,
        ),
        vision_supported=True,
        vision_exercise_key="plank",
    ),
    Exercise(
        code="exercise-glute-bridge-v1",
        version=1,
        slug="glute-bridge",
        name="Glute Bridge",
        category="LOWER_BODY",
        equipment="NONE",
        prescription=ExercisePrescription(
            prescription_type=PrescriptionType.REPETITIONS,
            default_sets=3,
            default_repetitions=12,
            default_rest_seconds=45,
        ),
        vision_supported=True,
        vision_exercise_key="glute_bridge",
    ),
    # Negative boundary control: Valid catalog exercise, but vision tracking is NOT
    # supported by the Vision model.
    Exercise(
        code="exercise-pull-up-v1",
        version=1,
        slug="pull-up",
        name="Pull-Up",
        category="UPPER_BODY",
        equipment="PULL_UP_BAR",
        prescription=ExercisePrescription(
            prescription_type=PrescriptionType.REPETITIONS,
            default_sets=3,
            default_repetitions=5,
            default_rest_seconds=90,
        ),
        vision_supported=False,
        vision_exercise_key=None,
    ),
)

CANONICAL_TEMPLATES: tuple[RoutineTemplate, ...] = (
    RoutineTemplate(
        code="template-full-body-foundation-v1",
        version=1,
        title="Full Body Foundation",
        description=(
            "An introductory full-body routine designed to build consistency without equipment."
        ),
        target_goal_code="goal-habit-consistency-v1",
        estimated_duration_minutes=15,
        items=(
            RoutineTemplateItem(
                exercise_code="exercise-bodyweight-squat-v1",
                order=1,
                sets=3,
                repetitions=10,
                rest_seconds=60,
            ),
            RoutineTemplateItem(
                exercise_code="exercise-push-up-v1",
                order=2,
                sets=3,
                repetitions=8,
                rest_seconds=60,
            ),
            RoutineTemplateItem(
                exercise_code="exercise-glute-bridge-v1",
                order=3,
                sets=3,
                repetitions=12,
                rest_seconds=45,
            ),
            RoutineTemplateItem(
                exercise_code="exercise-plank-v1",
                order=4,
                sets=3,
                duration_seconds=30,
                rest_seconds=45,
            ),
        ),
    ),
)
