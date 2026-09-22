from kinetiq.modules.integrations.vision_adapter import (
    VisionObservationDTO,
    VisionObservationsPageDTO,
    VisionRepetitionDTO,
)
from kinetiq.modules.workouts.infrastructure.vision_observation_adapter import (
    VisionRestObservationAdapter,
)


class FakeVisionRestAdapter:
    def __init__(self, page: VisionObservationsPageDTO) -> None:
        self.page = page
        self.calls: list[tuple[str, str | None, int]] = []

    def poll_observations(
        self, *, analysis_id: str, after_cursor: str | None, limit: int
    ) -> VisionObservationsPageDTO:
        self.calls.append((analysis_id, after_cursor, limit))
        return self.page


def _observation_dto(
    *,
    session_id: str = "session-1",
    target_person_id: str = "cand_1",
    exercise_key: str = "push_up",
) -> VisionObservationDTO:
    return VisionObservationDTO(
        session_id=session_id,
        epoch=2,
        sequence=6,
        timestamp_utc="2026-01-01T00:00:00Z",
        target_person_id=target_person_id,
        exercise_key=exercise_key,
        exercise_version=1,
        tracking_state="CONFIRMED",
        visibility_state="FULL",
        reason_code="OK",
        repetitions=(
            VisionRepetitionDTO(
                repetition_index=0,
                start_timestamp="2026-01-01T00:00:00Z",
                end_timestamp="2026-01-01T00:00:01Z",
                confidence=0.9,
                quality_score=0.8,
            ),
        ),
    )


def test_poll_observations_carries_identity_through_to_the_application_layer() -> None:
    """Third Codex adversarial-review pass: the Vision contract supplies
    session_id, target_person_id and exercise_key on every observation --
    this adapter must not drop them before the application layer's
    trust-boundary check gets a chance to validate them."""
    dto = _observation_dto(
        session_id="session-42", target_person_id="cand_7", exercise_key="goblet_squat"
    )
    page = VisionObservationsPageDTO(observations=(dto,), next_cursor="2:6", has_more=False)
    adapter = VisionRestObservationAdapter(FakeVisionRestAdapter(page))

    result = adapter.poll_observations(analysis_id="an_1", after_cursor=None, limit=50)

    (observation,) = result.observations
    assert observation.session_id == "session-42"
    assert observation.target_person_id == "cand_7"
    assert observation.exercise_key == "goblet_squat"
    assert observation.epoch == 2
    assert observation.sequence == 6
    assert observation.confirmed_repetitions == 1
    assert result.next_cursor == "2:6"
    assert result.has_more is False
