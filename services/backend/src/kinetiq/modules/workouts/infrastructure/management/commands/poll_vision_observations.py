import logging

from django.core.management.base import BaseCommand

from kinetiq.bootstrap.container import poll_vision_observations
from kinetiq.modules.integrations.vision_adapter import VisionAdapterError
from kinetiq.modules.workouts.infrastructure.repositories import (
    DjangoRoutineItemLookup,
    DjangoSessionLifecycleRepository,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Runs one pass of Vision observation ingestion across every session
    currently eligible for it (active/paused, Vision analysis started,
    target confirmed), publishing validated TransientSessionUpdates and
    advancing each session's observation cursor.

    This is the "worker" side of KV-403's real observation-ingestion path:
    the actual polling/validation/fan-out logic lives in
    PollVisionObservationsUseCase (unit-tested in isolation); this command
    is a thin entrypoint meant to be invoked repeatedly by external
    scheduling infrastructure (a cron entry, a Kubernetes CronJob, a
    supervisor loop) at whatever interval matches the desired observation
    latency -- no scheduler is bundled in this repository.

    A single session's Vision failure (e.g. VisionAdapterError from a
    transient network issue) is logged and skipped rather than aborting
    the whole pass, so one unhealthy analysis cannot starve every other
    session's updates.
    """

    help = (
        "Polls Vision for new observations across all eligible sessions "
        "and publishes transient updates."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum observations to fetch per session per pass.",
        )

    def handle(self, *args, **options) -> None:
        limit = options["limit"]
        repository = DjangoSessionLifecycleRepository()
        routine_items = DjangoRoutineItemLookup()
        use_case = poll_vision_observations()

        sessions = repository.list_sessions_polling_vision()
        total_published = 0
        for session in sessions:
            try:
                items = routine_items.get_accepted_routine_items(
                    owner_id=session.owner_id,
                    routine_id=session.routine_id,
                    version=session.routine_version,
                )
                active_exercise_id = items[0].exercise_id if items else None

                result = use_case.execute(
                    session=session, active_exercise_id=active_exercise_id, limit=limit
                )
                total_published += result.published_count
                if result.lease_contended:
                    logger.info(
                        "vision_observation_poll_lease_contended",
                        extra={"session_id": str(session.id)},
                    )
                elif (
                    result.published_count
                    or result.skipped_stale_epoch
                    or result.skipped_duplicate_sequence
                    or result.publish_failed
                    or not result.cursor_advanced
                ):
                    logger.info(
                        "vision_observations_polled",
                        extra={
                            "session_id": str(session.id),
                            "published_count": result.published_count,
                            "skipped_stale_epoch": result.skipped_stale_epoch,
                            "skipped_duplicate_sequence": result.skipped_duplicate_sequence,
                            "next_cursor": result.next_cursor,
                            "publish_failed": result.publish_failed,
                            "cursor_advanced": result.cursor_advanced,
                        },
                    )
            except VisionAdapterError:
                logger.exception(
                    "vision_observation_poll_failed", extra={"session_id": str(session.id)}
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Polled {len(sessions)} session(s), published {total_published} update(s)."
            )
        )
