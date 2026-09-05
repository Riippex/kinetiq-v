from uuid import uuid4

import pytest
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord

PREPARE_SESSION = """
mutation PrepareSession($input: PrepareSessionInput!) {
  prepareSession(input: $input) {
    session {
      id
      revision
      state
      routine {
        id version title accepted
        items {
          order sets repetitions durationSeconds
          exercise { id version name visionSupported }
        }
      }
      configuration {
        requestedMode
        activeMode
        intensity
        coachingTone
        promptForProgressPhoto
        dynamic { frequency allowedChallengeTypes scoringEnabled narrationEnabled }
      }
    }
    errors { code message field }
  }
}
"""


def session_input(routine: RoutineRecord, *, key: str = "prepare-1", mode: str = "DYNAMIC") -> dict:
    value = {
        "routineId": str(routine.routine_id),
        "routineVersion": routine.version,
        "mode": mode,
        "intensity": "PLANNED",
        "coachingTone": "MOTIVATIONAL",
        "captureDeviceId": "galaxy-s26-ultra-camera",
        "displayDeviceId": "living-room-fire-tv",
        "promptForProgressPhoto": True,
        "idempotencyKey": key,
    }
    if mode == "DYNAMIC":
        value["dynamic"] = {
            "frequency": "STANDARD",
            "allowedChallengeTypes": ["HOLD_POSE", "QUICK_REPS"],
            "scoringEnabled": True,
            "narrationEnabled": True,
        }
    return value


@pytest.fixture
def owner() -> User:
    return User.objects.create_user(username="athlete")


@pytest.fixture
def routine(owner: User) -> RoutineRecord:
    return RoutineRecord.objects.create(
        owner=owner,
        routine_id=uuid4(),
        version=2,
        title="Full body foundation",
        rationale="A balanced starting point.",
        prescription={
            "items": [
                {
                    "order": 1,
                    "exerciseId": str(uuid4()),
                    "exerciseVersion": 3,
                    "name": "Bodyweight squat",
                    "visionSupported": True,
                    "sets": 3,
                    "repetitions": 10,
                }
            ]
        },
        accepted=True,
    )


@pytest.mark.django_db
def test_authenticated_owner_prepares_dynamic_session_idempotently(
    owner: User, routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(owner)
    variables = {"input": session_input(routine)}

    first = client.post(
        "/graphql/",
        data={"query": PREPARE_SESSION, "variables": variables},
        content_type="application/json",
    ).json()
    second = client.post(
        "/graphql/",
        data={"query": PREPARE_SESSION, "variables": variables},
        content_type="application/json",
    ).json()

    first_payload = first["data"]["prepareSession"]
    second_payload = second["data"]["prepareSession"]
    assert first_payload["errors"] == []
    assert first_payload["session"]["state"] == "READY"
    assert first_payload["session"]["routine"]["version"] == 2
    exercise = first_payload["session"]["routine"]["items"][0]["exercise"]
    assert exercise["name"] == "Bodyweight squat"
    assert exercise["version"] == 3
    assert exercise["visionSupported"] is True
    assert first_payload["session"]["configuration"]["requestedMode"] == "DYNAMIC"
    assert second_payload["session"]["id"] == first_payload["session"]["id"]
    assert WorkoutSessionRecord.objects.count() == 1


@pytest.mark.django_db
def test_reusing_idempotency_key_with_different_command_is_rejected(
    owner: User, routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(owner)
    client.post(
        "/graphql/",
        data={"query": PREPARE_SESSION, "variables": {"input": session_input(routine)}},
        content_type="application/json",
    )

    response = client.post(
        "/graphql/",
        data={
            "query": PREPARE_SESSION,
            "variables": {"input": session_input(routine, mode="NORMAL")},
        },
        content_type="application/json",
    ).json()

    payload = response["data"]["prepareSession"]
    assert payload["session"] is None
    assert payload["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.django_db
def test_anonymous_user_cannot_prepare_session(routine: RoutineRecord) -> None:
    response = (
        Client()
        .post(
            "/graphql/",
            data={"query": PREPARE_SESSION, "variables": {"input": session_input(routine)}},
            content_type="application/json",
        )
        .json()
    )

    payload = response["data"]["prepareSession"]
    assert payload["session"] is None
    assert payload["errors"][0]["code"] == "AUTHENTICATION_REQUIRED"
