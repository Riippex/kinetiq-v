from kinetiq.modules.workouts.application import PrepareWorkoutSession
from kinetiq.modules.workouts.infrastructure.repositories import DjangoSessionPreparationRepository


def prepare_workout_session() -> PrepareWorkoutSession:
    return PrepareWorkoutSession(DjangoSessionPreparationRepository())
