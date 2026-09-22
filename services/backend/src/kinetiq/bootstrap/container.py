import redis
from django.conf import settings as django_settings

from kinetiq.modules.catalog.domain.entities import Exercise
from kinetiq.modules.catalog.infrastructure.repositories import DjangoCatalogRepository
from kinetiq.modules.goals.application import (
    GetActiveGoalUseCase,
    ListGoalRevisionsUseCase,
    SetGoalUseCase,
)
from kinetiq.modules.goals.infrastructure.repositories import DjangoGoalRepository
from kinetiq.modules.identity.application import SubjectDirectory
from kinetiq.modules.identity.infrastructure.subject_directory import DjangoSubjectDirectory
from kinetiq.modules.integrations import VisionClientConfig, VisionRestAdapter
from kinetiq.modules.integrations.application import IdempotentToolRunner
from kinetiq.modules.integrations.infrastructure.receipt_store import DjangoToolReceiptStore
from kinetiq.modules.media.application import (
    DeleteProgressPhotoUseCase,
    FinalizeProgressPhotoUseCase,
    ListProgressPhotosUseCase,
    MediaCleanupRepository,
    MediaCleanupService,
    MediaStoragePort,
    RequestProgressPhotoUploadUseCase,
)
from kinetiq.modules.media.infrastructure.repositories import (
    DjangoMediaCleanupRepository,
    DjangoProgressPhotoRepository,
    LogMediaEventPublisher,
)
from kinetiq.modules.media.infrastructure.repositories import (
    DjangoWorkoutSessionLookup as DjangoMediaWorkoutSessionLookup,
)
from kinetiq.modules.media.infrastructure.storage import (
    InMemoryMediaStorageAdapter,
    S3MediaStorageAdapter,
)
from kinetiq.modules.profiles.application import GetProfileUseCase, UpdateProfileUseCase
from kinetiq.modules.profiles.infrastructure.repositories import DjangoProfileRepository
from kinetiq.modules.progress.application import GetProgressSummaryUseCase
from kinetiq.modules.progress.infrastructure.repositories import (
    DjangoGoalLookup as DjangoProgressGoalLookup,
)
from kinetiq.modules.progress.infrastructure.repositories import (
    DjangoProfileLookup as DjangoProgressProfileLookup,
)
from kinetiq.modules.progress.infrastructure.repositories import (
    DjangoSessionHistoryLookup,
)
from kinetiq.modules.routines.application import (
    AcceptRoutineUseCase,
    EditRoutineUseCase,
    GetCurrentRoutineUseCase,
    GetRoutineVersionUseCase,
    ProposeRoutineUseCase,
)
from kinetiq.modules.routines.infrastructure.repositories import DjangoRoutineRepository
from kinetiq.modules.workouts.application import (
    AbandonWorkoutSessionUseCase,
    ConfirmSessionTargetUseCase,
    DisableDynamicModeUseCase,
    FinishWorkoutSessionUseCase,
    GetDisplaySessionStateUseCase,
    GetLatestWorkoutSessionUseCase,
    GetSessionDynamicChallengesUseCase,
    GetWorkoutSessionUseCase,
    IssueDisplayPairingCodeUseCase,
    ListVisionCandidatesUseCase,
    PairDisplayDeviceUseCase,
    PauseWorkoutSessionUseCase,
    PollVisionObservationsUseCase,
    PrepareWorkoutSession,
    RecordSessionFeedbackUseCase,
    ResumeWorkoutSessionUseCase,
    SkipDynamicChallengeUseCase,
    StartSessionVisionAnalysisUseCase,
    StartWorkoutSessionUseCase,
)
from kinetiq.modules.workouts.application.ports import SessionTransientStore
from kinetiq.modules.workouts.domain.display_pairing import (
    DisplayPairingStore,
    InMemoryDisplayPairingStore,
)
from kinetiq.modules.workouts.infrastructure.display_pairing_store import (
    RedisDisplayPairingStore,
)
from kinetiq.modules.workouts.infrastructure.repositories import (
    DjangoLatestSessionReader,
    DjangoRoutineItemLookup,
    DjangoSessionLifecycleRepository,
    DjangoSessionPreparationRepository,
    DjangoUserProfileLookup,
)
from kinetiq.modules.workouts.infrastructure.transient_store import RedisSessionTransientStore
from kinetiq.modules.workouts.infrastructure.vision_observation_adapter import (
    VisionRestObservationAdapter,
)

