from dataclasses import dataclass
from uuid import UUID

from kinetiq.modules.workouts.application.ports import (
    SessionLifecycleRepository,
    SessionTransientStore,
    TransientSessionUpdate,
    VisionObservationInfo,
    VisionObservationSourcePort,
)
from kinetiq.modules.workouts.domain import WorkoutSession

_LOST_TRACKING_STATES = frozenset({"SEARCHING", "AMBIGUOUS", "LOST"})
_VISIBILITY_STATE_TO_STATUS = {
    "FULL": "VISIBLE",
    "PARTIAL": "PARTIALLY_VISIBLE",
    "OCCLUDED": "NOT_VISIBLE",
    "ABSENT": "NOT_VISIBLE",
}


@dataclass(frozen=True, slots=True)
class ObservationIngestionResult:
    session_id: UUID
    published_count: int
    skipped_stale_epoch: int
    skipped_duplicate_sequence: int
    next_cursor: str | None


def _parse_cursor(cursor: str | None) -> tuple[int, int] | None:
    if cursor is None:
        return None
    try:
        epoch_str, sequence_str = cursor.split(":", 1)
        return int(epoch_str), int(sequence_str)
    except (ValueError, IndexError):
        return None


def _map_visibility_status(observation: VisionObservationInfo) -> str:
    if observation.tracking_state in _LOST_TRACKING_STATES:
        return "NOT_VISIBLE"
    return _VISIBILITY_STATE_TO_STATUS.get(observation.visibility_state, "NOT_VISIBLE")


def _to_transient_update(
    *, session_id: UUID, active_exercise_id: str | None, observation: VisionObservationInfo
) -> TransientSessionUpdate:
    pose_confidence = (
        observation.last_repetition_confidence
        if observation.last_repetition_confidence is not None
        else observation.hold_confidence
    )
    return TransientSessionUpdate(
        session_id=session_id,
        active_exercise_id=active_exercise_id,
        current_repetitions=(
            observation.confirmed_repetitions if observation.confirmed_repetitions else None
        ),
        current_duration_seconds=(
            int(observation.hold_elapsed_seconds)
            if observation.hold_elapsed_seconds is not None
            else None
        ),
        pose_confidence=pose_confidence,
        visibility_status=_map_visibility_status(observation),
    )


class PollVisionObservationsUseCase:
    """Polls Vision for new observations on a single session's active,
    confirmed-target analysis, by cursor, and fans them out as validated
    TransientSessionUpdates -- the real observation-ingestion path KV-403
    was missing (the earlier pass wired the Redis publish/subscribe
    plumbing but had no real producer feeding it).

    Rejects observations from a stale epoch (the session was re-targeted
    since Vision produced them) and duplicate or out-of-order sequences
    (the persisted cursor already advanced past them, e.g. an overlapping
    poll), so a retried or concurrent poll cannot double-publish or regress
    the session's observation cursor.

    Scoping decision, disclosed: this maps Vision's per-observation
    tracking/visibility state onto `TransientSessionUpdate.visibility_status`
    (the field the transient-update contract already exposes for a client
    to react to lost/ambiguous tracking) but does not itself transition the
    WorkoutSession's persisted lifecycle state (e.g. auto-pause). Auto-pause
    driven by sustained tracking loss is a further behavioral decision with
    its own idempotency/revision semantics, intentionally left to a
    separate pass rather than folded into this cursor-polling worker.
    """

    def __init__(
        self,
        repository: SessionLifecycleRepository,
        vision_observations: VisionObservationSourcePort,
        transient_store: SessionTransientStore,
    ) -> None:
        self._repository = repository
        self._vision_observations = vision_observations
        self._transient_store = transient_store

    def execute(
        self,
        *,
        session: WorkoutSession,
        active_exercise_id: str | None = None,
        limit: int = 50,
    ) -> ObservationIngestionResult:
        if session.vision_analysis_id is None:
            return ObservationIngestionResult(
                session_id=session.id,
                published_count=0,
                skipped_stale_epoch=0,
                skipped_duplicate_sequence=0,
                next_cursor=session.vision_observation_cursor,
            )

        last_cursor = _parse_cursor(session.vision_observation_cursor)
        page = self._vision_observations.poll_observations(
            analysis_id=session.vision_analysis_id,
            after_cursor=session.vision_observation_cursor,
            limit=limit,
        )

        published = 0
        skipped_stale_epoch = 0
        skipped_duplicate_sequence = 0
        latest_cursor = session.vision_observation_cursor

        for observation in page.observations:
            if observation.epoch != session.vision_epoch:
                skipped_stale_epoch += 1
                continue
            if (
                last_cursor is not None
                and last_cursor[0] == observation.epoch
                and observation.sequence <= last_cursor[1]
            ):
                skipped_duplicate_sequence += 1
                continue

            update = _to_transient_update(
                session_id=session.id,
                active_exercise_id=active_exercise_id,
                observation=observation,
            )
            self._transient_store.publish_transient_update(update)

            published += 1
            last_cursor = (observation.epoch, observation.sequence)
            latest_cursor = f"{observation.epoch}:{observation.sequence}"

        if latest_cursor != session.vision_observation_cursor:
            self._repository.advance_vision_observation_cursor(
                owner_id=session.owner_id, session_id=session.id, cursor=latest_cursor
            )

        return ObservationIngestionResult(
            session_id=session.id,
            published_count=published,
            skipped_stale_epoch=skipped_stale_epoch,
            skipped_duplicate_sequence=skipped_duplicate_sequence,
            next_cursor=latest_cursor,
        )
