from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

import strawberry
from strawberry.types import Info

from kinetiq.bootstrap.container import (
    abandon_workout_session,
    accept_routine,
    disable_dynamic_mode,
    edit_routine,
    finish_workout_session,
    get_active_goal,
    get_current_routine,
    get_profile,
    get_routine_version,
    get_session_transient_store,
    get_workout_session,
    list_catalog_exercises,
    list_goal_revisions,
    pause_workout_session,
    prepare_workout_session,
    propose_routine,
    record_session_feedback,
    resume_workout_session,
    set_goal,
    start_workout_session,
    update_profile,
)
from kinetiq.modules.catalog.domain.entities import Exercise
from kinetiq.modules.goals.application import SetGoalCommand
from kinetiq.modules.goals.domain import GoalRevision
from kinetiq.modules.profiles.application import UpdateProfileCommand
from kinetiq.modules.profiles.domain import ExperienceLevel, UserProfile
from kinetiq.modules.routines.application import EditRoutineCommand, RoutineEditItem
from kinetiq.modules.routines.domain.entities import Routine
from kinetiq.modules.routines.domain.errors import (
    InvalidRoutineEditError,
    NoEligibleRoutineTemplatesError,
    RoutineNotFoundError,
    UnsupportedLimitationError,
)
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application import (
    FinishSessionCommand,
    IdempotencyConflict,
    InconsistentPerformedSetMeasurementError,
    PrepareSessionCommand,
    RecordSessionFeedbackCommand,
    RevisionConflict,
    RoutineUnavailable,
    SessionLifecycleCommand,
    SessionNotFound,
    TransientSessionUpdate,
    UnknownRoutineExerciseError,
)
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DuplicatePerformedSetError,
    DynamicChallengeFrequency,
    DynamicChallengeType,
    InvalidSessionStateTransition,
    ObservationCoverage,
    PerformedSet,
    SessionFeedback,
    SessionIntensity,
    SessionMode,
    WorkoutSession,
)
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord


@strawberry.enum(name="ExperienceLevel")
class ExperienceLevelType(Enum):
    STARTING = "STARTING"
    RETURNING = "RETURNING"
    REGULAR = "REGULAR"


@strawberry.enum(name="SessionMode")
class SessionModeType(Enum):
    NORMAL = "NORMAL"
    DYNAMIC = "DYNAMIC"


@strawberry.enum(name="SessionIntensity")
class SessionIntensityType(Enum):
    LIGHTER = "LIGHTER"
    PLANNED = "PLANNED"
    CHALLENGING = "CHALLENGING"


@strawberry.enum(name="CoachingTone")
class CoachingToneType(Enum):
    CALM = "CALM"
    TECHNICAL = "TECHNICAL"
    MOTIVATIONAL = "MOTIVATIONAL"
    EDGY = "EDGY"


