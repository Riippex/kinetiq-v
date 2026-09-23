"""Account-deletion safety net for private media.

`MediaCleanupJobRecord`/`MediaEventOutboxRecord` no longer cascade when the
owning user is deleted (see `models.py`), so an S3 object already mid-cleanup
survives. But a photo that is still CONFIRMED/PENDING_UPLOAD at the moment
the account is deleted has no cleanup job yet at all -- without this hook,
Django's own CASCADE would simply drop its `ProgressPhotoRecord` row and the
real S3 object it points to would become permanently unreachable orphan
storage, with nothing left in the database to ever clean it up.

This receiver closes that gap for every deletion path, including a bare
`User.delete()` from the admin or a shell, not just a future user-facing
"delete my account" flow -- no such flow exists yet in this codebase (see
pass-7 Codex adversarial review), so a signal is the only mechanism that
covers every current and future way a `User` row can be removed.

It is intentionally data-only: it tombstones each live photo and durably
enqueues its cleanup job in the same request/transaction, but never calls
`MediaCleanupService.attempt()` (which would perform a real S3 delete).
`pre_delete` fires before the surrounding transaction commits, so acting on
storage here could delete a real object for an account deletion that later
rolls back. The actual S3 removal is left to `process_media_cleanup`, which
only ever runs after the deletion has durably committed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from kinetiq.modules.media.domain.entities import ProgressPhotoStatus
from kinetiq.modules.media.infrastructure.models import ProgressPhotoRecord
from kinetiq.modules.media.infrastructure.repositories import DjangoProgressPhotoRepository


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def tombstone_media_before_account_deletion(sender: Any, instance: Any, **kwargs: Any) -> None:
    repo = DjangoProgressPhotoRepository()
    now = datetime.now(UTC)
    photo_ids = list(
        ProgressPhotoRecord.objects.filter(owner_id=instance.id)
        .exclude(status=ProgressPhotoStatus.DELETED.value)
        .values_list("id", flat=True)
    )
    for photo_id in photo_ids:
        repo.tombstone_and_enqueue_cleanup(photo_id=photo_id, owner_id=instance.id, deleted_at=now)
