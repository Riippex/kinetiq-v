import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from kinetiq.modules.workouts.application.ports import (
    SessionLifecycleRepository,
    SessionTransientStore,
)
from kinetiq.modules.workouts.application.session_lifecycle import SessionNotFound
from kinetiq.modules.workouts.domain.display_pairing import (
    DisplayDeviceType,
    DisplayPairingCode,
    DisplayPairingCodeExpired,
    DisplayPairingCodeNotFound,
    DisplayPairingCodePaired,
    DisplayPairingContention,
    DisplayPairingStatus,
    DisplayPairingStore,
)
from kinetiq.modules.workouts.domain.session import SessionIntensity, SessionMode

_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_LENGTH = 6
_MAX_GENERATION_ATTEMPTS = 10
_MAX_CLAIM_ATTEMPTS = 8


@dataclass(frozen=True)
class DisplaySessionState:
    session_id: str | None
    device_type: DisplayDeviceType
    status: DisplayPairingStatus
    mode: SessionMode | None = None
    intensity: SessionIntensity | None = None
    state: str | None = None
    active_exercise: str | None = None
    confirmed_reps: int = 0
    visibility_status: str | None = None
    pause_reason: str | None = None


class IssueDisplayPairingCodeUseCase:
    def __init__(self, pairing_store: DisplayPairingStore) -> None:
        self._pairing_store = pairing_store

    def execute(self, device_type: DisplayDeviceType) -> DisplayPairingCode:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=15)
        prefix = "FIRE" if device_type == DisplayDeviceType.FIRE_TV else "VEGA"

        # Always generate a real random code and never fall back to a
        # fixed, predictable default: a guessable pairing code would let
        # an unrelated party pair their own display to someone else's
        # session. Retries only guard against the astronomically rare
        # collision with another still-live code for the same prefix.
        # Each candidate is claimed atomically (`create_if_absent`), so two
        # concurrent requests can never be issued the same live code.
        for _ in range(_MAX_GENERATION_ATTEMPTS):
            suffix = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
            pairing = DisplayPairingCode(
                code=f"{prefix}-{suffix}",
                device_type=device_type,
                created_at=now,
                expires_at=expires_at,
                status=DisplayPairingStatus.UNPAIRED,
            )
            if self._pairing_store.create_if_absent(pairing):
                return pairing
        raise RuntimeError("Could not generate a unique display pairing code")


class PairDisplayDeviceUseCase:
    def __init__(
        self,
        pairing_store: DisplayPairingStore,
        lifecycle_repo: SessionLifecycleRepository,
    ) -> None:
        self._pairing_store = pairing_store
        self._lifecycle_repo = lifecycle_repo

    def execute(
        self, owner_id: str, code: str, session_id: str | None = None
    ) -> DisplayPairingCode:
        target_session_id = self._validated_session_id(owner_id, session_id)

        # Read -> decide -> compare-and-save. The guard is re-evaluated on
        # every attempt, so when two owners race for the same live code
        # exactly one commit wins and the loser, on re-reading, is rejected
        # as "already paired" instead of silently overwriting the winner.
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            pairing = self._pairing_store.get(code)
            if pairing is None:
                raise DisplayPairingCodeNotFound(code)

            if pairing.is_expired():
                raise DisplayPairingCodeExpired(code)

            # A code already paired to a different owner must never be
            # re-pairable by someone else: that would let a second athlete
            # who observed or guessed a live code redirect the display to
            # their own session, or read the original owner's live progress.
            # Pairing the same owner's code again (e.g. reconnecting) is fine.
            if (
                pairing.status == DisplayPairingStatus.PAIRED
                and pairing.owner_id is not None
                and pairing.owner_id != owner_id
            ):
                raise DisplayPairingCodePaired(code)

            updated = DisplayPairingCode(
                code=pairing.code,
                device_type=pairing.device_type,
                created_at=pairing.created_at,
                expires_at=pairing.expires_at,
                status=DisplayPairingStatus.PAIRED,
                paired_session_id=target_session_id,
                owner_id=owner_id,
                version=pairing.version + 1,
            )
            if self._pairing_store.compare_and_save(
                expected_version=pairing.version, pairing=updated
            ):
                return updated

        raise DisplayPairingContention(code)

    def _validated_session_id(self, owner_id: str, session_id: str | None) -> str | None:
        if not session_id:
            return None
        try:
            owner_uuid = UUID(owner_id)
            session_uuid = UUID(session_id)
        except (ValueError, TypeError) as exc:
            raise SessionNotFound(f"Session '{session_id}' not found") from exc

        session = self._lifecycle_repo.get_session(owner_id=owner_uuid, session_id=session_uuid)
        # A session_id that does not exist, or that belongs to a different
        # owner (get_session is owner-scoped and returns None for a foreign
        # session), must never be silently paired -- that would let a display
        # show another athlete's session, or a nonexistent one that a client
        # just made up.
        if session is None:
            raise SessionNotFound(f"Session '{session_id}' not found")
        return str(session.id)


class GetDisplaySessionStateUseCase:
    def __init__(
        self,
        pairing_store: DisplayPairingStore,
        lifecycle_repo: SessionLifecycleRepository,
        transient_store: SessionTransientStore | None = None,
    ) -> None:
        self._pairing_store = pairing_store
        self._lifecycle_repo = lifecycle_repo
        self._transient_store = transient_store

    def execute(self, code: str) -> DisplaySessionState:
        pairing = self._pairing_store.get(code)
        if pairing is None:
            raise DisplayPairingCodeNotFound(code)

        if pairing.is_expired():
            return DisplaySessionState(
                session_id=pairing.paired_session_id,
                device_type=pairing.device_type,
                status=DisplayPairingStatus.EXPIRED,
            )

        if pairing.status == DisplayPairingStatus.UNPAIRED:
            return DisplaySessionState(
                session_id=None,
                device_type=pairing.device_type,
                status=DisplayPairingStatus.UNPAIRED,
            )

        session = None
        if pairing.owner_id and pairing.paired_session_id:
            try:
                session = self._lifecycle_repo.get_session(
                    owner_id=UUID(pairing.owner_id), session_id=UUID(pairing.paired_session_id)
                )
            except (ValueError, TypeError):
                session = None

        if session is None:
            return DisplaySessionState(
                session_id=pairing.paired_session_id,
                device_type=pairing.device_type,
                status=pairing.status,
            )

        # Real-time progress comes exclusively from the transient store
        # (fed by PollVisionObservationsUseCase polling real Vision
        # observations). With no transient update published yet, the
        # display has nothing measured to show -- 0 reps and no active
        # exercise, never a fabricated placeholder.
        confirmed_reps = 0
        visibility_status: str | None = None
        active_exercise: str | None = None

        if self._transient_store:
            transient = self._transient_store.get_transient_update(session.id)
            if transient:
                confirmed_reps = transient.current_repetitions or 0
                visibility_status = transient.visibility_status
                active_exercise = transient.active_exercise_id

        return DisplaySessionState(
            session_id=str(session.id),
            device_type=pairing.device_type,
            status=pairing.status,
            mode=session.configuration.active_mode,
            intensity=session.configuration.intensity,
            state=session.state.value,
            active_exercise=active_exercise,
            confirmed_reps=confirmed_reps,
            visibility_status=visibility_status,
            pause_reason=session.pause_reason.value if session.pause_reason else None,
        )
