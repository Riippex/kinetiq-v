from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from kinetiq.modules.catalog.application.seed_catalog import SeedCatalogUseCase
from kinetiq.modules.catalog.infrastructure.canonical_data import (
    CANONICAL_EXERCISES,
    CANONICAL_GOALS,
    CANONICAL_TEMPLATES,
)
from kinetiq.modules.catalog.infrastructure.repositories import DjangoCatalogRepository
from kinetiq.modules.catalog.infrastructure.vision_contract_adapter import (
    FileBasedVisionCapabilities,
)


class Command(BaseCommand):
    help = "Create or update the canonical goals, exercises, and routine templates."

    def handle(self, *args: Any, **options: Any) -> None:
        use_case = SeedCatalogUseCase(
            catalog_repo=DjangoCatalogRepository(),
            vision_capabilities=FileBasedVisionCapabilities(),
        )

        with transaction.atomic():
            result = use_case.execute(
                goals=CANONICAL_GOALS,
                exercises=CANONICAL_EXERCISES,
                templates=CANONICAL_TEMPLATES,
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Canonical catalog ready: "
                f"goals={result.goals_seeded} "
                f"exercises={result.exercises_seeded} "
                f"templates={result.templates_seeded}."
            )
        )
