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
    pause_reason = models.CharField(max_length=32, null=True, blank=True)
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
    session = models.ForeignKey(
        WorkoutSessionRecord,
        on_delete=models.CASCADE,
        related_name="idempotency_receipts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "operation", "key"), name="idempotency_owner_operation_key_unique"
            )
        ]


class PerformedSetRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    session = models.ForeignKey(
        WorkoutSessionRecord,
        on_delete=models.CASCADE,
        related_name="performed_sets",
    )
    exercise_id = models.CharField(max_length=120)
    set_order = models.PositiveIntegerField()
    repetitions = models.PositiveIntegerField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("session", "exercise_id", "set_order"),
                name="performed_set_session_exercise_order_unique",
            )
        ]
        ordering = ["set_order", "created_at"]


class ObservationCoverageRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    session = models.OneToOneField(
        WorkoutSessionRecord,
        on_delete=models.CASCADE,
        related_name="observation_coverage",
    )
    coverage_ratio = models.FloatField()
    tracked_seconds = models.PositiveIntegerField()
    total_seconds = models.PositiveIntegerField()
    fully_visible_ratio = models.FloatField(default=1.0)
    untracked_reasons = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class SessionFeedbackRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    session = models.OneToOneField(
        WorkoutSessionRecord,
        on_delete=models.CASCADE,
        related_name="feedback",
    )
    perceived_effort = models.PositiveSmallIntegerField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

