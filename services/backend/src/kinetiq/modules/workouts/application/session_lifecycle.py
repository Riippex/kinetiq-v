import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from kinetiq.modules.workouts.application.ports import SessionLifecycleRepository
from kinetiq.modules.workouts.domain import (
    PauseReason,
    WorkoutSession,
)


class SessionNotFound(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionLifecycleCommand:
    session_id: UUID
    expected_revision: int
    idempotency_key: str

    def fingerprint(self) -> str:
        payload = {
            "session_id": str(self.session_id),
            "expected_revision": self.expected_revision,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


class BaseSessionLifecycleUseCase:
    def __init__(self, repository: SessionLifecycleRepository) -> None:
        self._repository = repository

    def _execute_transition(
        self,
        *,
        owner_id: UUID,
        command: SessionLifecycleCommand,
        operation: str,
        transition: Callable[[WorkoutSession], WorkoutSession],
    ) -> WorkoutSession:
        if not command.idempotency_key.strip():
            raise ValueError("An idempotency key is required")
        if command.expected_revision < 1:
            raise ValueError("Expected revision must be positive")

        return self._repository.apply_transition(
            owner_id=owner_id,
            session_id=command.session_id,
            expected_revision=command.expected_revision,
            operation=operation,
            idempotency_key=command.idempotency_key,
            request_fingerprint=command.fingerprint(),
            transition=transition,
        )


class StartWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.start_session",
            transition=lambda session: session.start(),
        )


class PauseWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(
        self,
        *,
        owner_id: UUID,
        command: SessionLifecycleCommand,
        reason: PauseReason = PauseReason.USER_REQUEST,
    ) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.pause_session",
            transition=lambda session: session.pause(reason=reason),
        )


class ResumeWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.resume_session",
            transition=lambda session: session.resume(),
        )


class DisableDynamicModeUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.disable_dynamic_mode",
            transition=lambda session: session.disable_dynamic_mode(),
        )


class FinishWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.finish_session",
            transition=lambda session: session.finish(),
        )


class AbandonWorkoutSessionUseCase(BaseSessionLifecycleUseCase):
    def execute(self, *, owner_id: UUID, command: SessionLifecycleCommand) -> WorkoutSession:
        return self._execute_transition(
            owner_id=owner_id,
            command=command,
            operation="workouts.abandon_session",
            transition=lambda session: session.abandon(),
        )
