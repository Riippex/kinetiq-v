import threading
import time
from dataclasses import replace
from uuid import UUID, uuid4

from kinetiq.modules.workouts.application.observation_ingestion import (
    ObservationIngestionResult,
    PollVisionObservationsUseCase,
)
from kinetiq.modules.workouts.application.ports import (
    TransientSessionUpdate,
    VisionObservationInfo,
    VisionObservationsPage,
)
from kinetiq.modules.workouts.domain import (
    CoachingTone,
    SessionConfiguration,
    SessionIntensity,
    SessionMode,
    WorkoutSession,
)

ROUTINE_ID = uuid4()


class FakeVisionObservationSourcePort:
    def __init__(self, page: VisionObservationsPage) -> None:
        self.page = page
        self.calls: list[tuple[str, str | None, int]] = []

    def poll_observations(
        self, *, analysis_id: str, after_cursor: str | None, limit: int
    ) -> VisionObservationsPage:
        self.calls.append((analysis_id, after_cursor, limit))
        return self.page


class FakeSessionTransientStore:
    def __init__(self) -> None:
        self.published: list[TransientSessionUpdate] = []

    def publish_transient_update(self, update: TransientSessionUpdate) -> bool:
        self.published.append(update)
        return True

    def get_transient_update(self, session_id: UUID) -> TransientSessionUpdate | None:
        return self.published[-1] if self.published else None


class FlakyTransientStore:
    """Simulates a Redis publish that fails on a specific attempt (1-indexed),
    e.g. a connection drop partway through a batch."""

    def __init__(self, *, fail_on_attempt: int | None = None) -> None:
        self.published: list[TransientSessionUpdate] = []
        self.attempts = 0
        self._fail_on_attempt = fail_on_attempt

    def publish_transient_update(self, update: TransientSessionUpdate) -> bool:
        self.attempts += 1
        if self.attempts == self._fail_on_attempt:
            return False
        self.published.append(update)
        return True

    def get_transient_update(self, session_id: UUID) -> TransientSessionUpdate | None:
        return self.published[-1] if self.published else None


class FakeSessionLifecycleRepository:
    def __init__(self, *, lease_held: bool = False, cas_fails: bool = False) -> None:
        self.advance_calls: list[tuple[UUID, UUID, str | None, str]] = []
        self._lease_held = lease_held
        self._cas_fails = cas_fails
        self._lock = threading.Lock()
        self.poll_lease_acquire_calls = 0
        self.poll_lease_release_calls = 0

    def acquire_vision_poll_lease(
        self, *, owner_id: UUID, session_id: UUID, ttl_seconds: int
    ) -> str | None:
        with self._lock:
            self.poll_lease_acquire_calls += 1
            if self._lease_held:
                return None
            self._lease_held = True
            return "fake-poll-lease-token"

    def release_vision_poll_lease(
        self, *, owner_id: UUID, session_id: UUID, lease_token: str
    ) -> None:
        with self._lock:
            self.poll_lease_release_calls += 1
            self._lease_held = False

    def advance_vision_observation_cursor(
        self,
        *,
        owner_id: UUID,
        session_id: UUID,
        expected_previous_cursor: str | None,
        new_cursor: str,
    ) -> bool:
        self.advance_calls.append((owner_id, session_id, expected_previous_cursor, new_cursor))
        return not self._cas_fails


def tracking_session(*, epoch: int = 2, cursor: str | None = "2:5") -> WorkoutSession:
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
    base = WorkoutSession.prepare(
        session_id=uuid4(),
        owner_id=uuid4(),
        routine_id=ROUTINE_ID,
        routine_version=1,
        configuration=configuration,
    )
    return replace(
        base,
        state=base.state,
        target_person_id="cand_1",
        vision_analysis_id="an_1",
        vision_epoch=epoch,
        vision_observation_cursor=cursor,
    )


def observation(
    *,
    epoch: int,
    sequence: int,
    tracking_state: str = "CONFIRMED",
    visibility_state: str = "FULL",
    confirmed_repetitions: int = 0,
    last_repetition_confidence: float | None = None,
) -> VisionObservationInfo:
    return VisionObservationInfo(
        epoch=epoch,
        sequence=sequence,
        tracking_state=tracking_state,
        visibility_state=visibility_state,
        reason_code="OK",
        confirmed_repetitions=confirmed_repetitions,
        last_repetition_confidence=last_repetition_confidence,
    )


