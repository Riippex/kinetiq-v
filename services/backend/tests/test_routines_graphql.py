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
from kinetiq.modules.goals.application import SetGoalCommand, SetGoalUseCase
from kinetiq.modules.goals.infrastructure.repositories import DjangoGoalRepository
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.profiles.application import (
    GetProfileUseCase,
    UpdateProfileCommand,
    UpdateProfileUseCase,
)
from kinetiq.modules.profiles.infrastructure.repositories import DjangoProfileRepository

PROPOSE_ROUTINE_MUTATION = """
mutation ProposeRoutine {
  proposeRoutine {
    routine {
      id
      version
      title
      rationale
      accepted
      items {
        order
        sets
        repetitions
        durationSeconds
        exercise {
          id
          name
          visionSupported
        }
      }
    }
    errors {
      code
      message
      field
    }
  }
}
"""

CURRENT_ROUTINE_QUERY = """
query CurrentRoutine {
  currentRoutine {
    id
    version
    title
    rationale
    accepted
    items {
      order
      sets
      repetitions
      exercise {
        id
        name
      }
    }
  }
}
"""

EDIT_ROUTINE_MUTATION = """
mutation EditRoutine($input: EditRoutineInput!) {
  editRoutine(input: $input) {
    routine {
      id
      version
      title
      rationale
      accepted
      items {
        order
        sets
        repetitions
        exercise {
          id
          name
        }
      }
    }
    errors {
      code
      message
      field
    }
  }
}
"""

ACCEPT_ROUTINE_MUTATION = """
mutation AcceptRoutine($routineId: ID!, $version: Int!) {
  acceptRoutine(routineId: $routineId, version: $version) {
    routine {
      id
      version
      title
      accepted
    }
    errors {
      code
      message
      field
    }
  }
}
"""

