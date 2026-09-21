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