@strawberry.enum(name="DynamicChallengeFrequency")
class DynamicChallengeFrequencyType(Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


@strawberry.enum(name="DynamicChallengeType")
class DynamicChallengeTypeType(Enum):
    HOLD_POSE = "HOLD_POSE"
    MIRROR_POSE = "MIRROR_POSE"
    QUICK_REPS = "QUICK_REPS"
    RECOVERY = "RECOVERY"


@strawberry.enum(name="SessionState")
class SessionStateType(Enum):
    READY = "READY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


@strawberry.enum(name="PauseReason")
class PauseReasonType(Enum):
    USER_REQUEST = "USER_REQUEST"
    VISIBILITY = "VISIBILITY"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    CAMERA_DISCONNECTED = "CAMERA_DISCONNECTED"


@strawberry.type
class ServiceStatus:
    name: str
    version: str
    ready: bool


@strawberry.type(name="Profile")
class ProfileType:
    id: strawberry.ID
    display_name: str
    timezone: str
    experience_level: ExperienceLevelType
    availability_days_per_week: int
    target_session_minutes: int
    available_equipment: list[str]
    workout_space: str
    preferences: list[str]
    exclusions: list[str]
    limitations: list[str]
    coaching_tone: CoachingToneType
    updated_at: datetime


@strawberry.type(name="Goal")
class GoalType:
    id: strawberry.ID
    revision: int
    description: str
    measure: str | None
    baseline: float | None
    target: float | None
    unit: str | None
    created_at: datetime


@strawberry.type(name="RoutineItem")
class RoutineItemType:
    exercise: "ExerciseType"
    order: int
    sets: int
    repetitions: int | None
    duration_seconds: int | None


@strawberry.type(name="Exercise")
class ExerciseType:
    id: strawberry.ID
    version: int
    name: str
    vision_supported: bool


@strawberry.type(name="Routine")
class RoutineType:
    id: strawberry.ID
    version: int
    title: str
    rationale: str
    items: list[RoutineItemType]
    accepted: bool


@strawberry.type(name="DynamicSessionConfiguration")
class DynamicSessionConfigurationType:
    frequency: DynamicChallengeFrequencyType
    allowed_challenge_types: list[DynamicChallengeTypeType]
    scoring_enabled: bool
    narration_enabled: bool


@strawberry.type(name="SessionConfiguration")
class SessionConfigurationType:
    requested_mode: SessionModeType
    active_mode: SessionModeType
    intensity: SessionIntensityType
    coaching_tone: CoachingToneType
    capture_device_id: strawberry.ID
    display_device_id: strawberry.ID | None
    prompt_for_progress_photo: bool
    dynamic: DynamicSessionConfigurationType | None


@strawberry.type(name="PerformedSet")
class PerformedSetType:
    exercise_id: strawberry.ID
    set_order: int
    repetitions: int | None
    duration_seconds: int | None


@strawberry.type(name="ObservationCoverage")
class ObservationCoverageType:
    coverage_ratio: float
    tracked_seconds: int
    total_seconds: int
    fully_visible_ratio: float
    untracked_reasons: list[str]


@strawberry.type(name="SessionFeedback")
class SessionFeedbackType:
    perceived_effort: int | None
    comments: str | None


@strawberry.type(name="WorkoutSession")
class WorkoutSessionType:
    id: strawberry.ID
    revision: int
    routine: RoutineType
    state: SessionStateType
    configuration: SessionConfigurationType
    pause_reason: PauseReasonType | None
    confirmed_repetitions: int
    performed_sets: list[PerformedSetType]
    observation_coverage: ObservationCoverageType | None
    feedback: SessionFeedbackType | None
    updated_at: datetime


@strawberry.type
class DomainError:
    code: str
    message: str
    field: str | None = None


@strawberry.type(name="ProfileResult")
class ProfileResultType:
    profile: ProfileType | None
    errors: list[DomainError]


@strawberry.type(name="GoalResult")
class GoalResultType:
    goal: GoalType | None
    errors: list[DomainError]


@strawberry.type(name="SessionResult")
class SessionResultType:
    session: WorkoutSessionType | None
    errors: list[DomainError]


@strawberry.type(name="RoutineResult")
class RoutineResultType:
    routine: RoutineType | None
    errors: list[DomainError]


@strawberry.input
class RoutineEditItemInput:
    exercise_id: strawberry.ID
    order: int
    sets: int
    repetitions: int | None = None
    duration_seconds: int | None = None


@strawberry.input
class EditRoutineInput:
    routine_id: strawberry.ID
    items: list[RoutineEditItemInput]
    title: str | None = None
    base_version: int | None = None


@strawberry.input
class UpdateProfileInput:
    display_name: str | None = None
    timezone: str | None = None
    experience_level: ExperienceLevelType | None = None
    availability_days_per_week: int | None = None
    target_session_minutes: int | None = None
    available_equipment: list[str] | None = None
    workout_space: str | None = None
    preferences: list[str] | None = None
    exclusions: list[str] | None = None
    limitations: list[str] | None = None
    coaching_tone: CoachingToneType | None = None


@strawberry.input
class SetGoalInput:
    description: str
    goal_id: strawberry.ID | None = None
    measure: str | None = None
    baseline: float | None = None
    target: float | None = None
    unit: str | None = None


@strawberry.input
class DynamicSessionConfigurationInput:
    allowed_challenge_types: list[DynamicChallengeTypeType]
    frequency: DynamicChallengeFrequencyType = DynamicChallengeFrequencyType.STANDARD
    scoring_enabled: bool = True
    narration_enabled: bool = True


@strawberry.input
class PrepareSessionInput:
    routine_id: strawberry.ID
    routine_version: int
    mode: SessionModeType
    coaching_tone: CoachingToneType
    capture_device_id: strawberry.ID
    idempotency_key: str
    intensity: SessionIntensityType = SessionIntensityType.PLANNED
    display_device_id: strawberry.ID | None = None
    prompt_for_progress_photo: bool = True
    dynamic: DynamicSessionConfigurationInput | None = None


@strawberry.input
class SessionCommandInput:
    session_id: strawberry.ID
    expected_revision: int
    idempotency_key: str


@strawberry.input
class PerformedSetInput:
    exercise_id: strawberry.ID
    set_order: int
    repetitions: int | None = None
    duration_seconds: int | None = None


@strawberry.input
class ObservationCoverageInput:
    coverage_ratio: float
    tracked_seconds: int
    total_seconds: int
    fully_visible_ratio: float = 1.0
    untracked_reasons: list[str] = strawberry.field(default_factory=list)


@strawberry.input
class SessionFeedbackInput:
    perceived_effort: int | None = None
    comments: str | None = None


@strawberry.type(name="TransientSessionUpdate")
class TransientSessionUpdateType:
    session_id: strawberry.ID
    active_exercise_id: strawberry.ID | None = None
    current_repetitions: int | None = None
    current_duration_seconds: int | None = None
    pose_confidence: float | None = None
    visibility_status: str = "VISIBLE"
    timestamp: str | None = None


@strawberry.input
class TransientSessionUpdateInput:
    session_id: strawberry.ID
    active_exercise_id: strawberry.ID | None = None
    current_repetitions: int | None = None
    current_duration_seconds: int | None = None
    pose_confidence: float | None = None
    visibility_status: str = "VISIBLE"
    timestamp: str | None = None


@strawberry.type(name="TransientSessionUpdateResult")
class TransientSessionUpdateResultType:
    success: bool
    errors: list[DomainError]


@strawberry.type
class Query:
    @strawberry.field
    def service_status(self) -> ServiceStatus:
        return ServiceStatus(name="kinetiq-backend", version="0.1.0", ready=True)

    @strawberry.field
    def me(self, info: Info[Any, None]) -> ProfileType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError("AUTHENTICATION_REQUIRED: Sign in before accessing profile")
        profile = get_profile().execute(owner_id)
        return _to_profile_graphql(profile)

    @strawberry.field
    def session(
        self, info: Info[Any, None], id: strawberry.ID
    ) -> WorkoutSessionType | None:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError("AUTHENTICATION_REQUIRED: Sign in before accessing session")
        try:
            session_uuid = UUID(str(id))
        except (ValueError, TypeError):
            return None

        session = get_workout_session().execute(owner_id=owner_id, session_id=session_uuid)
        if session is None:
            return None
        routine = get_routine_version().execute(
            owner_id, session.routine_id, session.routine_version
        )
        if routine is None:
            return None
        return _to_workout_session_graphql(session, routine)

    @strawberry.field
    def goals(self, info: Info[Any, None]) -> list[GoalType]:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError("AUTHENTICATION_REQUIRED: Sign in before accessing goals")
        revisions = list_goal_revisions().execute(owner_id)
        return [_to_goal_graphql(rev) for rev in revisions]

    @strawberry.field
    def active_goal(self, info: Info[Any, None]) -> GoalType | None:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError("AUTHENTICATION_REQUIRED: Sign in before accessing active goal")
        goal = get_active_goal().execute(owner_id)
        if goal is None:
            return None
        return _to_goal_graphql(goal)

    @strawberry.field
    def current_routine(self, info: Info[Any, None]) -> RoutineType | None:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError("AUTHENTICATION_REQUIRED: Sign in before accessing routines")
        routine = get_current_routine().execute(owner_id)
        if routine is None:
            return None
        return _to_routine_graphql(routine)

    @strawberry.field
    def routine(
        self, info: Info[Any, None], id: strawberry.ID, version: int
    ) -> RoutineType | None:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError("AUTHENTICATION_REQUIRED: Sign in before accessing routines")
        routine = get_routine_version().execute(owner_id, UUID(str(id)), version)
        if routine is None:
            return None
        return _to_routine_graphql(routine)

    @strawberry.field
    def exercises(self, info: Info[Any, None]) -> list[ExerciseType]:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError(
                "AUTHENTICATION_REQUIRED: Sign in before accessing the exercise catalog"
            )
        catalog_exercises = list_catalog_exercises()
        return [_to_exercise_graphql(ex) for ex in catalog_exercises]

    @strawberry.field
    def transient_session_state(
        self, info: Info[Any, None], session_id: strawberry.ID
    ) -> TransientSessionUpdateType | None:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            raise PermissionError(
                "AUTHENTICATION_REQUIRED: Sign in before accessing transient state"
            )
        try:
            session_uuid = UUID(str(session_id))
        except (ValueError, TypeError):
            return None

        session = get_workout_session().execute(owner_id=owner_id, session_id=session_uuid)
        if session is None:
            return None

        store = get_session_transient_store()
        update = store.get_transient_update(session_uuid)
        if update is None:
            return None

        return TransientSessionUpdateType(
            session_id=strawberry.ID(str(update.session_id)),
            active_exercise_id=(
                strawberry.ID(update.active_exercise_id)
                if update.active_exercise_id
                else None
            ),
            current_repetitions=update.current_repetitions,
            current_duration_seconds=update.current_duration_seconds,
            pose_confidence=update.pose_confidence,
            visibility_status=update.visibility_status,
            timestamp=update.timestamp,
        )



@strawberry.type
class Mutation:
    @strawberry.mutation
    def update_profile(
        self, info: Info[Any, None], input: UpdateProfileInput
    ) -> ProfileResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return ProfileResultType(
                profile=None,
                errors=[
                    DomainError(
                        code="AUTHENTICATION_REQUIRED",
                        message="Sign in before updating profile",
                    )
                ],
            )
        try:
            command = UpdateProfileCommand(
                display_name=input.display_name,
                timezone_name=input.timezone,
                experience_level=(
                    ExperienceLevel(input.experience_level.value)
                    if input.experience_level is not None
                    else None
                ),
                availability_days_per_week=input.availability_days_per_week,
                target_session_minutes=input.target_session_minutes,
                available_equipment=(
                    tuple(input.available_equipment)
                    if input.available_equipment is not None
                    else None
                ),
                workout_space=input.workout_space,
                preferences=tuple(input.preferences) if input.preferences is not None else None,
                exclusions=tuple(input.exclusions) if input.exclusions is not None else None,
                limitations=tuple(input.limitations) if input.limitations is not None else None,
                coaching_tone=(
                    CoachingTone(input.coaching_tone.value)
                    if input.coaching_tone is not None
                    else None
                ),
            )
            profile = update_profile().execute(owner_id, command)
            return ProfileResultType(profile=_to_profile_graphql(profile), errors=[])
        except (ValueError, TypeError) as error:
            return ProfileResultType(
                profile=None,
                errors=[DomainError(code="INVALID_PROFILE", message=str(error))],
            )

    @strawberry.mutation
    def set_goal(self, info: Info[Any, None], input: SetGoalInput) -> GoalResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return GoalResultType(
                goal=None,
                errors=[
                    DomainError(
                        code="AUTHENTICATION_REQUIRED",
                        message="Sign in before setting a goal",
                    )
                ],
            )
        try:
            goal_uuid = UUID(str(input.goal_id)) if input.goal_id else None
            command = SetGoalCommand(
                goal_id=goal_uuid,
                description=input.description,
                measure=input.measure,
                baseline=input.baseline,
                target=input.target,
                unit=input.unit,
            )
            goal = set_goal().execute(owner_id, command)
            return GoalResultType(goal=_to_goal_graphql(goal), errors=[])
        except (ValueError, TypeError) as error:
            return GoalResultType(
                goal=None,
                errors=[DomainError(code="INVALID_GOAL", message=str(error))],
            )

    @strawberry.mutation
    def propose_routine(self, info: Info[Any, None]) -> RoutineResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return RoutineResultType(
                routine=None,
                errors=[
                    DomainError(
                        code="AUTHENTICATION_REQUIRED",
                        message="Sign in before proposing a routine",
                    )
                ],
            )
        try:
            propose_routine().execute(owner_id)
            routine = get_current_routine().execute(owner_id)
            if routine is None:
                return RoutineResultType(
                    routine=None,
                    errors=[
                        DomainError(
                            code="ROUTINE_PROPOSAL_FAILED",
                            message="Failed to generate routine proposal",
                        )
                    ],
                )
            return RoutineResultType(routine=_to_routine_graphql(routine), errors=[])
        except UnsupportedLimitationError as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="UNSUPPORTED_LIMITATION", message=str(error))],
            )
        except NoEligibleRoutineTemplatesError as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="NO_ELIGIBLE_TEMPLATES", message=str(error))],
            )
        except (ValueError, TypeError) as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="INVALID_ROUTINE_REQUEST", message=str(error))],
            )

    @strawberry.mutation
    def edit_routine(
        self, info: Info[Any, None], input: EditRoutineInput
    ) -> RoutineResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return RoutineResultType(
                routine=None,
                errors=[
                    DomainError(
                        code="AUTHENTICATION_REQUIRED",
                        message="Sign in before editing a routine",
                    )
                ],
            )
        try:
            command = EditRoutineCommand(
                routine_id=UUID(str(input.routine_id)),
                title=input.title,
                base_version=input.base_version,
                items=tuple(
                    RoutineEditItem(
                        exercise_id=str(item.exercise_id),
                        order=item.order,
                        sets=item.sets,
                        repetitions=item.repetitions,
                        duration_seconds=item.duration_seconds,
                    )
                    for item in input.items
                ),
            )
            routine = edit_routine().execute(owner_id, command)
            return RoutineResultType(routine=_to_routine_graphql(routine), errors=[])
        except RoutineNotFoundError as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="ROUTINE_NOT_FOUND", message=str(error))],
            )
        except UnsupportedLimitationError as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="UNSUPPORTED_LIMITATION", message=str(error))],
            )
        except InvalidRoutineEditError as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="INVALID_ROUTINE_EDIT", message=str(error))],
            )
        except (ValueError, TypeError) as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="INVALID_INPUT", message=str(error))],
            )

    @strawberry.mutation
    def accept_routine(
        self, info: Info[Any, None], routine_id: strawberry.ID, version: int
    ) -> RoutineResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return RoutineResultType(
                routine=None,
                errors=[
                    DomainError(
                        code="AUTHENTICATION_REQUIRED",
                        message="Sign in before accepting a routine",
                    )
                ],
            )
        try:
            routine = accept_routine().execute(owner_id, UUID(str(routine_id)), version)
            return RoutineResultType(routine=_to_routine_graphql(routine), errors=[])
        except RoutineNotFoundError as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="ROUTINE_NOT_FOUND", message=str(error))],
            )
        except (ValueError, TypeError) as error:
            return RoutineResultType(
                routine=None,
                errors=[DomainError(code="INVALID_INPUT", message=str(error))],
            )

    @strawberry.mutation
    def prepare_session(
        self, info: Info[Any, None], input: PrepareSessionInput
    ) -> SessionResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return _failure("AUTHENTICATION_REQUIRED", "Sign in before preparing a session")

        try:
            command = _to_command(input)
            session = prepare_workout_session().execute(owner_id=owner_id, command=command)
            record = WorkoutSessionRecord.objects.select_related("routine").get(pk=session.id)
            return SessionResultType(session=_to_graphql(record), errors=[])
        except RoutineUnavailable as error:
            return _failure("ROUTINE_UNAVAILABLE", str(error), "routineId")
        except IdempotencyConflict as error:
            return _failure("IDEMPOTENCY_CONFLICT", str(error), "idempotencyKey")
        except (ValueError, TypeError) as error:
            return _failure("INVALID_SESSION_CONFIGURATION", str(error))

    @strawberry.mutation
    def start_session(
        self, info: Info[Any, None], command: SessionCommandInput
    ) -> SessionResultType:
        return _handle_session_lifecycle(
            info,
            command,
            lambda owner_id, cmd: start_workout_session().execute(owner_id=owner_id, command=cmd),
        )

    @strawberry.mutation
    def pause_session(
        self, info: Info[Any, None], command: SessionCommandInput
    ) -> SessionResultType:
        return _handle_session_lifecycle(
            info,
            command,
            lambda owner_id, cmd: pause_workout_session().execute(owner_id=owner_id, command=cmd),
        )

    @strawberry.mutation
    def resume_session(
        self, info: Info[Any, None], command: SessionCommandInput
    ) -> SessionResultType:
        return _handle_session_lifecycle(
            info,
            command,
            lambda owner_id, cmd: resume_workout_session().execute(owner_id=owner_id, command=cmd),
        )

    @strawberry.mutation
    def disable_dynamic_mode(
        self, info: Info[Any, None], command: SessionCommandInput
    ) -> SessionResultType:
        return _handle_session_lifecycle(
            info,
            command,
            lambda owner_id, cmd: disable_dynamic_mode().execute(owner_id=owner_id, command=cmd),
        )

    @strawberry.mutation
    def finish_session(
        self,
        info: Info[Any, None],
        command: SessionCommandInput,
        performed_sets: list[PerformedSetInput] | None = None,
        observation_coverage: ObservationCoverageInput | None = None,
        feedback: SessionFeedbackInput | None = None,
    ) -> SessionResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return _failure("AUTHENTICATION_REQUIRED", "Sign in before modifying a session")

        try:
            session_uuid = UUID(str(command.session_id))
        except (ValueError, TypeError) as error:
            return _failure("INVALID_INPUT", f"Invalid session ID: {error}", "sessionId")

        try:
            domain_sets: tuple[PerformedSet, ...] = ()
            if performed_sets is not None:
                domain_sets = tuple(
                    PerformedSet(
                        exercise_id=str(s.exercise_id),
                        set_order=s.set_order,
                        repetitions=s.repetitions,
                        duration_seconds=s.duration_seconds,
                    )
                    for s in performed_sets
                )

            domain_coverage: ObservationCoverage | None = None
            if observation_coverage is not None:
                domain_coverage = ObservationCoverage(
                    coverage_ratio=observation_coverage.coverage_ratio,
                    tracked_seconds=observation_coverage.tracked_seconds,
                    total_seconds=observation_coverage.total_seconds,
                    fully_visible_ratio=observation_coverage.fully_visible_ratio,
                    untracked_reasons=tuple(observation_coverage.untracked_reasons),
                )

            domain_feedback: SessionFeedback | None = None
            if feedback is not None:
                domain_feedback = SessionFeedback(
                    perceived_effort=feedback.perceived_effort,
                    comments=feedback.comments,
                )

            finish_cmd = FinishSessionCommand(
                session_id=session_uuid,
                expected_revision=command.expected_revision,
                idempotency_key=command.idempotency_key,
                performed_sets=domain_sets,
                observation_coverage=domain_coverage,
                feedback=domain_feedback,
            )
            session = finish_workout_session().execute(owner_id=owner_id, command=finish_cmd)
            record = (
                WorkoutSessionRecord.objects.select_related(
                    "routine", "observation_coverage", "feedback"
                )
                .prefetch_related("performed_sets")
                .get(pk=session.id)
            )
            return SessionResultType(session=_to_graphql(record), errors=[])
        except SessionNotFound as error:
            return _failure("SESSION_NOT_FOUND", str(error), "sessionId")
        except RevisionConflict as error:
            return _failure("REVISION_CONFLICT", str(error), "expectedRevision")
        except IdempotencyConflict as error:
            return _failure("IDEMPOTENCY_CONFLICT", str(error), "idempotencyKey")
        except InvalidSessionStateTransition as error:
            return _failure("INVALID_SESSION_STATE", str(error))
        except DuplicatePerformedSetError as error:
            return _failure("DUPLICATE_PERFORMED_SET", str(error), "performedSets")
        except UnknownRoutineExerciseError as error:
            return _failure("UNKNOWN_ROUTINE_EXERCISE", str(error), "performedSets")
        except InconsistentPerformedSetMeasurementError as error:
            return _failure("INCONSISTENT_PERFORMED_SET_MEASUREMENT", str(error), "performedSets")
        except (ValueError, TypeError) as error:
            return _failure("INVALID_INPUT", str(error))

    @strawberry.mutation
    def record_session_feedback(
        self,
        info: Info[Any, None],
        command: SessionCommandInput,
        feedback: SessionFeedbackInput,
    ) -> SessionResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return _failure("AUTHENTICATION_REQUIRED", "Sign in before modifying a session")

        try:
            session_uuid = UUID(str(command.session_id))
        except (ValueError, TypeError) as error:
            return _failure("INVALID_INPUT", f"Invalid session ID: {error}", "sessionId")

        try:
            domain_feedback = SessionFeedback(
                perceived_effort=feedback.perceived_effort,
                comments=feedback.comments,
            )
            cmd = RecordSessionFeedbackCommand(
                session_id=session_uuid,
                expected_revision=command.expected_revision,
                idempotency_key=command.idempotency_key,
                feedback=domain_feedback,
            )
            session = record_session_feedback().execute(owner_id=owner_id, command=cmd)
            record = (
                WorkoutSessionRecord.objects.select_related(
                    "routine", "observation_coverage", "feedback"
                )
                .prefetch_related("performed_sets")
                .get(pk=session.id)
            )
            return SessionResultType(session=_to_graphql(record), errors=[])
        except SessionNotFound as error:
            return _failure("SESSION_NOT_FOUND", str(error), "sessionId")
        except RevisionConflict as error:
            return _failure("REVISION_CONFLICT", str(error), "expectedRevision")
        except IdempotencyConflict as error:
            return _failure("IDEMPOTENCY_CONFLICT", str(error), "idempotencyKey")
        except InvalidSessionStateTransition as error:
            return _failure("INVALID_SESSION_STATE", str(error))
        except (ValueError, TypeError) as error:
            return _failure("INVALID_INPUT", str(error))

    @strawberry.mutation
    def abandon_session(
        self, info: Info[Any, None], command: SessionCommandInput
    ) -> SessionResultType:
        return _handle_session_lifecycle(
            info,
            command,
            lambda owner_id, cmd: abandon_workout_session().execute(owner_id=owner_id, command=cmd),
        )

    @strawberry.mutation
    def publish_transient_session_update(
        self, info: Info[Any, None], input: TransientSessionUpdateInput
    ) -> TransientSessionUpdateResultType:
        owner_id = _authenticated_owner_id(info)
        if owner_id is None:
            return TransientSessionUpdateResultType(
                success=False,
                errors=[
                    DomainError(
                        code="AUTHENTICATION_REQUIRED",
                        message="Sign in before publishing transient session updates",
                    )
                ],
            )
        try:
            session_uuid = UUID(str(input.session_id))
        except (ValueError, TypeError) as error:
            return TransientSessionUpdateResultType(
                success=False,
                errors=[
                    DomainError(
                        code="INVALID_INPUT",
                        message=f"Invalid session ID: {error}",
                        field="sessionId",
                    )
                ],
            )

        session = get_workout_session().execute(owner_id=owner_id, session_id=session_uuid)
        if session is None:
            return TransientSessionUpdateResultType(
                success=False,
                errors=[
                    DomainError(
                        code="SESSION_NOT_FOUND",
                        message=f"Workout session '{session_uuid}' not found",
                        field="sessionId",
                    )
                ],
            )

        update = TransientSessionUpdate(
            session_id=session_uuid,
            active_exercise_id=str(input.active_exercise_id) if input.active_exercise_id else None,
            current_repetitions=input.current_repetitions,
            current_duration_seconds=input.current_duration_seconds,
            pose_confidence=input.pose_confidence,
            visibility_status=input.visibility_status,
            timestamp=input.timestamp,
        )
        success = get_session_transient_store().publish_transient_update(update)
        return TransientSessionUpdateResultType(success=success, errors=[])



