from io import StringIO

import pytest
from django.core.management import call_command

from kinetiq.modules.catalog.infrastructure.models import (
    ExerciseRecord,
    GoalDefinitionRecord,
    RoutineTemplateRecord,
)


@pytest.mark.django_db
def test_seed_catalog_command_is_idempotent() -> None:
    first_output = StringIO()
    call_command("seed_catalog", stdout=first_output)

    assert GoalDefinitionRecord.objects.count() == 1
    assert ExerciseRecord.objects.count() == 5
    assert RoutineTemplateRecord.objects.count() == 1
    assert "Canonical catalog ready: goals=1 exercises=5 templates=1." in first_output.getvalue()

    second_output = StringIO()
    call_command("seed_catalog", stdout=second_output)

    assert GoalDefinitionRecord.objects.count() == 1
    assert ExerciseRecord.objects.count() == 5
    assert RoutineTemplateRecord.objects.count() == 1
    assert "Canonical catalog ready: goals=1 exercises=5 templates=1." in second_output.getvalue()
