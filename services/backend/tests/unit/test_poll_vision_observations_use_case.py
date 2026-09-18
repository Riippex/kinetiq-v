from dataclasses import replace
from uuid import UUID, uuid4

from kinetiq.modules.workouts.application.observation_ingestion import (
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


class FakeSessionLifecycleRepository:
    def __init__(self) -> None:
        self.advance_calls: list[tuple[UUID, UUID, str]] = []

    def advance_vision_observation_cursor(
        self, *, owner_id: UUID, session_id: UUID, cursor: str
    ) -> None:
        self.advance_calls.append((owner_id, session_id, cursor))


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
    assert vision.calls == [("an_1", "2:5", 50)]
    assert len(store.published) == 2
    assert store.published[0].current_repetitions == 3
    assert store.published[0].pose_confidence == 0.9
    assert repo.advance_calls == [(session.owner_id, session.id, "2:7")]


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
    assert repo.advance_calls == [(session.owner_id, session.id, "2:6")]


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
    assert repo.advance_calls == [(session.owner_id, session.id, "3:1")]


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
