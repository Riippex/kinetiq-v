from django.conf import settings
from django.db import models


class UserProfileRecord(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="profile",
    )
    display_name = models.CharField(max_length=120)
    timezone = models.CharField(max_length=64, default="UTC")
    experience_level = models.CharField(max_length=32, default="RETURNING")
    availability_days_per_week = models.PositiveSmallIntegerField(default=3)
    target_session_minutes = models.PositiveSmallIntegerField(default=15)
    available_equipment = models.JSONField(default=list)
    workout_space = models.CharField(max_length=64, default="LIVING_ROOM")
    preferences = models.JSONField(default=list)
    exclusions = models.JSONField(default=list)
    limitations = models.JSONField(default=list)
    coaching_tone = models.CharField(max_length=32, default="CALM")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "profiles_user_profile"
