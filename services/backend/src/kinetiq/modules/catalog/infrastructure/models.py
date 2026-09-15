from uuid import uuid4

from django.db import models


class GoalDefinitionRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    code = models.CharField(max_length=80, unique=True)
    revision = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=160)
    description = models.TextField()
    measure = models.CharField(max_length=80)
    baseline = models.FloatField(default=0.0)
    target = models.FloatField()
    unit = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_goal_definitions"
        indexes = [models.Index(fields=["code"], name="catalog_goal_code_idx")]


class ExerciseRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    code = models.CharField(max_length=80, unique=True)
    version = models.PositiveIntegerField(default=1)
    slug = models.CharField(max_length=80, db_index=True)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=40)
    equipment = models.CharField(max_length=40)
    prescription_type = models.CharField(max_length=24)
    default_prescription = models.JSONField(default=dict)
    vision_supported = models.BooleanField(default=False)
    vision_exercise_key = models.CharField(max_length=80, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_exercises"
        indexes = [
            models.Index(fields=["equipment", "vision_supported"], name="catalog_ex_eq_vis_idx"),
            models.Index(fields=["code", "version"], name="catalog_ex_code_ver_idx"),
        ]


class RoutineTemplateRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    code = models.CharField(max_length=80, unique=True)
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    target_goal_code = models.CharField(max_length=80)
    estimated_duration_minutes = models.PositiveIntegerField()
    items = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_routine_templates"
        indexes = [
            models.Index(fields=["target_goal_code"], name="catalog_tmpl_goal_idx"),
        ]
