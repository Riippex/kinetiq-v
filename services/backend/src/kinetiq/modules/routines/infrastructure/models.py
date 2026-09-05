from uuid import uuid4

from django.conf import settings
from django.db import models


class RoutineRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    routine_id = models.UUIDField()
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    rationale = models.TextField(blank=True)
    prescription = models.JSONField(default=dict)
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("routine_id", "version"), name="routine_version_unique")
        ]
        indexes = [models.Index(fields=("owner", "accepted"), name="routine_owner_accept_idx")]