def _handle_session_lifecycle(
    info: Info[Any, None],
    command: SessionCommandInput,
    action: Callable[[UUID, SessionLifecycleCommand], Any],
) -> SessionResultType:
    owner_id = _authenticated_owner_id(info)
    if owner_id is None:
        return _failure("AUTHENTICATION_REQUIRED", "Sign in before modifying a session")

    try:
        session_uuid = UUID(str(command.session_id))
    except (ValueError, TypeError) as error:
        return _failure("INVALID_INPUT", f"Invalid session ID: {error}", "sessionId")

    try:
        cmd = SessionLifecycleCommand(
            session_id=session_uuid,
            expected_revision=command.expected_revision,
            idempotency_key=command.idempotency_key,
        )
        session = action(owner_id, cmd)
        record = (
            WorkoutSessionRecord.objects.select_related(
                "routine", "observation_coverage", "feedback"
            )
            .prefetch_related("performed_sets")
            .get(pk=session.id)
        )
        return SessionResultType(session=_to_graphql(record), errors=[])
    except SessionNotFound as error:
        return _failure("SESSION_NOT_FOUND", str(error), "sessionId")
    except RevisionConflict as error:
        return _failure("REVISION_CONFLICT", str(error), "expectedRevision")
    except IdempotencyConflict as error:
        return _failure("IDEMPOTENCY_CONFLICT", str(error), "idempotencyKey")
    except InvalidSessionStateTransition as error:
        return _failure("INVALID_SESSION_STATE", str(error))
    except (ValueError, TypeError) as error:
        return _failure("INVALID_INPUT", str(error))


