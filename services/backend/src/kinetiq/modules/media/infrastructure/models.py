from uuid import uuid4

from django.conf import settings
from django.db import models


class ProgressPhotoRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    session_id = models.UUIDField(null=True, blank=True, db_index=True)
    s3_key = models.CharField(max_length=512)
    content_type = models.CharField(max_length=100)
    byte_length = models.PositiveIntegerField()
    status = models.CharField(max_length=30, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # The most recently issued presigned PUT is usable until this instant;
    # deletion cleanup must not report itself final before it elapses.
    upload_authorized_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "media_progress_photos"
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="media_owner_created_idx"),
            models.Index(fields=["owner", "session_id"], name="media_owner_session_idx"),
            models.Index(fields=["owner", "status"], name="media_owner_status_idx"),
        ]


class MediaUploadReceiptRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    idempotency_key = models.CharField(max_length=128)
    request_fingerprint = models.CharField(max_length=128)
    photo = models.ForeignKey(ProgressPhotoRecord, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "media_upload_receipts"
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "idempotency_key"],
                name="media_owner_idempotency_unique",
            )
        ]


class MediaCleanupJobRecord(models.Model):
    """Outbox of pending storage removals (survives the photo's tombstone)."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # Plain UUID (no FK): the job must outlive any later purge of the photo row.
    photo_id = models.UUIDField(db_index=True)
    s3_key = models.CharField(max_length=512)
    reason = models.CharField(max_length=30)
    status = models.CharField(max_length=20)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=500, null=True, blank=True)
    next_attempt_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Set only for a PHOTO_DELETED job: the object must be (re-)confirmed
    # absent no earlier than this instant before the job may be marked DONE.
    verify_after = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "media_cleanup_jobs"
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="media_cleanup_due_idx"),
        ]
        constraints = [
            # At most one open job per object and reason.
            models.UniqueConstraint(
                fields=["photo_id", "reason"],
                condition=models.Q(status="PENDING"),
                name="media_cleanup_one_pending_per_photo_reason",
            )
        ]
