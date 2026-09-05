from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

import strawberry
from strawberry.types import Info

from kinetiq.bootstrap.container import prepare_workout_session
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application import (
    IdempotencyConflict,
    PrepareSessionCommand,
    RoutineUnavailable,
)
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DynamicChallengeFrequency,
    DynamicChallengeType,
    SessionIntensity,
    SessionMode,
)
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord


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


@strawberry.type(name="WorkoutSession")
class WorkoutSessionType:
    id: strawberry.ID
    revision: int
    routine: RoutineType
    state: SessionStateType
    configuration: SessionConfigurationType
    pause_reason: PauseReasonType | None
    confirmed_repetitions: int
    updated_at: datetime


@strawberry.type
class DomainError:
    code: str
    message: str
    field: str | None = None


@strawberry.type(name="SessionResult")
class SessionResultType:
    session: WorkoutSessionType | None
    errors: list[DomainError]


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


@strawberry.type
class Query:
    @strawberry.field
    def service_status(self) -> ServiceStatus:
        return ServiceStatus(name="kinetiq-backend", version="0.1.0", ready=True)


@strawberry.type
class Mutation:
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


def _authenticated_owner_id(info: Info[Any, None]) -> UUID | None:
    context = info.context
    request = getattr(context, "request", context)
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or not isinstance(user.pk, UUID):
        return None
    return user.pk


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
    routine: RoutineRecord = record.routine
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
        for item in routine.prescription.get("items", [])
    ]
    return WorkoutSessionType(
        id=strawberry.ID(str(record.id)),
        revision=record.revision,
        routine=RoutineType(
            id=strawberry.ID(str(routine.routine_id)),
            version=routine.version,
            title=routine.title,
            rationale=routine.rationale,
            items=items,
            accepted=routine.accepted,
        ),
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
        pause_reason=None,
        confirmed_repetitions=record.confirmed_repetitions,
        updated_at=record.updated_at,
    )


def _failure(code: str, message: str, field: str | None = None) -> SessionResultType:
    return SessionResultType(
        session=None, errors=[DomainError(code=code, message=message, field=field)]
    )


schema = strawberry.Schema(query=Query, mutation=Mutation)
