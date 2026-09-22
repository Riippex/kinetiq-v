from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from kinetiq.bootstrap.container import get_media_cleanup_repository, process_media_cleanup


class Command(BaseCommand):
    help = (
        "Retry pending private-media storage cleanups (deleted photos and rejected "
        "uploads). Run periodically, e.g. every minute, from a scheduler or worker."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=50, help="Maximum jobs per run.")

    def handle(self, *args: Any, **options: Any) -> None:
        summary = process_media_cleanup().process_due(limit=options["limit"])
        counts = get_media_cleanup_repository().counts_by_status()
        pending = counts.get("PENDING", 0)
        dead = counts.get("DEAD_LETTER", 0)
        self.stdout.write(
            f"claimed={summary.claimed} completed={summary.completed} "
            f"retried={summary.retried} dead_lettered={summary.dead_lettered} "
            f"pending={pending} dead_letter_total={dead}"
        )
        if dead:
            # Surface unremovable private photos instead of leaving them silent.
            raise CommandError(
                f"{dead} media cleanup job(s) are dead-lettered and need operator attention"
            )
