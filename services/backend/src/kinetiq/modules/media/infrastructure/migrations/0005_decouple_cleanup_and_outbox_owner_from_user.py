import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Sever MediaCleanupJobRecord/MediaEventOutboxRecord from the user's FK.

    An account deletion must never cascade-destroy a durable cleanup job or
    outbox event still pointing at a real S3 object -- see the `owner_id`
    field comments in models.py. Both tables already store the owner as a
    plain UUID column named `owner_id` (Django's own default column name for
    a ForeignKey field literally named `owner`), so this is a pure
    constraint drop: step one removes the FK constraint via `AlterField`
    (Django computes and drops the real constraint name for us, on whatever
    backend is in use); step two only updates Django's own model state to
    know the field is now a plain `owner_id` UUIDField -- no further SQL
    runs, so the column, its data, and its index are untouched.
    """

    dependencies = [
        ("kinetiq_media", "0004_mediaeventoutboxrecord"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="mediacleanupjobrecord",
            name="owner",
            field=models.ForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="mediaeventoutboxrecord",
            name="owner",
            field=models.ForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveField(model_name="mediacleanupjobrecord", name="owner"),
                migrations.AddField(
                    model_name="mediacleanupjobrecord",
                    name="owner_id",
                    field=models.UUIDField(db_index=True),
                ),
                migrations.RemoveField(model_name="mediaeventoutboxrecord", name="owner"),
                migrations.AddField(
                    model_name="mediaeventoutboxrecord",
                    name="owner_id",
                    field=models.UUIDField(db_index=True),
                ),
            ],
        ),
    ]