_MEMORY_DISPLAY_PAIRING_STORE = InMemoryDisplayPairingStore()
_redis_client: "redis.Redis | None" = None


def _get_redis_client() -> "redis.Redis":
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(django_settings.REDIS_URL, decode_responses=True)
    return _redis_client


def get_display_pairing_store() -> DisplayPairingStore:
    # Production uses the shared Redis store so a phone and a TV on different
    # worker processes see one pairing and ownership claims are atomic. The
    # process-local store is selected only by the test settings.
    if django_settings.DISPLAY_PAIRING_STORE == "memory":
        return _MEMORY_DISPLAY_PAIRING_STORE
    return RedisDisplayPairingStore(_get_redis_client())


def issue_display_pairing_code() -> IssueDisplayPairingCodeUseCase:
    return IssueDisplayPairingCodeUseCase(get_display_pairing_store())


def pair_display_device() -> PairDisplayDeviceUseCase:
    return PairDisplayDeviceUseCase(
        get_display_pairing_store(), DjangoSessionLifecycleRepository()
    )


def get_display_session_state() -> GetDisplaySessionStateUseCase:
    return GetDisplaySessionStateUseCase(
        get_display_pairing_store(),
        DjangoSessionLifecycleRepository(),
        get_session_transient_store(),
    )


def get_session_transient_store() -> SessionTransientStore:
    return RedisSessionTransientStore()


def get_vision_rest_adapter() -> VisionRestAdapter:
    headers: dict[str, str] = {}
    if django_settings.VISION_SERVICE_CREDENTIAL:
        headers["Authorization"] = f"Bearer {django_settings.VISION_SERVICE_CREDENTIAL}"
    return VisionRestAdapter(
        config=VisionClientConfig(
            base_url=django_settings.VISION_BASE_URL,
            timeout_seconds=django_settings.VISION_TIMEOUT_SECONDS,
            default_headers=headers,
        )
    )


def prepare_workout_session() -> PrepareWorkoutSession:
    return PrepareWorkoutSession(DjangoSessionPreparationRepository())


def confirm_session_target() -> ConfirmSessionTargetUseCase:
    return ConfirmSessionTargetUseCase(
        DjangoSessionLifecycleRepository(), get_vision_rest_adapter()
    )


def start_session_vision_analysis() -> StartSessionVisionAnalysisUseCase:
    return StartSessionVisionAnalysisUseCase(
        DjangoSessionLifecycleRepository(), get_vision_rest_adapter(), DjangoRoutineItemLookup()
    )


def list_vision_candidates() -> ListVisionCandidatesUseCase:
    return ListVisionCandidatesUseCase(
        DjangoSessionLifecycleRepository(), get_vision_rest_adapter()
    )


def poll_vision_observations() -> PollVisionObservationsUseCase:
    return PollVisionObservationsUseCase(
        DjangoSessionLifecycleRepository(),
        VisionRestObservationAdapter(get_vision_rest_adapter()),
        get_session_transient_store(),
    )


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


def get_latest_workout_session() -> GetLatestWorkoutSessionUseCase:
    return GetLatestWorkoutSessionUseCase(DjangoLatestSessionReader())


def get_idempotent_tool_runner() -> IdempotentToolRunner:
    return IdempotentToolRunner(DjangoToolReceiptStore())


def get_subject_directory() -> SubjectDirectory:
    return DjangoSubjectDirectory()


