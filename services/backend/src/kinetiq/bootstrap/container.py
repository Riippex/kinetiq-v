from kinetiq.modules.catalog.infrastructure.repositories import DjangoCatalogRepository
from kinetiq.modules.goals.application import (
    GetActiveGoalUseCase,
    ListGoalRevisionsUseCase,
    SetGoalUseCase,
)
from kinetiq.modules.goals.infrastructure.repositories import DjangoGoalRepository
from kinetiq.modules.profiles.application import GetProfileUseCase, UpdateProfileUseCase
from kinetiq.modules.profiles.infrastructure.repositories import DjangoProfileRepository
from kinetiq.modules.routines.application import (
    AcceptRoutineUseCase,
    EditRoutineUseCase,
    GetCurrentRoutineUseCase,
    GetRoutineVersionUseCase,
    ProposeRoutineUseCase,
)
from kinetiq.modules.routines.infrastructure.repositories import DjangoRoutineRepository
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


def propose_routine() -> ProposeRoutineUseCase:
    return ProposeRoutineUseCase(
        catalog_repo=DjangoCatalogRepository(),
        profile_repo=DjangoProfileRepository(),
        goal_repo=DjangoGoalRepository(),
        routine_repo=DjangoRoutineRepository(),
    )


def edit_routine() -> EditRoutineUseCase:
    return EditRoutineUseCase(
        routine_repo=DjangoRoutineRepository(),
        catalog_repo=DjangoCatalogRepository(),
        profile_repo=DjangoProfileRepository(),
    )


def accept_routine() -> AcceptRoutineUseCase:
    return AcceptRoutineUseCase(routine_repo=DjangoRoutineRepository())


def get_current_routine() -> GetCurrentRoutineUseCase:
    return GetCurrentRoutineUseCase(routine_repo=DjangoRoutineRepository())


def get_routine_version() -> GetRoutineVersionUseCase:
    return GetRoutineVersionUseCase(routine_repo=DjangoRoutineRepository())
