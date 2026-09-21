from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from kinetiq.modules.profiles.infrastructure.models import UserProfileRecord
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application.ports import (
    AcceptedRoutine,
    AcceptedRoutineItem,
    TransitionPrecondition,
)
from kinetiq.modules.workouts.application.prepare_session import IdempotencyConflict
from kinetiq.modules.workouts.application.session_lifecycle import RevisionConflict, SessionNotFound
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    DynamicChallengeFrequency,
    DynamicChallengeType,
    DynamicSessionConfiguration,
    ObservationCoverage,
    PauseReason,
    PerformedSet,
    SessionConfiguration,
    SessionFeedback,
    SessionIntensity,
    SessionMode,
    SessionState,
    WorkoutSession,
)
from kinetiq.modules.workouts.infrastructure.models import (
    IdempotencyReceipt,
    ObservationCoverageRecord,
    PerformedSetRecord,
    SessionFeedbackRecord,
    WorkoutSessionRecord,
)

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
                    configuration=_serialize_configuration(
                        session.configuration,
                        target_person_id=session.target_person_id,
                        vision_analysis_id=session.vision_analysis_id,
                        vision_epoch=session.vision_epoch,
                        vision_observation_cursor=session.vision_observation_cursor,
                        skipped_challenge_ids=session.skipped_challenge_ids,
                    ),
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
            IdempotencyReceipt.objects.select_related(
                "session", "session__routine", "session__observation_coverage", "session__feedback"
            )
            .prefetch_related("session__performed_sets")
            .filter(owner_id=owner_id, operation=PREPARE_OPERATION, key=key)
            .first()
        )

    @staticmethod
    def _resolve_receipt(receipt: IdempotencyReceipt, request_fingerprint: str) -> WorkoutSession:
        if receipt.request_fingerprint != request_fingerprint:
            raise IdempotencyConflict("The idempotency key was already used for another command")
        return _to_domain(receipt.session)


class DjangoRoutineItemLookup:
    """Read-only adapter over the routines module's persisted prescription,
    scoped to exactly the fields session-finish validation needs."""

    def get_accepted_routine_items(
        self, *, owner_id: UUID, routine_id: UUID, version: int
    ) -> tuple[AcceptedRoutineItem, ...] | None:
        record = (
            RoutineRecord.objects.filter(
                owner_id=owner_id,
                routine_id=routine_id,
                version=version,
                accepted=True,
            )
            .only("prescription")
            .first()
        )
        if record is None:
            return None

        prescription = record.prescription
        items: list[dict[str, Any]] = (
            prescription.get("items", []) if isinstance(prescription, dict) else []
        )
        return tuple(
            AcceptedRoutineItem(
                exercise_id=str(item["exerciseId"]),
                repetitions=item.get("repetitions"),
                duration_seconds=item.get("durationSeconds"),
            )
            for item in items
        )


class DjangoUserProfileLookup:
    """Read-only adapter retrieving user exclusions from UserProfileRecord."""

    def get_user_exclusions(self, *, owner_id: UUID) -> tuple[str, ...]:
        record = UserProfileRecord.objects.filter(owner_id=owner_id).only("exclusions").first()
        if record is None or not isinstance(record.exclusions, list):
            return ()
        return tuple(str(item) for item in record.exclusions if isinstance(item, str))