def record_session_feedback() -> RecordSessionFeedbackUseCase:
    return RecordSessionFeedbackUseCase(DjangoSessionLifecycleRepository())


def abandon_workout_session() -> AbandonWorkoutSessionUseCase:
    return AbandonWorkoutSessionUseCase(DjangoSessionLifecycleRepository())


def get_session_dynamic_challenges() -> GetSessionDynamicChallengesUseCase:
    return GetSessionDynamicChallengesUseCase(
        DjangoSessionLifecycleRepository(),
        DjangoRoutineItemLookup(),
        DjangoUserProfileLookup(),
    )


def skip_dynamic_challenge() -> SkipDynamicChallengeUseCase:
    return SkipDynamicChallengeUseCase(
        DjangoSessionLifecycleRepository(),
        DjangoRoutineItemLookup(),
        DjangoUserProfileLookup(),
    )


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
        progress_summary_use_case=get_progress_summary(),
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


def get_progress_summary() -> GetProgressSummaryUseCase:
    return GetProgressSummaryUseCase(
        session_history_lookup=DjangoSessionHistoryLookup(),
        profile_lookup=DjangoProgressProfileLookup(),
        goal_lookup=DjangoProgressGoalLookup(),
    )


_in_memory_media_storage: InMemoryMediaStorageAdapter | None = None


def get_media_storage() -> MediaStoragePort:
    global _in_memory_media_storage
    # The in-memory adapter is not durable (per-process, discarded on
    # restart) and must be an explicit development/test choice, never a
    # silent fallback: swallowing an S3 misconfiguration here would make
    # every photo upload/deletion a no-op against real storage without any
    # error surfacing that S3 is unreachable.
    if getattr(django_settings, "USE_IN_MEMORY_MEDIA_STORAGE", False):
        if _in_memory_media_storage is None:
            _in_memory_media_storage = InMemoryMediaStorageAdapter()
        return _in_memory_media_storage

    return S3MediaStorageAdapter(
        bucket_name=django_settings.MEDIA_S3_BUCKET,
        region=django_settings.MEDIA_S3_REGION,
        endpoint_url=getattr(django_settings, "MEDIA_S3_ENDPOINT_URL", None),
    )


def request_progress_photo_upload() -> RequestProgressPhotoUploadUseCase:
    return RequestProgressPhotoUploadUseCase(
        repository=DjangoProgressPhotoRepository(),
        storage=get_media_storage(),
        session_lookup=DjangoMediaWorkoutSessionLookup(),
        ttl_seconds=getattr(django_settings, "MEDIA_PRESIGNED_EXPIRY_SECONDS", 900),
    )


def get_media_cleanup_repository() -> MediaCleanupRepository:
    return DjangoMediaCleanupRepository()


def process_media_cleanup() -> MediaCleanupService:
    return MediaCleanupService(
        repository=get_media_cleanup_repository(),
        storage=get_media_storage(),
        event_publisher=LogMediaEventPublisher(),
    )


def finalize_progress_photo() -> FinalizeProgressPhotoUseCase:
    return FinalizeProgressPhotoUseCase(
        repository=DjangoProgressPhotoRepository(),
        storage=get_media_storage(),
        cleanup=process_media_cleanup(),
        ttl_seconds=getattr(django_settings, "MEDIA_PRESIGNED_EXPIRY_SECONDS", 900),
    )


def list_progress_photos() -> ListProgressPhotosUseCase:
    return ListProgressPhotosUseCase(
        repository=DjangoProgressPhotoRepository(),
        storage=get_media_storage(),
        ttl_seconds=getattr(django_settings, "MEDIA_PRESIGNED_EXPIRY_SECONDS", 900),
    )


def delete_progress_photo() -> DeleteProgressPhotoUseCase:
    return DeleteProgressPhotoUseCase(
        repository=DjangoProgressPhotoRepository(),
        cleanup=process_media_cleanup(),
    )
