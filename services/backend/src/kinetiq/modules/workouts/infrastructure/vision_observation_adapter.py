from kinetiq.modules.integrations.vision_adapter import VisionRestAdapter
from kinetiq.modules.workouts.application.ports import (
    VisionObservationInfo,
    VisionObservationsPage,
)


class VisionRestObservationAdapter:
    """Adapts VisionRestAdapter.poll_observations (which returns the
    integrations module's own nested DTOs) to the workouts application
    layer's VisionObservationSourcePort, flattening each observation's
    repetitions/hold sub-objects into the fields PollVisionObservationsUseCase
    actually reads. Keeps the application layer's port decoupled from the
    integrations module's DTOs, mirroring how VisionCandidateInfo and
    VisionAnalysisHandle already decouple from that module elsewhere."""

    def __init__(self, adapter: VisionRestAdapter) -> None:
        self._adapter = adapter

    def poll_observations(
        self, *, analysis_id: str, after_cursor: str | None, limit: int
    ) -> VisionObservationsPage:
        page = self._adapter.poll_observations(
            analysis_id=analysis_id, after_cursor=after_cursor, limit=limit
        )
        observations = tuple(
            VisionObservationInfo(
                session_id=observation.session_id,
                target_person_id=observation.target_person_id,
                exercise_key=observation.exercise_key,
                epoch=observation.epoch,
                sequence=observation.sequence,
                tracking_state=observation.tracking_state,
                visibility_state=observation.visibility_state,
                reason_code=observation.reason_code,
                confirmed_repetitions=observation.confirmed_repetition_count,
                hold_elapsed_seconds=(
                    observation.hold.elapsed_seconds if observation.hold else None
                ),
                hold_confidence=observation.hold.confidence if observation.hold else None,
                last_repetition_confidence=(
                    observation.repetitions[-1].confidence if observation.repetitions else None
                ),
            )
            for observation in page.observations
        )
        return VisionObservationsPage(
            observations=observations, next_cursor=page.next_cursor, has_more=page.has_more
        )
