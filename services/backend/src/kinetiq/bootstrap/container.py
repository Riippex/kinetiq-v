from kinetiq.modules.catalog.domain.entities import Exercise
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
from kinetiq.modules.integrations import VisionRestAdapter
from kinetiq.modules.workouts.application import (
    AbandonWorkoutSessionUseCase,
    ConfirmSessionTargetUseCase,
    DisableDynamicModeUseCase,
    FinishWorkoutSessionUseCase,
    GetWorkoutSessionUseCase,
    PauseWorkoutSessionUseCase,
    PrepareWorkoutSession,
    RecordSessionFeedbackUseCase,
    ResumeWorkoutSessionUseCase,
    StartWorkoutSessionUseCase,
)
from kinetiq.modules.workouts.application.ports import SessionTransientStore
from kinetiq.modules.workouts.infrastructure.repositories import (
    DjangoRoutineItemLookup,
    DjangoSessionLifecycleRepository,
    DjangoSessionPreparationRepository,
)
from kinetiq.modules.workouts.infrastructure.transient_store import RedisSessionTransientStore


def get_session_transient_store() -> SessionTransientStore:
    return RedisSessionTransientStore()


def get_vision_rest_adapter() -> VisionRestAdapter:
    return VisionRestAdapter()


def prepare_workout_session() -> PrepareWorkoutSession:
    return PrepareWorkoutSession(DjangoSessionPreparationRepository())


def confirm_session_target() -> ConfirmSessionTargetUseCase:
    return ConfirmSessionTargetUseCase(DjangoSessionLifecycleRepository())




def start_workout_session() -> StartWorkoutSessionUseCase:
    return StartWorkoutSessionUseCase(DjangoSessionLifecycleRepository())


def pause_workout_session() -> PauseWorkoutSessionUseCase:
    return PauseWorkoutSessionUseCase(DjangoSessionLifecycleRepository())


def resume_workout_session() -> ResumeWorkoutSessionUseCase:
    return ResumeWorkoutSessionUseCase(DjangoSessionLifecycleRepository())


def disable_dynamic_mode() -> DisableDynamicModeUseCase:
    return DisableDynamicModeUseCase(DjangoSessionLifecycleRepository())


def finish_workout_session() -> FinishWorkoutSessionUseCase:
    return FinishWorkoutSessionUseCase(
        DjangoSessionLifecycleRepository(), DjangoRoutineItemLookup()
    )


def get_workout_session() -> GetWorkoutSessionUseCase:
    return GetWorkoutSessionUseCase(DjangoSessionLifecycleRepository())


def record_session_feedback() -> RecordSessionFeedbackUseCase:
    return RecordSessionFeedbackUseCase(DjangoSessionLifecycleRepository())


def abandon_workout_session() -> AbandonWorkoutSessionUseCase:
    return AbandonWorkoutSessionUseCase(DjangoSessionLifecycleRepository())



def list_catalog_exercises() -> list[Exercise]:
    return DjangoCatalogRepository().list_exercises()


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
