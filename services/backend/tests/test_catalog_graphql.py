from uuid import uuid4

import pytest
from django.test import Client

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
from kinetiq.modules.identity.infrastructure.models import User

EXERCISES_QUERY = """
query Exercises {
  exercises {
    id
    name
    visionSupported
  }
}
"""


@pytest.fixture
def catalog_seeded() -> DjangoCatalogRepository:
    repo = DjangoCatalogRepository()
    vision = FileBasedVisionCapabilities()
    SeedCatalogUseCase(catalog_repo=repo, vision_capabilities=vision).execute(
        goals=CANONICAL_GOALS,
        exercises=CANONICAL_EXERCISES,
        templates=CANONICAL_TEMPLATES,
    )
    return repo


@pytest.mark.django_db
def test_exercises_query_requires_authentication(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    client = Client()
    response = client.post("/graphql/", {"query": EXERCISES_QUERY}, content_type="application/json")
    data = response.json()
    assert "errors" in data
    assert "AUTHENTICATION_REQUIRED" in data["errors"][0]["message"]


@pytest.mark.django_db
def test_exercises_query_returns_stable_catalog_ids(
    catalog_seeded: DjangoCatalogRepository,
) -> None:
    """Regression test: the client-facing catalog listing must expose the
    same stable exercise identifiers accepted by profile exclusions and
    routine items, not a display-only or regenerated ID."""
    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    client = Client()
    client.force_login(user)

    response = client.post("/graphql/", {"query": EXERCISES_QUERY}, content_type="application/json")
    assert response.status_code == 200
    exercises = response.json()["data"]["exercises"]

    assert len(exercises) == 5
    by_id = {ex["id"]: ex for ex in exercises}
    assert by_id["exercise-bodyweight-squat-v1"]["name"] == "Bodyweight Squat"
    assert by_id["exercise-bodyweight-squat-v1"]["visionSupported"] is True
    assert by_id["exercise-pull-up-v1"]["visionSupported"] is False
