import logging
from dataclasses import dataclass
from uuid import UUID

from kinetiq.modules.workouts.application.ports import (
    SessionLifecycleRepository,
    SessionTransientStore,
    TransientSessionUpdate,
    VisionObservationInfo,
    VisionObservationQuarantinePort,
    VisionObservationSourcePort,
)
from kinetiq.modules.workouts.domain import WorkoutSession

logger = logging.getLogger(__name__)

_LOST_TRACKING_STATES = frozenset({"SEARCHING", "AMBIGUOUS", "LOST"})
_VISIBILITY_STATE_TO_STATUS = {
    "FULL": "VISIBLE",
    "PARTIAL": "PARTIALLY_VISIBLE",
    "OCCLUDED": "NOT_VISIBLE",
    "ABSENT": "NOT_VISIBLE",
}

POLL_LEASE_TTL_SECONDS = 30
"""Must comfortably exceed one poll-and-publish pass (a Vision GET plus up
to `limit` Redis publishes); if a worker crashes or hangs mid-pass, the
lease self-expires after this many seconds rather than starving that
session's observations forever."""


@dataclass(frozen=True, slots=True)
class ObservationIngestionResult:
    session_id: UUID
    published_count: int
    skipped_stale_epoch: int
    skipped_duplicate_sequence: int
    next_cursor: str | None
    lease_contended: bool = False
    publish_failed: bool = False
    skipped_identity_mismatch: int = 0
    cursor_advanced: bool = True


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

    Trust boundary: rejects any observation whose `session_id` or
    `target_person_id` does not match this session/its confirmed target --
    Vision's response is untrusted input, and publishing it regardless
    would attribute another session's or person's repetitions to this
    athlete. A mismatch is persisted to a durable quarantine record (never
    just a log line, so it stays investigable/alertable) and the resume
    cursor advances past it -- one corrupted or mixed-analysis observation
    must not wedge the session's live tracking for the rest of its
    lifetime; every mismatch is still individually recorded no matter how
    many occur. Rejects observations from a stale epoch (the session was
    re-targeted since Vision produced them) and duplicate or out-of-order
    sequences (the persisted cursor already advanced past them, e.g. an
    overlapping poll). The resume cursor persisted for the next poll
    advances past every stale/duplicate/quarantined observation in a fully
    processed page (using Vision's own page-end cursor), so a page that
    happens to be entirely rejected (e.g. right after a retarget) does not
    permanently stall ingestion on it; it never advances past a failed
    publish, which still stops the pass so a retry re-attempts it.

    Retry-safety (this pass): a per-session poll lease
    (`acquire_vision_poll_lease`) is held for the whole pass so two worker
    processes can never poll and publish the same session concurrently --
    fixing the previous version, which had no such guard and could
    double-publish or race its own cursor advance against another worker.
    `publish_transient_update`'s return value is now respected: on a
    failed publish (e.g. Redis unreachable), the pass stops immediately
    and the cursor is advanced only up to the last *successfully*
    published observation, never past the failure -- a retry will
    naturally re-attempt the failed observation rather than silently
    skipping it. The cursor write itself is a compare-and-swap
    (`advance_vision_observation_cursor`) against the cursor value this
    pass started from, so a worker whose poll lease expired mid-pass (and
    was then claimed by a second worker that has since advanced further)
    cannot regress the cursor backward when it finally finishes.

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
        quarantine: VisionObservationQuarantinePort,
    ) -> None:
        self._repository = repository
        self._vision_observations = vision_observations
        self._transient_store = transient_store
        self._quarantine = quarantine

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

        lease_token = self._repository.acquire_vision_poll_lease(
            owner_id=session.owner_id, session_id=session.id, ttl_seconds=POLL_LEASE_TTL_SECONDS
        )
        if lease_token is None:
            # Another worker is already polling/publishing this session --
            # fail fast rather than risk a concurrent double-publish.
            return ObservationIngestionResult(
                session_id=session.id,
                published_count=0,
                skipped_stale_epoch=0,
                skipped_duplicate_sequence=0,
                next_cursor=session.vision_observation_cursor,
                lease_contended=True,
            )

        try:
            starting_cursor = session.vision_observation_cursor
            last_cursor = _parse_cursor(starting_cursor)
            page = self._vision_observations.poll_observations(
                analysis_id=session.vision_analysis_id,
                after_cursor=starting_cursor,
                limit=limit,
            )

            published = 0
            skipped_stale_epoch = 0
            skipped_duplicate_sequence = 0
            skipped_identity_mismatch = 0
            publish_failed = False
            latest_cursor = starting_cursor
            expected_session_id = str(session.id)

            for observation in page.observations:
                if observation.session_id != expected_session_id or (
                    session.target_person_id is not None
                    and observation.target_person_id != session.target_person_id
                ):
                    # Untrusted input: Vision's response does not belong to
                    # this session/confirmed target. Never publish it, but
                    # persist it durably (investigable/alertable, unlike a
                    # log line) and advance past it -- one corrupted or
                    # mixed-analysis observation must not wedge this
                    # session's live tracking for the rest of its lifetime.
                    logger.error(
                        "Vision observation identity mismatch for session %s: "
                        "observation session_id=%s target_person_id=%s "
                        "(expected session_id=%s target_person_id=%s)",
                        session.id,
                        observation.session_id,
                        observation.target_person_id,
                        expected_session_id,
                        session.target_person_id,
                    )
                    self._quarantine.quarantine(
                        owner_id=session.owner_id,
                        session_id=session.id,
                        analysis_id=session.vision_analysis_id,
                        observed_session_id=observation.session_id,
                        observed_target_person_id=observation.target_person_id,
                        expected_session_id=expected_session_id,
                        expected_target_person_id=session.target_person_id,
                        epoch=observation.epoch,
                        sequence=observation.sequence,
                    )
                    skipped_identity_mismatch += 1
                    latest_cursor = f"{observation.epoch}:{observation.sequence}"
                    continue
                if observation.epoch != session.vision_epoch:
                    skipped_stale_epoch += 1
                    latest_cursor = f"{observation.epoch}:{observation.sequence}"
                    continue
                if (
                    last_cursor is not None
                    and last_cursor[0] == observation.epoch
                    and observation.sequence <= last_cursor[1]
                ):
                    skipped_duplicate_sequence += 1
                    latest_cursor = f"{observation.epoch}:{observation.sequence}"
                    continue

                update = _to_transient_update(
                    session_id=session.id,
                    active_exercise_id=active_exercise_id,
                    observation=observation,
                )
                if not self._transient_store.publish_transient_update(update):
                    # Never advance the cursor past a failed publication:
                    # stop here so a retry re-fetches and re-attempts this
                    # exact observation instead of silently skipping it.
                    publish_failed = True
                    break

                published += 1
                last_cursor = (observation.epoch, observation.sequence)
                latest_cursor = f"{observation.epoch}:{observation.sequence}"
            else:
                # The whole page was safely processed (no publish failure --
                # the only thing that still stops the loop early): Vision's
                # own page-end cursor guarantees forward progress through
                # its stream even when every observation in this page was
                # stale/duplicate/quarantined for us, so a page we can never
                # locally accept does not permanently stall the next poll.
                if page.next_cursor is not None:
                    latest_cursor = page.next_cursor

            cursor_advanced = True
            if latest_cursor != starting_cursor:
                assert latest_cursor is not None
                cursor_advanced = self._repository.advance_vision_observation_cursor(
                    owner_id=session.owner_id,
                    session_id=session.id,
                    expected_previous_cursor=starting_cursor,
                    new_cursor=latest_cursor,
                )

            return ObservationIngestionResult(
                session_id=session.id,
                published_count=published,
                skipped_stale_epoch=skipped_stale_epoch,
                skipped_duplicate_sequence=skipped_duplicate_sequence,
                next_cursor=latest_cursor if cursor_advanced else starting_cursor,
                publish_failed=publish_failed,
                skipped_identity_mismatch=skipped_identity_mismatch,
                cursor_advanced=cursor_advanced,
            )
        finally:
            self._repository.release_vision_poll_lease(
                owner_id=session.owner_id, session_id=session.id, lease_token=lease_token
            )
