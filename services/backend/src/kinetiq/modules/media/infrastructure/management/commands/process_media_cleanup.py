from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from kinetiq.bootstrap.container import (
    get_media_cleanup_repository,
    get_media_event_outbox_repository,
    process_media_cleanup,
    process_media_event_outbox,
    reconcile_abandoned_uploads,
)


class Command(BaseCommand):
    help = (
        "Retry pending private-media storage cleanups (deleted photos and rejected "
        "uploads), reconcile PENDING_UPLOAD photos whose presigned upload URL expired "
        "without ever being finalized, and retry delivery of durably outboxed "
        "ProgressPhotoDeleted.v1 events. Run periodically, e.g. every minute, from a "
        "scheduler or worker."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=50, help="Maximum cleanup jobs per run.")
        parser.add_argument(
            "--reconcile-limit",
            type=int,
            default=100,
            help="Maximum abandoned PENDING_UPLOAD photos to reconcile per run.",
        )
        parser.add_argument(
            "--event-limit",
            type=int,
            default=50,
            help="Maximum outboxed events to attempt delivery of per run.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Reconcile first: an abandoned upload becomes a normal PHOTO_DELETED
        # cleanup job, so the retry pass below can also drive it to DONE.
        reconciliation = reconcile_abandoned_uploads().execute(limit=options["reconcile_limit"])

        summary = process_media_cleanup().process_due(limit=options["limit"])
        counts = get_media_cleanup_repository().counts_by_status()
        pending = counts.get("PENDING", 0)
        dead = counts.get("DEAD_LETTER", 0)

        # Independent of cleanup-job completion above: an event enqueued by a
        # previous run (or another worker) is retried here regardless of
        # whether this run itself completed any new jobs.
        event_summary = process_media_event_outbox().process_due(limit=options["event_limit"])
        event_counts = get_media_event_outbox_repository().counts_by_status()
        event_pending = event_counts.get("PENDING", 0)
        event_dead = event_counts.get("DEAD_LETTER", 0)

        self.stdout.write(
            f"reconciled={reconciliation.reconciled} "
            f"claimed={summary.claimed} completed={summary.completed} "
            f"retried={summary.retried} dead_lettered={summary.dead_lettered} "
            f"pending={pending} dead_letter_total={dead} "
            f"events_claimed={event_summary.claimed} "
            f"events_completed={event_summary.completed} "
            f"events_retried={event_summary.retried} "
            f"events_dead_lettered={event_summary.dead_lettered} "
            f"events_pending={event_pending} events_dead_letter_total={event_dead}"
        )
        if dead or event_dead:
            # Surface unremovable private photos / undelivered events instead
            # of leaving them silent.
            raise CommandError(
                f"{dead} media cleanup job(s) and {event_dead} media event(s) are "
                "dead-lettered and need operator attention"
            )
