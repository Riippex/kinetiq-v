from uuid import uuid4

from django.conf import settings
from django.db import models

from kinetiq.modules.routines.infrastructure.models import RoutineRecord


class WorkoutSessionRecord(models.Model):
    id = models.UUIDField(primary_key=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    routine = models.ForeignKey(RoutineRecord, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    state = models.CharField(max_length=24)
    configuration = models.JSONField()
    confirmed_repetitions = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=("owner", "-updated_at"), name="session_owner_updated_idx")]


class IdempotencyReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    operation = models.CharField(max_length=80)
    key = models.CharField(max_length=160)
    request_fingerprint = models.CharField(max_length=64)
    session = models.OneToOneField(WorkoutSessionRecord, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "operation", "key"), name="idempotency_owner_operation_key_unique"
            )
        ]
