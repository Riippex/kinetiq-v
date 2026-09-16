# Generated manually for KV-301 session lifecycle and idempotency

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kinetiq_workouts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="workoutsessionrecord",
            name="pause_reason",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
        migrations.AlterField(
            model_name="idempotencyreceipt",
            name="session",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="idempotency_receipts",
                to="kinetiq_workouts.workoutsessionrecord",
            ),
        ),
    ]
