from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from kinetiq.modules.workouts.application.display_pairing_use_cases import (
    GetDisplaySessionStateUseCase,
    IssueDisplayPairingCodeUseCase,
    PairDisplayDeviceUseCase,
)
from kinetiq.modules.workouts.application.ports import TransientSessionUpdate
from kinetiq.modules.workouts.application.session_lifecycle import SessionNotFound
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    SessionConfiguration,
    SessionIntensity,
    SessionMode,
    WorkoutSession,
)
from kinetiq.modules.workouts.domain.display_pairing import (
    DisplayDeviceType,
    DisplayPairingCode,
    DisplayPairingCodeExpired,
    DisplayPairingCodeNotFound,
    DisplayPairingCodePaired,
    DisplayPairingStatus,
    InMemoryDisplayPairingStore,
)


class DummyLifecycleRepo:
    def __init__(self, session=None):
        self._session = session

    def get_session(self, *, owner_id, session_id):
        if self._session and str(self._session.id) == str(session_id) and str(
            owner_id
        ) == str(self._session.owner_id):
            return self._session
        return None


class DummyTransientStore:
    def __init__(self, update=None):
        self._update = update

    def publish_transient_update(self, update):
        self._update = update
        return True

    def get_transient_update(self, session_id):
        if self._update and self._update.session_id == session_id:
            return self._update
        return None


def test_issue_display_pairing_code_creates_and_saves():
    store = InMemoryDisplayPairingStore()
    use_case = IssueDisplayPairingCodeUseCase(store)

    pairing = use_case.execute(DisplayDeviceType.FIRE_TV)

    assert pairing.code.startswith("FIRE-")
    assert len(pairing.code) == len("FIRE-") + 6
    assert pairing.device_type == DisplayDeviceType.FIRE_TV
    assert pairing.status == DisplayPairingStatus.UNPAIRED
    assert store.get(pairing.code) == pairing


def test_issue_display_pairing_code_is_not_predictable():
    """Regression test: the pairing code must never be a fixed, guessable
    default -- a predictable code would let an unrelated party pair their
    own display to someone else's session."""
    store = InMemoryDisplayPairingStore()
    use_case = IssueDisplayPairingCodeUseCase(store)

    codes = {use_case.execute(DisplayDeviceType.FIRE_TV).code for _ in range(20)}

    assert "FIRE-7892" not in codes
    assert len(codes) == 20


def test_pair_display_device_not_found():
    store = InMemoryDisplayPairingStore()
    repo = DummyLifecycleRepo()
    use_case = PairDisplayDeviceUseCase(store, repo)

    with pytest.raises(DisplayPairingCodeNotFound):
        use_case.execute("user-1", "NON_EXISTENT")


def test_pair_display_device_rejects_nonexistent_session_id():
    """Regression test: a session_id that does not exist at all must
    reject the pairing rather than silently attaching an unvalidated ID."""
    store = InMemoryDisplayPairingStore()
    issue_use_case = IssueDisplayPairingCodeUseCase(store)
    pairing = issue_use_case.execute(DisplayDeviceType.FIRE_TV)

    repo = DummyLifecycleRepo(session=None)
    use_case = PairDisplayDeviceUseCase(store, repo)

    with pytest.raises(SessionNotFound):
        use_case.execute(str(uuid4()), pairing.code, session_id=str(uuid4()))

    # The pairing must remain UNPAIRED -- a rejected session_id must not
    # leave a half-applied pairing behind.
    assert store.get(pairing.code).status == DisplayPairingStatus.UNPAIRED


def test_pair_display_device_rejects_foreign_session_id():
    """Regression test: a session_id that exists but belongs to a
    different owner must be rejected exactly like a nonexistent one --
    get_session is owner-scoped, so this session_id truly does not exist
    from this owner's point of view."""

    class _Session:
        def __init__(self, session_id, owner_id):
            self.id = session_id
            self.owner_id = owner_id

    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)

    foreign_owner = uuid4()
    foreign_session = _Session(session_id=uuid4(), owner_id=foreign_owner)
    repo = DummyLifecycleRepo(session=foreign_session)
    use_case = PairDisplayDeviceUseCase(store, repo)

    with pytest.raises(SessionNotFound):
        use_case.execute(str(uuid4()), pairing.code, session_id=str(foreign_session.id))