def _authenticated_owner_id(info: Info[Any, None]) -> UUID | None:
    context = info.context
    request = getattr(context, "request", context)
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not isinstance(user.pk, UUID):
        return None
    return user.pk


def _to_exercise_graphql(exercise: Exercise) -> ExerciseType:
    return ExerciseType(
        id=strawberry.ID(exercise.code),
        version=exercise.version,
        name=exercise.name,
        vision_supported=exercise.vision_supported,
    )


def _to_profile_graphql(profile: UserProfile) -> ProfileType:
    return ProfileType(
        id=strawberry.ID(str(profile.owner_id)),
        display_name=profile.display_name,
        timezone=profile.timezone,
        experience_level=ExperienceLevelType(profile.experience_level.value),
        availability_days_per_week=profile.availability_days_per_week,
        target_session_minutes=profile.target_session_minutes,
        available_equipment=list(profile.available_equipment),
        workout_space=profile.workout_space,
        preferences=list(profile.preferences),
        exclusions=list(profile.exclusions),
        limitations=list(profile.limitations),
        coaching_tone=CoachingToneType(profile.coaching_tone.value),
        updated_at=profile.updated_at,
    )


def _to_goal_graphql(goal: GoalRevision) -> GoalType:
    return GoalType(
        id=strawberry.ID(str(goal.goal_id)),
        revision=goal.revision,
        description=goal.description,
        measure=goal.measure,
        baseline=goal.baseline,
        target=goal.target,
        unit=goal.unit,
        created_at=goal.created_at,
    )


