from uuid import uuid4

from django.conf import settings
from django.db import models


class GoalRevisionRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    goal_id = models.UUIDField(db_index=True)
    revision = models.PositiveIntegerField()
    description = models.TextField()
    measure = models.CharField(max_length=80, null=True, blank=True)
    baseline = models.FloatField(null=True, blank=True)
    target = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=40, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "goals_goal_revisions"
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "goal_id", "revision"),
                name="goal_owner_id_revision_unique",
            )
        ]
        indexes = [
            models.Index(fields=("owner", "-revision"), name="goal_owner_rev_idx"),
            models.Index(fields=("owner", "-created_at"), name="goal_owner_created_idx"),
        ]