def test_pair_display_device_rejects_repairing_to_a_different_owner():
    """Regression test: a code already paired to one owner must never be
    re-pairable by a different owner -- that would let a second athlete
    who observed or guessed a live code hijack the display."""
    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    use_case = PairDisplayDeviceUseCase(store, DummyLifecycleRepo())

    owner_a = str(uuid4())
    owner_b = str(uuid4())
    use_case.execute(owner_a, pairing.code)

    with pytest.raises(DisplayPairingCodePaired):
        use_case.execute(owner_b, pairing.code)

    # The original owner's pairing must be untouched by the rejected attempt.
    assert store.get(pairing.code).owner_id == owner_a


def test_pair_display_device_allows_same_owner_to_repair():
    """The same owner re-pairing the same code (e.g. the TV app
    restarting) must not be rejected as a hijack attempt."""
    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    use_case = PairDisplayDeviceUseCase(store, DummyLifecycleRepo())

    owner_a = str(uuid4())
    first = use_case.execute(owner_a, pairing.code)
    second = use_case.execute(owner_a, pairing.code)

    assert first.status == DisplayPairingStatus.PAIRED
    assert second.status == DisplayPairingStatus.PAIRED


def test_pair_display_device_expired():
    store = InMemoryDisplayPairingStore()
    past = datetime.now(UTC) - timedelta(minutes=20)
    expired_code = DisplayPairingCode(
        code="EXPIRED-01",
        device_type=DisplayDeviceType.VEGA_OS,
        created_at=past - timedelta(minutes=15),
        expires_at=past,
    )
    assert store.create_if_absent(expired_code)

    repo = DummyLifecycleRepo()
    use_case = PairDisplayDeviceUseCase(store, repo)

    with pytest.raises(DisplayPairingCodeExpired):
        use_case.execute("user-1", "EXPIRED-01")


def test_pair_display_device_allows_same_owner_to_repair_after_claim_window_expires():
    """`expires_at` is the short-lived claim window for an unpaired code, not
    the paired session's lifetime: a workout running longer than 15 minutes
    must not lock the same owner out of reconnecting (e.g. the TV app
    restarting mid-workout)."""
    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    use_case = PairDisplayDeviceUseCase(store, DummyLifecycleRepo())
    owner_a = str(uuid4())
    first = use_case.execute(owner_a, pairing.code)

    long_expired = DisplayPairingCode(
        code=first.code,
        device_type=first.device_type,
        created_at=first.created_at,
        expires_at=first.created_at - timedelta(minutes=1),
        status=first.status,
        paired_session_id=first.paired_session_id,
        owner_id=first.owner_id,
        version=first.version,
    )
    assert store.compare_and_save(expected_version=first.version, pairing=long_expired)

    second = use_case.execute(owner_a, pairing.code)
    assert second.status == DisplayPairingStatus.PAIRED


def test_pair_display_device_rejects_other_owner_even_after_claim_window_expires():
    """The claim-window exemption for an already-PAIRED code must never
    reopen it to hijacking: a different owner is still rejected."""
    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.VEGA_OS)
    use_case = PairDisplayDeviceUseCase(store, DummyLifecycleRepo())
    owner_a = str(uuid4())
    first = use_case.execute(owner_a, pairing.code)

    expired = DisplayPairingCode(
        code=first.code,
        device_type=first.device_type,
        created_at=first.created_at,
        expires_at=first.created_at - timedelta(minutes=1),
        status=first.status,
        paired_session_id=first.paired_session_id,
        owner_id=first.owner_id,
        version=first.version,
    )
    assert store.compare_and_save(expected_version=first.version, pairing=expired)

    with pytest.raises(DisplayPairingCodePaired):
        use_case.execute(str(uuid4()), pairing.code)


def test_get_display_session_state_unpaired():
    store = InMemoryDisplayPairingStore()
    issue_use_case = IssueDisplayPairingCodeUseCase(store)
    pairing = issue_use_case.execute(DisplayDeviceType.VEGA_OS)

    get_use_case = GetDisplaySessionStateUseCase(store, DummyLifecycleRepo())
    state = get_use_case.execute(pairing.code)

    assert state.device_type == DisplayDeviceType.VEGA_OS
    assert state.status == DisplayPairingStatus.UNPAIRED
    assert state.session_id is None