def _to_command(value: PrepareSessionInput) -> PrepareSessionCommand:
    dynamic = value.dynamic
    return PrepareSessionCommand(
        routine_id=UUID(str(value.routine_id)),
        routine_version=value.routine_version,
        mode=SessionMode(value.mode.value),
        intensity=SessionIntensity(value.intensity.value),
        coaching_tone=CoachingTone(value.coaching_tone.value),
        capture_device_id=str(value.capture_device_id),
        display_device_id=str(value.display_device_id) if value.display_device_id else None,
        prompt_for_progress_photo=value.prompt_for_progress_photo,
        idempotency_key=value.idempotency_key,
        dynamic_frequency=(
            DynamicChallengeFrequency(dynamic.frequency.value) if dynamic is not None else None
        ),
        allowed_challenge_types=(
            tuple(DynamicChallengeType(item.value) for item in dynamic.allowed_challenge_types)
            if dynamic is not None
            else ()
        ),
        scoring_enabled=dynamic.scoring_enabled if dynamic is not None else True,
        narration_enabled=dynamic.narration_enabled if dynamic is not None else True,
    )


def _to_routine_graphql(routine: Routine | RoutineRecord) -> RoutineType:
    prescription = routine.prescription
    raw_items = prescription.get("items") if isinstance(prescription, dict) else None
    items_list: list[dict[str, Any]] = raw_items if isinstance(raw_items, list) else []
    items = [
        RoutineItemType(
            exercise=ExerciseType(
                id=strawberry.ID(str(item["exerciseId"])),
                version=item.get("exerciseVersion", 1),
                name=item["name"],
                vision_supported=item.get("visionSupported", False),
            ),
            order=item["order"],
            sets=item.get("sets", 1),
            repetitions=item.get("repetitions"),
            duration_seconds=item.get("durationSeconds"),
        )
        for item in items_list
    ]
    return RoutineType(
        id=strawberry.ID(str(routine.routine_id)),
        version=routine.version,
        title=routine.title,
        rationale=routine.rationale,
        items=items,
        accepted=routine.accepted,
    )


