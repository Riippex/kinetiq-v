from uuid import uuid4

import pytest
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord

PREPARE_DYNAMIC_SESSION = """
mutation PrepareDynamicSession($input: PrepareSessionInput!) {
  prepareSession(input: $input) {
    session { id revision state }
    errors { code message field }
  }
}
"""

START_SESSION = """
mutation StartSession($command: SessionCommandInput!) {
  startSession(command: $command) {
    session { id revision state }
    errors { code message field }
  }
}
"""

QUERY_DYNAMIC_CHALLENGES = """
query SessionDynamicChallenges($sessionId: ID!) {
  sessionDynamicChallenges(sessionId: $sessionId) {
    id
    challengeType
    exerciseId
    targetValue
    description
    setOrder
    status
  }
}
"""

SKIP_DYNAMIC_CHALLENGE = """
mutation SkipDynamicChallenge($input: SkipDynamicChallengeInput!) {
  skipDynamicChallenge(input: $input) {
    challenges {
      id
      challengeType
      exerciseId
      targetValue
      description
      setOrder
      status
    }
    errors { code message field }
  }
}
"""


@pytest.fixture
def athlete(db) -> User:
    return User.objects.create_user(username="athlete-dynamic")


@pytest.fixture
def other_athlete(db) -> User:
    return User.objects.create_user(username="other-athlete-dynamic")


@pytest.fixture
def accepted_routine(athlete: User) -> RoutineRecord:
    return RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="Dynamic Routine",
        rationale="Testing dynamic challenge flow.",
        prescription={
            "items": [
                {
                    "order": 1,
                    "exerciseId": "exercise-push-up-v1",
                    "exerciseVersion": 1,
                    "name": "Push Up",
                    "visionSupported": True,
                    "sets": 3,
                    "repetitions": 10,
                    "durationSeconds": None,
                },
                {
                    "order": 2,
                    "exerciseId": "exercise-squat-v1",
                    "exerciseVersion": 1,
                    "name": "Squat",
                    "visionSupported": True,
                    "sets": 3,
                    "repetitions": 12,
                    "durationSeconds": None,
                },
            ]
        },
        accepted=True,
    )


def test_session_dynamic_challenges_flow(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)

    prep_resp = client.post(
        "/graphql/",
        data={
            "query": PREPARE_DYNAMIC_SESSION,
            "variables": {
                "input": {
                    "routineId": str(accepted_routine.routine_id),
                    "routineVersion": 1,
                    "mode": "DYNAMIC",
                    "intensity": "PLANNED",
                    "coachingTone": "CALM",
                    "captureDeviceId": "phone-cam",
                    "idempotencyKey": "key-prep-dynamic-1",
                    "dynamic": {
                        "frequency": "STANDARD",
                        "allowedChallengeTypes": ["HOLD_POSE", "QUICK_REPS"],
                        "scoringEnabled": True,
                        "narrationEnabled": True,
                    },
                }
            },
        },
        content_type="application/json",
    )
    assert prep_resp.status_code == 200
    prep_data = prep_resp.json()["data"]["prepareSession"]
    assert prep_data["errors"] == []
    session_id = prep_data["session"]["id"]

    start_resp = client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "key-start-dynamic-1",
                }
            },
        },
        content_type="application/json",
    )
    assert start_resp.status_code == 200

    # Query dynamic challenges for the session
    query_resp = client.post(
        "/graphql/",
        data={
            "query": QUERY_DYNAMIC_CHALLENGES,
            "variables": {"sessionId": session_id},
        },
        content_type="application/json",
    )
    assert query_resp.status_code == 200
    challenges = query_resp.json()["data"]["sessionDynamicChallenges"]
    assert len(challenges) > 0
    for c in challenges:
        assert c["status"] == "PENDING"
        assert c["exerciseId"] in ("exercise-push-up-v1", "exercise-squat-v1")
        assert c["challengeType"] in ("HOLD_POSE", "QUICK_REPS")

    # Skip the first challenge
    first_challenge = challenges[0]
    skip_resp = client.post(
        "/graphql/",
        data={
            "query": SKIP_DYNAMIC_CHALLENGE,
            "variables": {
                "input": {
                    "sessionId": session_id,
                    "expectedRevision": 2,
                    "challengeId": first_challenge["id"],
                    "clientMutationId": "mut-skip-1",
                }
            },
        },
        content_type="application/json",
    )
    assert skip_resp.status_code == 200
    skip_data = skip_resp.json()["data"]["skipDynamicChallenge"]
    assert skip_data["errors"] == []
    updated_challenges = skip_data["challenges"]

    matching = next(c for c in updated_challenges if c["id"] == first_challenge["id"])
    assert matching["status"] == "SKIPPED"


def test_skip_dynamic_challenge_rejects_unknown_challenge_id(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)

    prep_resp = client.post(
        "/graphql/",
        data={
            "query": PREPARE_DYNAMIC_SESSION,
            "variables": {
                "input": {
                    "routineId": str(accepted_routine.routine_id),
                    "routineVersion": 1,
                    "mode": "DYNAMIC",
                    "intensity": "PLANNED",
                    "coachingTone": "CALM",
                    "captureDeviceId": "phone-cam",
                    "idempotencyKey": "key-prep-dynamic-unknown-1",
                    "dynamic": {
                        "frequency": "STANDARD",
                        "allowedChallengeTypes": ["HOLD_POSE", "QUICK_REPS"],
                        "scoringEnabled": True,
                        "narrationEnabled": True,
                    },
                }
            },
        },
        content_type="application/json",
    )
    assert prep_resp.status_code == 200
    prep_data = prep_resp.json()["data"]["prepareSession"]
    assert prep_data["errors"] == []
    session_id = prep_data["session"]["id"]

    start_resp = client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "key-start-dynamic-unknown-1",
                }
            },
        },
        content_type="application/json",
    )
    assert start_resp.status_code == 200

    skip_resp = client.post(
        "/graphql/",
        data={
            "query": SKIP_DYNAMIC_CHALLENGE,
            "variables": {
                "input": {
                    "sessionId": session_id,
                    "expectedRevision": 2,
                    "challengeId": str(uuid4()),
                    "clientMutationId": "mut-skip-unknown-1",
                }
            },
        },
        content_type="application/json",
    )
    assert skip_resp.status_code == 200
    skip_data = skip_resp.json()["data"]["skipDynamicChallenge"]
    assert skip_data["challenges"] == []
    assert skip_data["errors"][0]["code"] == "CHALLENGE_NOT_FOUND"


def test_session_dynamic_challenges_requires_auth(client: Client) -> None:
    resp = client.post(
        "/graphql/",
        data={
            "query": QUERY_DYNAMIC_CHALLENGES,
            "variables": {"sessionId": str(uuid4())},
        },
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert "errors" in resp.json()
    assert "AUTHENTICATION_REQUIRED" in resp.json()["errors"][0]["message"]
