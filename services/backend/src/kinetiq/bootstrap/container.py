from kinetiq.modules.goals.application import (
    GetActiveGoalUseCase,
    ListGoalRevisionsUseCase,
    SetGoalUseCase,
)
from kinetiq.modules.goals.infrastructure.repositories import DjangoGoalRepository
from kinetiq.modules.profiles.application import GetProfileUseCase, UpdateProfileUseCase
from kinetiq.modules.profiles.infrastructure.repositories import DjangoProfileRepository
from kinetiq.modules.workouts.application import PrepareWorkoutSession
from kinetiq.modules.workouts.infrastructure.repositories import DjangoSessionPreparationRepository


def prepare_workout_session() -> PrepareWorkoutSession:
    return PrepareWorkoutSession(DjangoSessionPreparationRepository())


def get_profile() -> GetProfileUseCase:
    return GetProfileUseCase(DjangoProfileRepository())


def update_profile() -> UpdateProfileUseCase:
    return UpdateProfileUseCase(DjangoProfileRepository())


def get_active_goal() -> GetActiveGoalUseCase:
    return GetActiveGoalUseCase(DjangoGoalRepository())


def list_goal_revisions() -> ListGoalRevisionsUseCase:
    return ListGoalRevisionsUseCase(DjangoGoalRepository())


def set_goal() -> SetGoalUseCase:
    return SetGoalUseCase(DjangoGoalRepository())