def _prepared_session(owner_id) -> WorkoutSession:
    configuration = SessionConfiguration(
        requested_mode=SessionMode.NORMAL,
        active_mode=SessionMode.NORMAL,
        intensity=SessionIntensity.PLANNED,
        coaching_tone=CoachingTone.CALM,
        capture_device_id="phone-camera-01",
        display_device_id=None,
        prompt_for_progress_photo=False,
        dynamic=None,
    )
    return WorkoutSession.prepare(
        session_id=uuid4(),
        owner_id=owner_id,
        routine_id=uuid4(),
        routine_version=1,
        configuration=configuration,
    ).start()


def test_get_display_session_state_paired_reads_real_transient_progress():
    """Regression test: the previous implementation called a nonexistent
    transient-store method (get_transient_state) and read mismatched
    field names (confirmed_reps, visibility_status.value) -- this would
    have raised AttributeError against the real port the moment a display
    was actually paired to a live session."""
    owner_id = uuid4()
    session = _prepared_session(owner_id)

    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    repo = DummyLifecycleRepo(session=session)
    PairDisplayDeviceUseCase(store, repo).execute(
        str(owner_id), pairing.code, session_id=str(session.id)
    )

    transient_store = DummyTransientStore(
        TransientSessionUpdate(
            session_id=session.id,
            active_exercise_id="bodyweight_squat",
            current_repetitions=6,
            visibility_status="VISIBLE",
        )
    )
    get_use_case = GetDisplaySessionStateUseCase(store, repo, transient_store)

    state = get_use_case.execute(pairing.code)

    assert state.session_id == str(session.id)
    assert state.status == DisplayPairingStatus.PAIRED
    assert state.mode == SessionMode.NORMAL
    assert state.intensity == SessionIntensity.PLANNED
    assert state.state == "ACTIVE"
    assert state.active_exercise == "bodyweight_squat"
    assert state.confirmed_reps == 6
    assert state.visibility_status == "VISIBLE"


def test_get_display_session_state_paired_without_transient_update_shows_no_fabricated_progress():
    """No transient update has been published yet (e.g. Vision has not
    detected a rep) -- the display must show zero/none, never a
    hardcoded placeholder like 'Goblet Squat' or an invented rep count."""
    owner_id = uuid4()
    session = _prepared_session(owner_id)

    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.VEGA_OS)
    repo = DummyLifecycleRepo(session=session)
    PairDisplayDeviceUseCase(store, repo).execute(
        str(owner_id), pairing.code, session_id=str(session.id)
    )

    get_use_case = GetDisplaySessionStateUseCase(store, repo, DummyTransientStore())
    state = get_use_case.execute(pairing.code)

    assert state.active_exercise is None
    assert state.confirmed_reps == 0
    assert state.visibility_status is None


def test_get_display_session_state_stays_live_past_the_original_claim_window():
    """A workout running longer than the 15-minute claim window must keep
    reporting real, live progress -- not flip to EXPIRED and have the
    display overwrite its last good state (reps, active exercise) with
    zeroed defaults mid-workout."""
    owner_id = uuid4()
    session = _prepared_session(owner_id)

    store = InMemoryDisplayPairingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    repo = DummyLifecycleRepo(session=session)
    paired = PairDisplayDeviceUseCase(store, repo).execute(
        str(owner_id), pairing.code, session_id=str(session.id)
    )

    # Simulate the original 15-minute claim window having long since passed.
    long_expired = DisplayPairingCode(
        code=paired.code,
        device_type=paired.device_type,
        created_at=paired.created_at,
        expires_at=paired.created_at - timedelta(minutes=1),
        status=paired.status,
        paired_session_id=paired.paired_session_id,
        owner_id=paired.owner_id,
        version=paired.version,
    )
    assert store.compare_and_save(expected_version=paired.version, pairing=long_expired)

    transient_store = DummyTransientStore(
        TransientSessionUpdate(
            session_id=session.id,
            active_exercise_id="bodyweight_squat",
            current_repetitions=11,
            visibility_status="VISIBLE",
        )
    )
    get_use_case = GetDisplaySessionStateUseCase(store, repo, transient_store)

    state = get_use_case.execute(pairing.code)

    assert state.status == DisplayPairingStatus.PAIRED
    assert state.confirmed_reps == 11
    assert state.active_exercise == "bodyweight_squat"
