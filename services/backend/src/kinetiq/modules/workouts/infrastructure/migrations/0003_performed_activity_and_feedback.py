# Generated manually for KV-302 performed activity and feedback

import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kinetiq_workouts", "0002_session_lifecycle_and_idempotency"),
    ]

    operations = [
        migrations.CreateModel(
            name="PerformedSetRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("exercise_id", models.CharField(max_length=120)),
                ("set_order", models.PositiveIntegerField()),
                ("repetitions", models.PositiveIntegerField(blank=True, null=True)),
                ("duration_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="performed_sets",
                        to="kinetiq_workouts.workoutsessionrecord",
                    ),
                ),
            ],
            options={
                "ordering": ["set_order", "created_at"],
            },
        ),
        migrations.CreateModel(
            name="ObservationCoverageRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("coverage_ratio", models.FloatField()),
                ("tracked_seconds", models.PositiveIntegerField()),
                ("total_seconds", models.PositiveIntegerField()),
                ("fully_visible_ratio", models.FloatField(default=1.0)),
                ("untracked_reasons", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "session",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="observation_coverage",
                        to="kinetiq_workouts.workoutsessionrecord",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="SessionFeedbackRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("perceived_effort", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("comments", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "session",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedback",
                        to="kinetiq_workouts.workoutsessionrecord",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="performedsetrecord",
            constraint=models.UniqueConstraint(
                fields=("session", "exercise_id", "set_order"),
                name="performed_set_session_exercise_order_unique",
            ),
        ),
    ]