def test_publishes_new_observations_and_advances_cursor() -> None:
    session = tracking_session(epoch=2, cursor="2:5")
    page = VisionObservationsPage(
        observations=(
            observation(
                epoch=2, sequence=6, confirmed_repetitions=3, last_repetition_confidence=0.9
            ),
            observation(
                epoch=2, sequence=7, confirmed_repetitions=4, last_repetition_confidence=0.92
            ),
        ),
        next_cursor="2:7",
        has_more=False,
    )
    vision = FakeVisionObservationSourcePort(page)
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.published_count == 2
    assert result.skipped_stale_epoch == 0
    assert result.skipped_duplicate_sequence == 0
    assert result.next_cursor == "2:7"
    assert result.lease_contended is False
    assert result.publish_failed is False
    assert result.cursor_advanced is True
    assert vision.calls == [("an_1", "2:5", 50)]
    assert len(store.published) == 2
    assert store.published[0].current_repetitions == 3
    assert store.published[0].pose_confidence == 0.9
    assert repo.advance_calls == [(session.owner_id, session.id, "2:5", "2:7")]
    assert repo.poll_lease_acquire_calls == 1
    assert repo.poll_lease_release_calls == 1


def test_rejects_observations_from_a_stale_epoch() -> None:
    """Regression test: an observation produced under a previous epoch
    (e.g. before a re-target) must never be published as if it were
    current."""
    session = tracking_session(epoch=3, cursor=None)
    page = VisionObservationsPage(
        observations=(observation(epoch=2, sequence=1),),
        next_cursor="2:1",
        has_more=False,
    )
    vision = FakeVisionObservationSourcePort(page)
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.published_count == 0
    assert result.skipped_stale_epoch == 1
    assert store.published == []
    assert repo.advance_calls == []


def test_rejects_duplicate_or_out_of_order_sequences() -> None:
    """Regression test: replaying observations already covered by the
    persisted cursor (e.g. an overlapping poll) must not double-publish."""
    session = tracking_session(epoch=2, cursor="2:5")
    page = VisionObservationsPage(
        observations=(
            observation(epoch=2, sequence=4),  # already covered
            observation(epoch=2, sequence=5),  # already covered (boundary)
            observation(epoch=2, sequence=6, confirmed_repetitions=1),  # new
        ),
        next_cursor="2:6",
        has_more=False,
    )
    vision = FakeVisionObservationSourcePort(page)
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.published_count == 1
    assert result.skipped_duplicate_sequence == 2
    assert len(store.published) == 1
    assert repo.advance_calls == [(session.owner_id, session.id, "2:5", "2:6")]


def test_cursor_from_a_previous_epoch_does_not_suppress_the_new_epoch() -> None:
    """A cursor saved under the prior epoch must not be mistaken for a
    duplicate marker once the session has been re-targeted (new epoch) --
    sequence numbers restart and are not comparable across epochs."""
    session = tracking_session(epoch=3, cursor="2:99")
    page = VisionObservationsPage(
        observations=(observation(epoch=3, sequence=1, confirmed_repetitions=1),),
        next_cursor="3:1",
        has_more=False,
    )
    vision = FakeVisionObservationSourcePort(page)
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.published_count == 1
    assert result.skipped_duplicate_sequence == 0
    assert repo.advance_calls == [(session.owner_id, session.id, "2:99", "3:1")]


def test_maps_lost_tracking_to_not_visible_regardless_of_visibility_state() -> None:
    session = tracking_session(epoch=2, cursor=None)
    page = VisionObservationsPage(
        observations=(
            observation(epoch=2, sequence=1, tracking_state="AMBIGUOUS", visibility_state="FULL"),
        ),
        next_cursor="2:1",
        has_more=False,
    )
    vision = FakeVisionObservationSourcePort(page)
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    use_case.execute(session=session)

    assert store.published[0].visibility_status == "NOT_VISIBLE"


def test_no_op_when_no_vision_analysis_started() -> None:
    session = replace(tracking_session(), vision_analysis_id=None)
    vision = FakeVisionObservationSourcePort(
        VisionObservationsPage(observations=(), next_cursor=None, has_more=False)
    )
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.published_count == 0
    assert vision.calls == []
    assert repo.advance_calls == []
    # No analysis to poll -- must not even attempt the lease.
    assert repo.poll_lease_acquire_calls == 0


