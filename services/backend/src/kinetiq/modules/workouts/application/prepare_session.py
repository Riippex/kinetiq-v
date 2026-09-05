import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from kinetiq.modules.workouts.application.ports import SessionPreparationRepository
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DynamicChallengeFrequency,
    DynamicChallengeType,
    DynamicSessionConfiguration,
    SessionConfiguration,
    SessionIntensity,
    SessionMode,
    WorkoutSession,
)


class RoutineUnavailable(ValueError):
    pass


class IdempotencyConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PrepareSessionCommand:
    routine_id: UUID
    routine_version: int
    mode: SessionMode
    intensity: SessionIntensity
    coaching_tone: CoachingTone
    capture_device_id: str
    display_device_id: str | None
    prompt_for_progress_photo: bool
    idempotency_key: str
    dynamic_frequency: DynamicChallengeFrequency | None = None
    allowed_challenge_types: tuple[DynamicChallengeType, ...] = ()
    scoring_enabled: bool = True
    narration_enabled: bool = True

    def fingerprint(self) -> str:
        payload = asdict(self)
        payload.pop("idempotency_key")
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


class PrepareWorkoutSession:
    def __init__(
        self,
        repository: SessionPreparationRepository,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self.id_factory = id_factory

    def execute(self, *, owner_id: UUID, command: PrepareSessionCommand) -> WorkoutSession:
        if not command.idempotency_key.strip():
            raise ValueError("An idempotency key is required")

        routine = self.repository.find_accepted_routine(
            owner_id=owner_id,
            routine_id=command.routine_id,
            version=command.routine_version,
        )
        if routine is None:
            raise RoutineUnavailable("The accepted routine version is unavailable")

        dynamic = None
        if command.mode is SessionMode.DYNAMIC:
            dynamic = DynamicSessionConfiguration(
                frequency=command.dynamic_frequency or DynamicChallengeFrequency.STANDARD,
                allowed_challenge_types=command.allowed_challenge_types,
                scoring_enabled=command.scoring_enabled,
                narration_enabled=command.narration_enabled,
                policy_version=1,
                random_seed=self.id_factory(),
            )

        configuration = SessionConfiguration(
            requested_mode=command.mode,
            active_mode=command.mode,
            intensity=command.intensity,
            coaching_tone=command.coaching_tone,
            capture_device_id=command.capture_device_id,
            display_device_id=command.display_device_id,
            prompt_for_progress_photo=command.prompt_for_progress_photo,
            dynamic=dynamic,
        )
        session = WorkoutSession.prepare(
            session_id=self.id_factory(),
            owner_id=owner_id,
            routine_id=routine.routine_id,
            routine_version=routine.version,
            configuration=configuration,
        )
        return self.repository.save_idempotently(
            session=session,
            routine=routine,
            idempotency_key=command.idempotency_key,
            request_fingerprint=command.fingerprint(),
        )