PREPARE_SESSION_MUTATION = """
mutation PrepareSession($input: PrepareSessionInput!) {
  prepareSession(input: $input) {
    session {
      id
      revision
      state
      routine {
        id
        version
        accepted
      }
    }
    errors {
      code
      message
      field
    }
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


@pytest.fixture
def athlete_user(catalog_seeded: DjangoCatalogRepository) -> User:
    user = User.objects.create_user(
        email=f"athlete-{uuid4()}@example.com",
        username=f"athlete-{uuid4()}",
    )
    # Initialize profile and goal
    GetProfileUseCase(DjangoProfileRepository()).execute(user.id)
    SetGoalUseCase(DjangoGoalRepository()).execute(
        user.id,
        SetGoalCommand(
            description="Build consistency with bodyweight routine",
            measure="weekly_completed_sessions",
            baseline=0.0,
            target=3.0,
            unit="sessions/week",
        ),
    )
    return user


@pytest.mark.django_db
def test_propose_routine_creates_unaccepted_draft(athlete_user: User) -> None:
    client = Client()
    client.force_login(athlete_user)

    response = client.post(
        "/graphql/",
        {"query": PROPOSE_ROUTINE_MUTATION},
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()["data"]["proposeRoutine"]
    assert data["errors"] == []
    routine = data["routine"]
    assert routine is not None
    assert routine["version"] == 1
    assert routine["title"] == "Full Body Foundation"
    assert routine["accepted"] is False
    assert len(routine["items"]) == 4
    assert "Full Body Foundation" in routine["rationale"]


@pytest.mark.django_db
def test_current_routine_query(athlete_user: User) -> None:
    client = Client()
    client.force_login(athlete_user)

    # 1. Before proposing, no routine exists
    res1 = client.post(
        "/graphql/",
        {"query": CURRENT_ROUTINE_QUERY},
        content_type="application/json",
    )
    assert res1.json()["data"]["currentRoutine"] is None

    # 2. Propose routine
    client.post(
        "/graphql/",
        {"query": PROPOSE_ROUTINE_MUTATION},
        content_type="application/json",
    )

    # 3. Query current routine returns the proposal
    res2 = client.post(
        "/graphql/",
        {"query": CURRENT_ROUTINE_QUERY},
        content_type="application/json",
    )
    current = res2.json()["data"]["currentRoutine"]
    assert current is not None
    assert current["version"] == 1
    assert current["accepted"] is False


@pytest.mark.django_db
def test_edit_routine_increments_version_and_validates_catalog(athlete_user: User) -> None:
    client = Client()
    client.force_login(athlete_user)

    # 1. Propose routine
    prop_res = client.post(
        "/graphql/",
        {"query": PROPOSE_ROUTINE_MUTATION},
        content_type="application/json",
    )
    routine_id = prop_res.json()["data"]["proposeRoutine"]["routine"]["id"]

    # 2. Edit routine with valid catalog exercises (squat + push-up with custom sets)
    edit_input = {
        "routineId": routine_id,
        "title": "Customized Upper-Lower Flow",
        "items": [
            {
                "exerciseId": "exercise-bodyweight-squat-v1",
                "order": 1,
                "sets": 4,
                "repetitions": 12,
            },
            {
                "exerciseId": "exercise-push-up-v1",
                "order": 2,
                "sets": 3,
                "repetitions": 10,
            },
        ],
    }
    edit_res = client.post(
        "/graphql/",
        {"query": EDIT_ROUTINE_MUTATION, "variables": {"input": edit_input}},
        content_type="application/json",
    )
    assert edit_res.status_code == 200
    edit_data = edit_res.json()["data"]["editRoutine"]
    assert edit_data["errors"] == []
    edited_routine = edit_data["routine"]
    assert edited_routine["version"] == 2
    assert edited_routine["title"] == "Customized Upper-Lower Flow"
    assert edited_routine["accepted"] is False
    assert len(edited_routine["items"]) == 2
    assert edited_routine["items"][0]["sets"] == 4
    assert edited_routine["items"][0]["repetitions"] == 12

    # 3. Attempting to edit with an exercise requiring equipment athlete lacks (pull-up)
    invalid_input = {
        "routineId": routine_id,
        "items": [
            {
                "exerciseId": "exercise-pull-up-v1",
                "order": 1,
                "sets": 3,
                "repetitions": 5,
            }
        ],
    }
    inv_res = client.post(
        "/graphql/",
        {"query": EDIT_ROUTINE_MUTATION, "variables": {"input": invalid_input}},
        content_type="application/json",
    )
    inv_data = inv_res.json()["data"]["editRoutine"]
    assert len(inv_data["errors"]) > 0
    assert inv_data["errors"][0]["code"] == "INVALID_ROUTINE_EDIT"


@pytest.mark.django_db
def test_accept_routine_and_session_preparation_enforcement(athlete_user: User) -> None:
    client = Client()
    client.force_login(athlete_user)

    # 1. Propose routine
    prop_res = client.post(
        "/graphql/",
        {"query": PROPOSE_ROUTINE_MUTATION},
        content_type="application/json",
    )
    routine_id = prop_res.json()["data"]["proposeRoutine"]["routine"]["id"]
    version = 1

    # 2. Attempt to prepare session with unaccepted routine version
    # -> MUST FAIL with ROUTINE_UNAVAILABLE
    prep_input = {
        "routineId": routine_id,
        "routineVersion": version,
        "mode": "NORMAL",
        "intensity": "PLANNED",
        "coachingTone": "CALM",
        "captureDeviceId": "phone-cam-1",
        "idempotencyKey": str(uuid4()),
    }
    fail_prep_res = client.post(
        "/graphql/",
        {"query": PREPARE_SESSION_MUTATION, "variables": {"input": prep_input}},
        content_type="application/json",
    )
    fail_data = fail_prep_res.json()["data"]["prepareSession"]
    assert fail_data["session"] is None
    assert fail_data["errors"][0]["code"] == "ROUTINE_UNAVAILABLE"

    # 3. Accept routine
    accept_res = client.post(
        "/graphql/",
        {
            "query": ACCEPT_ROUTINE_MUTATION,
            "variables": {"routineId": routine_id, "version": version},
        },
        content_type="application/json",
    )
    assert accept_res.status_code == 200
    accept_data = accept_res.json()["data"]["acceptRoutine"]
    assert accept_data["errors"] == []
    assert accept_data["routine"]["accepted"] is True

    # 4. Now prepare session with the accepted routine version -> MUST SUCCEED
    success_prep_res = client.post(
        "/graphql/",
        {"query": PREPARE_SESSION_MUTATION, "variables": {"input": prep_input}},
        content_type="application/json",
    )
    assert success_prep_res.status_code == 200
    success_data = success_prep_res.json()["data"]["prepareSession"]
    assert success_data["errors"] == []
    session = success_data["session"]
    assert session is not None
    assert session["routine"]["id"] == routine_id
    assert session["routine"]["version"] == version
    assert session["routine"]["accepted"] is True


@pytest.mark.django_db
def test_cross_user_isolation(athlete_user: User) -> None:
    client_a = Client()
    client_a.force_login(athlete_user)

    # Athlete A proposes routine
    prop_res = client_a.post(
        "/graphql/",
        {"query": PROPOSE_ROUTINE_MUTATION},
        content_type="application/json",
    )
    routine_id = prop_res.json()["data"]["proposeRoutine"]["routine"]["id"]

    # User B logs in
    user_b = User.objects.create_user(
        email=f"user-b-{uuid4()}@example.com",
        username=f"user-b-{uuid4()}",
    )
    GetProfileUseCase(DjangoProfileRepository()).execute(user_b.id)
    client_b = Client()
    client_b.force_login(user_b)

    # User B tries to accept User A's routine -> Rejected
    accept_res = client_b.post(
        "/graphql/",
        {"query": ACCEPT_ROUTINE_MUTATION, "variables": {"routineId": routine_id, "version": 1}},
        content_type="application/json",
    )
    accept_data = accept_res.json()["data"]["acceptRoutine"]
    assert accept_data["routine"] is None
    assert accept_data["errors"][0]["code"] == "ROUTINE_NOT_FOUND"

    # User B tries to edit User A's routine -> Rejected
    edit_res = client_b.post(
        "/graphql/",
        {
            "query": EDIT_ROUTINE_MUTATION,
            "variables": {
                "input": {
                    "routineId": routine_id,
                    "items": [
                        {
                            "exerciseId": "exercise-push-up-v1",
                            "order": 1,
                            "sets": 3,
                            "repetitions": 10,
                        }
                    ],
                }
            },
        },
        content_type="application/json",
    )
    edit_data = edit_res.json()["data"]["editRoutine"]
    assert edit_data["routine"] is None
    assert edit_data["errors"][0]["code"] == "ROUTINE_NOT_FOUND"


@pytest.mark.django_db
def test_propose_routine_returns_structured_error_when_limitation_unsupported(
    athlete_user: User,
) -> None:
    """Regression test: a self-reported limitation with no catalog adaptation
    must surface as a structured, client-usable GraphQL error rather than an
    unhandled exception or a silently accepted unsafe routine."""
    UpdateProfileUseCase(DjangoProfileRepository()).execute(
        owner_id=athlete_user.id,
        command=UpdateProfileCommand(limitations=("KNEE_PAIN",)),
    )

    client = Client()
    client.force_login(athlete_user)

    response = client.post(
        "/graphql/",
        {"query": PROPOSE_ROUTINE_MUTATION},
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()["data"]["proposeRoutine"]
    assert data["routine"] is None
    assert len(data["errors"]) == 1
    assert data["errors"][0]["code"] == "UNSUPPORTED_LIMITATION"
    assert "KNEE_PAIN" in data["errors"][0]["message"]


@pytest.mark.django_db
def test_edit_routine_rejects_excluded_exercise_with_structured_error(
    athlete_user: User,
) -> None:
    """Regression test: an excluded exercise must never enter an accepted
    routine through the edit mutation, surfaced as a structured GraphQL error."""
    client = Client()
    client.force_login(athlete_user)

    prop_res = client.post(
        "/graphql/",
        {"query": PROPOSE_ROUTINE_MUTATION},
        content_type="application/json",
    )
    routine_id = prop_res.json()["data"]["proposeRoutine"]["routine"]["id"]

    UpdateProfileUseCase(DjangoProfileRepository()).execute(
        owner_id=athlete_user.id,
        command=UpdateProfileCommand(exclusions=("exercise-push-up-v1",)),
    )

    edit_input = {
        "routineId": routine_id,
        "items": [
            {
                "exerciseId": "exercise-push-up-v1",
                "order": 1,
                "sets": 3,
                "repetitions": 8,
            }
        ],
    }
    edit_res = client.post(
        "/graphql/",
        {"query": EDIT_ROUTINE_MUTATION, "variables": {"input": edit_input}},
        content_type="application/json",
    )
    edit_data = edit_res.json()["data"]["editRoutine"]
    assert edit_data["routine"] is None
    assert edit_data["errors"][0]["code"] == "INVALID_ROUTINE_EDIT"
    assert "excluded" in edit_data["errors"][0]["message"]