def _to_workout_session_graphql(
    session: WorkoutSession, routine: Routine
) -> WorkoutSessionType:
    """Build the GraphQL projection purely from the domain WorkoutSession and
    Routine returned by application use cases, with no direct ORM access."""
    config = session.configuration
    dynamic = None
    if config.dynamic is not None:
        dynamic = DynamicSessionConfigurationType(
            frequency=DynamicChallengeFrequencyType(config.dynamic.frequency.value),
            allowed_challenge_types=[
                DynamicChallengeTypeType(t.value) for t in config.dynamic.allowed_challenge_types
            ],
            scoring_enabled=config.dynamic.scoring_enabled,
            narration_enabled=config.dynamic.narration_enabled,
        )

    performed_sets = [
        PerformedSetType(
            exercise_id=strawberry.ID(s.exercise_id),
            set_order=s.set_order,
            repetitions=s.repetitions,
            duration_seconds=s.duration_seconds,
        )
        for s in session.performed_sets
    ]

    coverage = None
    if session.observation_coverage is not None:
        cov = session.observation_coverage
        coverage = ObservationCoverageType(
            coverage_ratio=cov.coverage_ratio,
            tracked_seconds=cov.tracked_seconds,
            total_seconds=cov.total_seconds,
            fully_visible_ratio=cov.fully_visible_ratio,
            untracked_reasons=list(cov.untracked_reasons),
        )

    feedback = None
    if session.feedback is not None:
        feedback = SessionFeedbackType(
            perceived_effort=session.feedback.perceived_effort,
            comments=session.feedback.comments,
        )

    assert session.updated_at is not None, "A persisted session always has updated_at set"

    return WorkoutSessionType(
        id=strawberry.ID(str(session.id)),
        revision=session.revision,
        routine=_to_routine_graphql(routine),
        state=SessionStateType(session.state.value),
        configuration=SessionConfigurationType(
            requested_mode=SessionModeType(config.requested_mode.value),
            active_mode=SessionModeType(config.active_mode.value),
            intensity=SessionIntensityType(config.intensity.value),
            coaching_tone=CoachingToneType(config.coaching_tone.value),
            capture_device_id=strawberry.ID(config.capture_device_id),
            display_device_id=(
                strawberry.ID(config.display_device_id) if config.display_device_id else None
            ),
            prompt_for_progress_photo=config.prompt_for_progress_photo,
            dynamic=dynamic,
        ),
        pause_reason=(
            PauseReasonType(session.pause_reason.value) if session.pause_reason else None
        ),
        confirmed_repetitions=session.confirmed_repetitions,
        performed_sets=performed_sets,
        observation_coverage=coverage,
        feedback=feedback,
        updated_at=session.updated_at,
    )