def test_lease_contention_skips_the_poll_without_calling_vision() -> None:
    """Regression test: a second worker must never call Vision or publish
    anything for a session another worker is already polling."""
    session = tracking_session(epoch=2, cursor="2:5")
    vision = FakeVisionObservationSourcePort(
        VisionObservationsPage(observations=(), next_cursor=None, has_more=False)
    )
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository(lease_held=True)
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.lease_contended is True
    assert result.published_count == 0
    assert vision.calls == []
    assert store.published == []
    assert repo.advance_calls == []
    # The failed acquisition attempt has nothing to release.
    assert repo.poll_lease_release_calls == 0


def test_publish_failure_stops_and_advances_cursor_only_to_last_success() -> None:
    """Regression test: `publish_transient_update`'s return value must be
    respected. On a failed publish (e.g. Redis unreachable), the pass must
    stop -- the failed observation and anything after it must never be
    published, and the cursor must not advance past the last observation
    that was actually published successfully."""
    session = tracking_session(epoch=2, cursor="2:5")
    page = VisionObservationsPage(
        observations=(
            observation(epoch=2, sequence=6, confirmed_repetitions=1),
            observation(epoch=2, sequence=7, confirmed_repetitions=2),  # publish fails here
            observation(epoch=2, sequence=8, confirmed_repetitions=3),  # must never be reached
        ),
        next_cursor="2:8",
        has_more=False,
    )
    vision = FakeVisionObservationSourcePort(page)
    store = FlakyTransientStore(fail_on_attempt=2)
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.published_count == 1
    assert result.publish_failed is True
    assert len(store.published) == 1
    assert store.published[0].current_repetitions == 1
    assert result.next_cursor == "2:6"
    assert repo.advance_calls == [(session.owner_id, session.id, "2:5", "2:6")]


def test_cas_failure_on_cursor_advance_is_reported_and_does_not_regress() -> None:
    """If the compare-and-swap loses (another worker already advanced the
    cursor further, e.g. after this worker's lease expired mid-poll), the
    result reports cursor_advanced=False and next_cursor falls back to the
    cursor this pass started from -- it must never claim to have advanced
    to a cursor that was not actually persisted. The already-published
    update itself cannot be unpublished; this is a disclosed, acceptable
    at-least-once duplicate risk for the rare lease-expiry race, not a
    data-loss risk."""
    session = tracking_session(epoch=2, cursor="2:5")
    page = VisionObservationsPage(
        observations=(observation(epoch=2, sequence=6, confirmed_repetitions=1),),
        next_cursor="2:6",
        has_more=False,
    )
    vision = FakeVisionObservationSourcePort(page)
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository(cas_fails=True)
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    result = use_case.execute(session=session)

    assert result.published_count == 1
    assert result.cursor_advanced is False
    assert result.next_cursor == "2:5"
    assert repo.advance_calls == [(session.owner_id, session.id, "2:5", "2:6")]


def test_two_workers_racing_on_the_same_session_only_one_polls() -> None:
    """Two worker processes/threads both trying to poll the same session
    at the same time must never both reach Vision or both publish -- the
    per-session poll lease serializes them, and exactly one succeeds while
    the other reports lease_contended without touching Vision or Redis."""
    session = tracking_session(epoch=2, cursor="2:5")
    page = VisionObservationsPage(
        observations=(observation(epoch=2, sequence=6, confirmed_repetitions=1),),
        next_cursor="2:6",
        has_more=False,
    )
    lease_holder_started = threading.Event()

    class SlowVisionObservationSourcePort:
        def __init__(self) -> None:
            self.calls = 0

        def poll_observations(
            self, *, analysis_id: str, after_cursor: str | None, limit: int
        ) -> VisionObservationsPage:
            self.calls += 1
            lease_holder_started.set()
            time.sleep(0.3)
            return page

    vision = SlowVisionObservationSourcePort()
    store = FakeSessionTransientStore()
    repo = FakeSessionLifecycleRepository()
    use_case = PollVisionObservationsUseCase(repo, vision, store)

    results: dict[str, ObservationIngestionResult] = {}

    def worker_a() -> None:
        results["a"] = use_case.execute(session=session)

    def worker_b() -> None:
        lease_holder_started.wait(timeout=5)
        results["b"] = use_case.execute(session=session)

    thread_a = threading.Thread(target=worker_a)
    thread_b = threading.Thread(target=worker_b)
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=5)
    thread_b.join(timeout=5)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()
    assert vision.calls == 1

    contended = [r for r in results.values() if r.lease_contended]
    succeeded = [r for r in results.values() if not r.lease_contended]
    assert len(contended) == 1
    assert len(succeeded) == 1
    assert succeeded[0].published_count == 1
    assert len(store.published) == 1