class DjangoSessionLifecycleRepository:
    def get_session(self, *, owner_id: UUID, session_id: UUID) -> WorkoutSession | None:
        record = (
            WorkoutSessionRecord.objects.select_related(
                "routine", "observation_coverage", "feedback"
            )
            .prefetch_related("performed_sets")
            .filter(id=session_id, owner_id=owner_id)
            .first()
        )
        if record is None:
            return None
        return _to_domain(record)

    def check_transition_precondition(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_revision: int,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> TransitionPrecondition:
        """Validates the revision and idempotency command against the
        persisted session WITHOUT applying any transition or external side
        effect -- used to check whether it is safe to proceed to call
        Vision before actually calling it. Takes the same row lock
        `apply_transition` does (for a consistent read), but releases it
        immediately afterward since nothing is written; it does not hold
        the lock across the caller's subsequent Vision call. See
        `TransitionPrecondition` for what this does and does not guarantee.
        """
        existing = self._find_receipt(owner_id, operation, idempotency_key)
        if existing is not None:
            return TransitionPrecondition(
                already_applied=True,
                session=self._resolve_receipt(existing, request_fingerprint),
            )

        with transaction.atomic():
            record = (
                WorkoutSessionRecord.objects.select_for_update(of=("self",))
                .select_related("routine", "observation_coverage", "feedback")
                .prefetch_related("performed_sets")
                .filter(id=session_id, owner_id=owner_id)
                .first()
            )
            if record is None:
                raise SessionNotFound(f"Workout session {session_id} not found")

            existing = self._find_receipt(owner_id, operation, idempotency_key)
            if existing is not None:
                return TransitionPrecondition(
                    already_applied=True,
                    session=self._resolve_receipt(existing, request_fingerprint),
                )

            if record.revision != expected_revision:
                raise RevisionConflict(
                    f"Session revision conflict: expected {expected_revision}, "
                    f"current is {record.revision}"
                )

            return TransitionPrecondition(already_applied=False, session=_to_domain(record))

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
                # `of=("self",)` restricts FOR UPDATE to this table alone.
                # observation_coverage/feedback are nullable reverse OneToOne
                # relations (LEFT OUTER JOIN via select_related); PostgreSQL
                # rejects FOR UPDATE against the nullable side of an outer
                # join, so locking must not extend to those joined tables.
                record = (
                    WorkoutSessionRecord.objects.select_for_update(of=("self",))
                    .select_related("routine", "observation_coverage", "feedback")
                    .prefetch_related("performed_sets")
                    .filter(id=session_id, owner_id=owner_id)
                    .first()
                )
                if record is None:
                    raise SessionNotFound(f"Workout session {session_id} not found")

                # Re-check idempotency now that the row lock is held: a concurrent
                # identical request may have committed while this request was
                # blocked waiting for select_for_update(), in which case the
                # session's revision has already moved past `expected_revision`
                # and must resolve to that receipt rather than raise a spurious
                # RevisionConflict.
                existing = self._find_receipt(owner_id, operation, idempotency_key)
                if existing is not None:
                    return self._resolve_receipt(existing, request_fingerprint)

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
                record.configuration = _serialize_configuration(
                    updated_session.configuration,
                    target_person_id=updated_session.target_person_id,
                    vision_analysis_id=updated_session.vision_analysis_id,
                    vision_epoch=updated_session.vision_epoch,
                    vision_observation_cursor=updated_session.vision_observation_cursor,
                    skipped_challenge_ids=updated_session.skipped_challenge_ids,
                )
                record.confirmed_repetitions = updated_session.confirmed_repetitions
                record.save(
                    update_fields=[
                        "state",
                        "revision",
                        "pause_reason",
                        "configuration",
                        "confirmed_repetitions",
                        "updated_at",
                    ]
                )

                if updated_session.performed_sets:
                    for set_data in updated_session.performed_sets:
                        PerformedSetRecord.objects.get_or_create(
                            session=record,
                            exercise_id=set_data.exercise_id,
                            set_order=set_data.set_order,
                            defaults={
                                "repetitions": set_data.repetitions,
                                "duration_seconds": set_data.duration_seconds,
                            },
                        )

                if updated_session.observation_coverage is not None:
                    cov = updated_session.observation_coverage
                    ObservationCoverageRecord.objects.update_or_create(
                        session=record,
                        defaults={
                            "coverage_ratio": cov.coverage_ratio,
                            "tracked_seconds": cov.tracked_seconds,
                            "total_seconds": cov.total_seconds,
                            "fully_visible_ratio": cov.fully_visible_ratio,
                            "untracked_reasons": list(cov.untracked_reasons),
                        },
                    )

                if updated_session.feedback is not None:
                    fb = updated_session.feedback
                    SessionFeedbackRecord.objects.update_or_create(
                        session=record,
                        defaults={
                            "perceived_effort": fb.perceived_effort,
                            "comments": fb.comments,
                        },
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
            IdempotencyReceipt.objects.select_related(
                "session", "session__routine", "session__observation_coverage", "session__feedback"
            )
            .prefetch_related("session__performed_sets")
            .filter(owner_id=owner_id, operation=operation, key=key)
            .first()
        )

    @staticmethod
    def _resolve_receipt(receipt: IdempotencyReceipt, request_fingerprint: str) -> WorkoutSession:
        if receipt.request_fingerprint != request_fingerprint:
            raise IdempotencyConflict("The idempotency key was already used for another command")
        return _to_domain(receipt.session)

    def acquire_vision_lease(
        self, *, owner_id: UUID, session_id: UUID, ttl_seconds: int
    ) -> str | None:
        return self._acquire_lease(
            owner_id=owner_id,
            session_id=session_id,
            ttl_seconds=ttl_seconds,
            token_field="vision_lease_token",
            expires_field="vision_lease_expires_at",
        )

    def release_vision_lease(self, *, owner_id: UUID, session_id: UUID, lease_token: str) -> None:
        self._release_lease(
            owner_id=owner_id,
            session_id=session_id,
            lease_token=lease_token,
            token_field="vision_lease_token",
            expires_field="vision_lease_expires_at",
        )

    def acquire_vision_poll_lease(
        self, *, owner_id: UUID, session_id: UUID, ttl_seconds: int
    ) -> str | None:
        return self._acquire_lease(
            owner_id=owner_id,
            session_id=session_id,
            ttl_seconds=ttl_seconds,
            token_field="vision_poll_lease_token",
            expires_field="vision_poll_lease_expires_at",
        )

    def release_vision_poll_lease(
        self, *, owner_id: UUID, session_id: UUID, lease_token: str
    ) -> None:
        self._release_lease(
            owner_id=owner_id,
            session_id=session_id,
            lease_token=lease_token,
            token_field="vision_poll_lease_token",
            expires_field="vision_poll_lease_expires_at",
        )

    @staticmethod
    def _acquire_lease(
        *, owner_id: UUID, session_id: UUID, ttl_seconds: int, token_field: str, expires_field: str
    ) -> str | None:
        """Atomically claims a per-session lease with a single UPDATE,
        without holding any transaction open across whatever the caller
        does while holding it (a Vision HTTP call, an observation poll).
        PostgreSQL executes one UPDATE as a single atomic statement: either
        exactly one caller's UPDATE matches the WHERE clause and wins the
        lease, or it matches zero rows and the caller must not proceed.
        Returns the new lease token on success, None if another live
        lease is already held (the caller must fail fast, not retry
        indefinitely while holding anything open)."""
        token = str(uuid4())
        now = timezone.now()
        updated = (
            WorkoutSessionRecord.objects.filter(id=session_id, owner_id=owner_id)
            .filter(Q(**{f"{token_field}__isnull": True}) | Q(**{f"{expires_field}__lt": now}))
            .update(**{token_field: token, expires_field: now + timedelta(seconds=ttl_seconds)})
        )
        return token if updated == 1 else None

    @staticmethod
    def _release_lease(
        *, owner_id: UUID, session_id: UUID, lease_token: str, token_field: str, expires_field: str
    ) -> None:
        """Clears a held lease so a retry does not have to wait for TTL
        expiry. Only clears it if the token still matches -- if it
        doesn't (this lease already expired and was claimed by someone
        else), clearing it would incorrectly release a lease we no longer
        own."""
        WorkoutSessionRecord.objects.filter(
            id=session_id, owner_id=owner_id, **{token_field: lease_token}
        ).update(**{token_field: None, expires_field: None})

    def list_sessions_polling_vision(self) -> tuple[WorkoutSession, ...]:
        """Sessions eligible for Vision observation polling: still
        active/paused, with a Vision analysis started and a target
        confirmed. target_person_id/vision_analysis_id live inside the
        configuration JSON rather than indexed columns, so this filters by
        state at the SQL level and finishes the eligibility check in
        Python -- a disclosed simplification, fine at current session
        volumes but not a query that scales to a large fleet of concurrent
        sessions without an index on those JSON keys."""
        records = (
            WorkoutSessionRecord.objects.select_related(
                "routine", "observation_coverage", "feedback"
            )
            .prefetch_related("performed_sets")
            .filter(state__in=[SessionState.ACTIVE.value, SessionState.PAUSED.value])
        )
        return tuple(
            session
            for session in (_to_domain(record) for record in records)
            if session.vision_analysis_id is not None and session.target_person_id is not None
        )

    def advance_vision_observation_cursor(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_previous_cursor: str | None,
        new_cursor: str,
    ) -> bool:
        """Persists how far Vision observation polling has progressed for
        a session, without bumping its revision or requiring an
        idempotency key -- this is system-internal bookkeeping for a
        background worker, not a user-facing command subject to the
        optimistic-concurrency contract apply_transition enforces.

        Compare-and-swap: only writes if the currently persisted cursor
        still equals `expected_previous_cursor` (the value the caller read
        before polling Vision). The per-session poll lease
        (`acquire_vision_poll_lease`) already prevents two workers from
        polling the same session concurrently, but this CAS is the
        defense-in-depth backstop for the case a lease expired mid-poll
        (e.g. a slow Vision response past the TTL) and was claimed by a
        second worker: whichever worker's write loses the race to observe
        a stale `expected_previous_cursor` fails the swap and must not
        overwrite what the other worker already advanced to -- an older,
        lagging worker can never regress the cursor backward. Returns
        whether the swap succeeded.
        """
        with transaction.atomic():
            record = (
                WorkoutSessionRecord.objects.select_for_update(of=("self",))
                .filter(id=session_id, owner_id=owner_id)
                .first()
            )
            if record is None:
                return False
            current_cursor = record.configuration.get("vision_observation_cursor")
            if current_cursor != expected_previous_cursor:
                return False
            record.configuration = {
                **record.configuration,
                "vision_observation_cursor": new_cursor,
            }
            record.save(update_fields=["configuration", "updated_at"])
            return True


def _serialize_configuration(
    configuration: SessionConfiguration,
    target_person_id: str | None = None,
    vision_analysis_id: str | None = None,
    vision_epoch: int | None = None,
    vision_observation_cursor: str | None = None,
    skipped_challenge_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    dynamic = None
    if configuration.dynamic is not None:
        dynamic = {
            "frequency": (
                configuration.dynamic.frequency.value
                if hasattr(configuration.dynamic.frequency, "value")
                else str(configuration.dynamic.frequency)
            ),
            "allowed_challenge_types": [
                t.value if hasattr(t, "value") else str(t)
                for t in configuration.dynamic.allowed_challenge_types
            ],
            "scoring_enabled": configuration.dynamic.scoring_enabled,
            "narration_enabled": configuration.dynamic.narration_enabled,
            "policy_version": configuration.dynamic.policy_version,
            "random_seed": str(configuration.dynamic.random_seed),
        }
    payload: dict[str, Any] = {
        "requested_mode": configuration.requested_mode,
        "active_mode": configuration.active_mode,
        "intensity": configuration.intensity,
        "coaching_tone": configuration.coaching_tone,
        "capture_device_id": configuration.capture_device_id,
        "display_device_id": configuration.display_device_id,
        "prompt_for_progress_photo": configuration.prompt_for_progress_photo,
        "dynamic": dynamic,
    }
    if target_person_id is not None:
        payload["target_person_id"] = target_person_id
    if vision_analysis_id is not None:
        payload["vision_analysis_id"] = vision_analysis_id
    if vision_epoch is not None:
        payload["vision_epoch"] = vision_epoch
    if vision_observation_cursor is not None:
        payload["vision_observation_cursor"] = vision_observation_cursor
    if skipped_challenge_ids:
        payload["skipped_challenge_ids"] = list(skipped_challenge_ids)
    return payload


def _to_domain(record: WorkoutSessionRecord) -> WorkoutSession:
    data = record.configuration
    dynamic_data = data.get("dynamic")
    dynamic = None
    if dynamic_data is not None:
        dynamic = DynamicSessionConfiguration(
            frequency=DynamicChallengeFrequency(dynamic_data["frequency"]),
            allowed_challenge_types=tuple(
                value if isinstance(value, DynamicChallengeType) else DynamicChallengeType(value)
                for value in dynamic_data["allowed_challenge_types"]
            ),
            scoring_enabled=dynamic_data["scoring_enabled"],
            narration_enabled=dynamic_data["narration_enabled"],
            policy_version=dynamic_data["policy_version"],
            random_seed=UUID(str(dynamic_data["random_seed"])),
        )

    # Note: `getattr(record, name, None)` is sufficient here without a
    # try/except. Django's reverse OneToOne descriptor raises a
    # `RelatedObjectDoesNotExist` that also subclasses `AttributeError`
    # specifically so `getattr(..., default)` treats "no related row" as the
    # default rather than an error. A bare `except Exception` around this
    # previously also swallowed genuine DB failures or corrupted data as
    # empty/None instead of letting them propagate.
    performed_sets = tuple(
        PerformedSet(
            exercise_id=s.exercise_id,
            set_order=s.set_order,
            repetitions=s.repetitions,
            duration_seconds=s.duration_seconds,
        )
        for s in record.performed_sets.all()
    )

    observation_coverage: ObservationCoverage | None = None
    cov = getattr(record, "observation_coverage", None)
    if cov is not None:
        observation_coverage = ObservationCoverage(
            coverage_ratio=cov.coverage_ratio,
            tracked_seconds=cov.tracked_seconds,
            total_seconds=cov.total_seconds,
            fully_visible_ratio=cov.fully_visible_ratio,
            untracked_reasons=tuple(cov.untracked_reasons or []),
        )

    feedback: SessionFeedback | None = None
    fb = getattr(record, "feedback", None)
    if fb is not None:
        feedback = SessionFeedback(
            perceived_effort=fb.perceived_effort,
            comments=fb.comments,
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
        confirmed_repetitions=record.confirmed_repetitions,
        performed_sets=performed_sets,
        observation_coverage=observation_coverage,
        feedback=feedback,
        target_person_id=data.get("target_person_id"),
        vision_analysis_id=data.get("vision_analysis_id"),
        vision_epoch=data.get("vision_epoch"),
        vision_observation_cursor=data.get("vision_observation_cursor"),
        skipped_challenge_ids=tuple(data.get("skipped_challenge_ids") or []),
        updated_at=record.updated_at,
    )