def _to_graphql(record: WorkoutSessionRecord) -> WorkoutSessionType:
    data = record.configuration
    dynamic_data = data.get("dynamic")
    dynamic = None
    if dynamic_data is not None:
        dynamic = DynamicSessionConfigurationType(
            frequency=DynamicChallengeFrequencyType(dynamic_data["frequency"]),
            allowed_challenge_types=[
                DynamicChallengeTypeType(value) for value in dynamic_data["allowed_challenge_types"]
            ],
            scoring_enabled=dynamic_data["scoring_enabled"],
            narration_enabled=dynamic_data["narration_enabled"],
        )
    performed_sets = [
        PerformedSetType(
            exercise_id=strawberry.ID(s.exercise_id),
            set_order=s.set_order,
            repetitions=s.repetitions,
            duration_seconds=s.duration_seconds,
        )
        for s in record.performed_sets.all()
    ]
    # `getattr(record, name, None)` is sufficient: Django's reverse OneToOne
    # descriptor raises `RelatedObjectDoesNotExist`, which also subclasses
    # `AttributeError` for exactly this purpose. A broad `except Exception`
    # here would silently turn a real DB failure or corrupted data into an
    # empty/None field instead of propagating it.
    coverage = None
    cov = getattr(record, "observation_coverage", None)
    if cov is not None:
        coverage = ObservationCoverageType(
            coverage_ratio=cov.coverage_ratio,
            tracked_seconds=cov.tracked_seconds,
            total_seconds=cov.total_seconds,
            fully_visible_ratio=cov.fully_visible_ratio,
            untracked_reasons=list(cov.untracked_reasons or []),
        )

    feedback = None
    fb = getattr(record, "feedback", None)
    if fb is not None:
        feedback = SessionFeedbackType(
            perceived_effort=fb.perceived_effort,
            comments=fb.comments,
        )

    return WorkoutSessionType(
        id=strawberry.ID(str(record.id)),
        revision=record.revision,
        routine=_to_routine_graphql(record.routine),
        state=SessionStateType(record.state),
        configuration=SessionConfigurationType(
            requested_mode=SessionModeType(data["requested_mode"]),
            active_mode=SessionModeType(data["active_mode"]),
            intensity=SessionIntensityType(data["intensity"]),
            coaching_tone=CoachingToneType(data["coaching_tone"]),
            capture_device_id=strawberry.ID(data["capture_device_id"]),
            display_device_id=(
                strawberry.ID(data["display_device_id"]) if data["display_device_id"] else None
            ),
            prompt_for_progress_photo=data["prompt_for_progress_photo"],
            dynamic=dynamic,
        ),
        pause_reason=(
            PauseReasonType(record.pause_reason) if record.pause_reason else None
        ),
        confirmed_repetitions=record.confirmed_repetitions,
        performed_sets=performed_sets,
        observation_coverage=coverage,
        feedback=feedback,
        updated_at=record.updated_at,
    )


def _failure(code: str, message: str, field: str | None = None) -> SessionResultType:
    return SessionResultType(
        session=None, errors=[DomainError(code=code, message=message, field=field)]
    )


schema = strawberry.Schema(query=Query, mutation=Mutation)
