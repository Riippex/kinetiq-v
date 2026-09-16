from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application.ports import AcceptedRoutine
from kinetiq.modules.workouts.application.prepare_session import IdempotencyConflict
from kinetiq.modules.workouts.application.session_lifecycle import RevisionConflict, SessionNotFound
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DynamicChallengeFrequency,
    DynamicChallengeType,
    DynamicSessionConfiguration,
    PauseReason,
    SessionConfiguration,
    SessionIntensity,
    SessionMode,
    SessionState,
    WorkoutSession,
)
from kinetiq.modules.workouts.infrastructure.models import IdempotencyReceipt, WorkoutSessionRecord

PREPARE_OPERATION = "workouts.prepare_session"


class DjangoSessionPreparationRepository:
    def find_accepted_routine(
        self, *, owner_id: UUID, routine_id: UUID, version: int
    ) -> AcceptedRoutine | None:
        record = (
            RoutineRecord.objects.filter(
                owner_id=owner_id,
                routine_id=routine_id,
                version=version,
                accepted=True,
            )
            .only("id", "routine_id", "version")
            .first()
        )
        if record is None:
            return None
        return AcceptedRoutine(
            record_id=record.id, routine_id=record.routine_id, version=record.version
        )

    def save_idempotently(
        self,
        *,
        session: WorkoutSession,
        routine: AcceptedRoutine,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> WorkoutSession:
        existing = self._find_receipt(session.owner_id, idempotency_key)
        if existing is not None:
            return self._resolve_receipt(existing, request_fingerprint)

        try:
            with transaction.atomic():
                record = WorkoutSessionRecord.objects.create(
                    id=session.id,
                    owner_id=session.owner_id,
                    routine_id=routine.record_id,
                    revision=session.revision,
                    state=session.state,
                    configuration=_serialize_configuration(session.configuration),
                )
                IdempotencyReceipt.objects.create(
                    owner_id=session.owner_id,
                    operation=PREPARE_OPERATION,
                    key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    session=record,
                )
        except IntegrityError:
            receipt = self._find_receipt(session.owner_id, idempotency_key)
            if receipt is None:
                raise
            return self._resolve_receipt(receipt, request_fingerprint)

        return session

    @staticmethod
    def _find_receipt(owner_id: UUID, key: str) -> IdempotencyReceipt | None:
        return (
            IdempotencyReceipt.objects.select_related("session", "session__routine")
            .filter(owner_id=owner_id, operation=PREPARE_OPERATION, key=key)
            .first()
        )

    @staticmethod
    def _resolve_receipt(receipt: IdempotencyReceipt, request_fingerprint: str) -> WorkoutSession:
        if receipt.request_fingerprint != request_fingerprint:
            raise IdempotencyConflict("The idempotency key was already used for another command")
        return _to_domain(receipt.session)


class DjangoSessionLifecycleRepository:
    def get_session(self, *, owner_id: UUID, session_id: UUID) -> WorkoutSession | None:
        record = (
            WorkoutSessionRecord.objects.select_related("routine")
            .filter(id=session_id, owner_id=owner_id)
            .first()
        )
        if record is None:
            return None
        return _to_domain(record)

    def apply_transition(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_revision: int,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        transition: Callable[[WorkoutSession], WorkoutSession],
    ) -> WorkoutSession:
        existing = self._find_receipt(owner_id, operation, idempotency_key)
        if existing is not None:
            return self._resolve_receipt(existing, request_fingerprint)

        try:
            with transaction.atomic():
                record = (
                    WorkoutSessionRecord.objects.select_for_update()
                    .select_related("routine")
                    .filter(id=session_id, owner_id=owner_id)
                    .first()
                )
                if record is None:
                    raise SessionNotFound(f"Workout session {session_id} not found")

                if record.revision != expected_revision:
                    raise RevisionConflict(
                        f"Session revision conflict: expected {expected_revision}, "
                        f"current is {record.revision}"
                    )

                current_session = _to_domain(record)
                updated_session = transition(current_session)

                record.state = updated_session.state.value
                record.revision = updated_session.revision
                record.pause_reason = (
                    updated_session.pause_reason.value if updated_session.pause_reason else None
                )
                record.configuration = _serialize_configuration(updated_session.configuration)
                record.save(
                    update_fields=[
                        "state",
                        "revision",
                        "pause_reason",
                        "configuration",
                        "updated_at",
                    ]
                )

                IdempotencyReceipt.objects.create(
                    owner_id=owner_id,
                    operation=operation,
                    key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    session=record,
                )

                return updated_session
        except IntegrityError:
            receipt = self._find_receipt(owner_id, operation, idempotency_key)
            if receipt is None:
                raise
            return self._resolve_receipt(receipt, request_fingerprint)

    @staticmethod
    def _find_receipt(owner_id: UUID, operation: str, key: str) -> IdempotencyReceipt | None:
        return (
            IdempotencyReceipt.objects.select_related("session", "session__routine")
            .filter(owner_id=owner_id, operation=operation, key=key)
            .first()
        )

    @staticmethod
    def _resolve_receipt(receipt: IdempotencyReceipt, request_fingerprint: str) -> WorkoutSession:
        if receipt.request_fingerprint != request_fingerprint:
            raise IdempotencyConflict("The idempotency key was already used for another command")
        return _to_domain(receipt.session)


def _serialize_configuration(configuration: SessionConfiguration) -> dict[str, Any]:
    dynamic = None
    if configuration.dynamic is not None:
        dynamic = {
            "frequency": configuration.dynamic.frequency,
            "allowed_challenge_types": list(configuration.dynamic.allowed_challenge_types),
            "scoring_enabled": configuration.dynamic.scoring_enabled,
            "narration_enabled": configuration.dynamic.narration_enabled,
            "policy_version": configuration.dynamic.policy_version,
            "random_seed": str(configuration.dynamic.random_seed),
        }
    return {
        "requested_mode": configuration.requested_mode,
        "active_mode": configuration.active_mode,
        "intensity": configuration.intensity,
        "coaching_tone": configuration.coaching_tone,
        "capture_device_id": configuration.capture_device_id,
        "display_device_id": configuration.display_device_id,
        "prompt_for_progress_photo": configuration.prompt_for_progress_photo,
        "dynamic": dynamic,
    }


def _to_domain(record: WorkoutSessionRecord) -> WorkoutSession:
    data = record.configuration
    dynamic_data = data.get("dynamic")
    dynamic = None
    if dynamic_data is not None:
        dynamic = DynamicSessionConfiguration(
            frequency=DynamicChallengeFrequency(dynamic_data["frequency"]),
            allowed_challenge_types=tuple(
                DynamicChallengeType(value) for value in dynamic_data["allowed_challenge_types"]
            ),
            scoring_enabled=dynamic_data["scoring_enabled"],
            narration_enabled=dynamic_data["narration_enabled"],
            policy_version=dynamic_data["policy_version"],
            random_seed=UUID(dynamic_data["random_seed"]),
        )
    return WorkoutSession(
        id=record.id,
        owner_id=record.owner_id,
        routine_id=record.routine.routine_id,
        routine_version=record.routine.version,
        revision=record.revision,
        state=SessionState(record.state),
        configuration=SessionConfiguration(
            requested_mode=SessionMode(data["requested_mode"]),
            active_mode=SessionMode(data["active_mode"]),
            intensity=SessionIntensity(data["intensity"]),
            coaching_tone=CoachingTone(data["coaching_tone"]),
            capture_device_id=data["capture_device_id"],
            display_device_id=data["display_device_id"],
            prompt_for_progress_photo=data["prompt_for_progress_photo"],
            dynamic=dynamic,
        ),
        pause_reason=PauseReason(record.pause_reason) if record.pause_reason else None,
    )

