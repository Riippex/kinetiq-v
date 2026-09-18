from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application import (
    ConfirmSessionTargetUseCase,
    StartSessionVisionAnalysisUseCase,
)
from kinetiq.modules.workouts.application.ports import (
    VisionAnalysisHandle,
    VisionCandidateInfo,
    VisionTargetConfirmation,
)
from kinetiq.modules.workouts.infrastructure.models import IdempotencyReceipt, WorkoutSessionRecord
from kinetiq.modules.workouts.infrastructure.repositories import (
    DjangoRoutineItemLookup,
    DjangoSessionLifecycleRepository,
)


class FakeVisionSessionAnalysisPort:
    """Deterministic Vision double for GraphQL wiring tests: any
    candidate_id passed to select_target is treated as detected, so these
    tests exercise the real ConfirmSessionTargetUseCase and real
    persistence without a live Vision service. Candidate-validation
    behavior itself (UnknownVisionCandidateError) is covered separately in
    tests/unit/test_confirm_session_target_use_case.py.
    """

    def __init__(self) -> None:
        self.created_analyses: list[UUID] = []

    def create_analysis(
        self, *, session_id: UUID, source_id: str, exercise_key: str,
        exercise_version: int, idempotency_key: str,
    ) -> VisionAnalysisHandle:
        self.created_analyses.append(session_id)
        return VisionAnalysisHandle(
            analysis_id=f"fake-analysis-{session_id}", epoch=1, state="AWAITING_SELECTION"
        )

    def list_candidates(self, *, analysis_id: str) -> tuple[VisionCandidateInfo, ...]:
        return (
            VisionCandidateInfo(candidate_id="person-target-alpha", confidence=0.95),
            VisionCandidateInfo(candidate_id="person-target-beta", confidence=0.9),
        )

    def select_target(
        self, *, analysis_id: str, candidate_id: str, expected_epoch: int, idempotency_key: str,
    ) -> VisionTargetConfirmation:
        return VisionTargetConfirmation(
            target_person_id=candidate_id, epoch=expected_epoch, state="TRACKING"
        )


def _fake_confirm_session_target() -> ConfirmSessionTargetUseCase:
    return ConfirmSessionTargetUseCase(
        DjangoSessionLifecycleRepository(),
        FakeVisionSessionAnalysisPort(),
    )


def _fake_start_session_vision_analysis() -> StartSessionVisionAnalysisUseCase:
    return StartSessionVisionAnalysisUseCase(
        DjangoSessionLifecycleRepository(),
        FakeVisionSessionAnalysisPort(),
        DjangoRoutineItemLookup(),
    )

PREPARE_SESSION = """
mutation PrepareSession($input: PrepareSessionInput!) {
  prepareSession(input: $input) {
    session {
      id
      revision
      state
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""

START_SESSION = """
mutation StartSession($command: SessionCommandInput!) {
  startSession(command: $command) {
    session {
      id
      revision
      state
      pauseReason
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""

PAUSE_SESSION = """
mutation PauseSession($command: SessionCommandInput!) {
  pauseSession(command: $command) {
    session {
      id
      revision
      state
      pauseReason
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""

RESUME_SESSION = """
mutation ResumeSession($command: SessionCommandInput!) {
  resumeSession(command: $command) {
    session {
      id
      revision
      state
      pauseReason
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""

START_SESSION_VISION_ANALYSIS = """
mutation StartSessionVisionAnalysis($command: SessionCommandInput!) {
  startSessionVisionAnalysis(command: $command) {
    session {
      id
      revision
      state
    }
    errors { code message field }
  }
}
"""

CONFIRM_SESSION_TARGET = """
mutation ConfirmSessionTarget($command: SessionCommandInput!, $targetPersonId: String!) {
  confirmSessionTarget(command: $command, targetPersonId: $targetPersonId) {
    session {
      id
      revision
      state
      targetPersonId
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""

DISABLE_DYNAMIC_MODE = """
mutation DisableDynamicMode($command: SessionCommandInput!) {
  disableDynamicMode(command: $command) {
    session {
      id
      revision
      state
      pauseReason
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""

FINISH_SESSION = """
mutation FinishSession($command: SessionCommandInput!) {
  finishSession(command: $command) {
    session {
      id
      revision
      state
      pauseReason
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""

ABANDON_SESSION = """
mutation AbandonSession($command: SessionCommandInput!) {
  abandonSession(command: $command) {
    session {
      id
      revision
      state
      pauseReason
      configuration {
        requestedMode
        activeMode
      }
    }
    errors { code message field }
  }
}
"""


@pytest.fixture
def athlete() -> User:
    return User.objects.create_user(username="athlete-lifecycle")


@pytest.fixture
def other_athlete() -> User:
    return User.objects.create_user(username="other-athlete")


@pytest.fixture
def accepted_routine(athlete: User) -> RoutineRecord:
    return RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="Full body test",
        rationale="Lifecycle test routine.",
        prescription={
            "items": [
                {
                    "order": 1,
                    "exerciseId": str(uuid4()),
                    "exerciseVersion": 1,
                    "name": "Squat",
                    "visionSupported": True,
                    "sets": 3,
                    "repetitions": 10,
                }
            ]
        },
        accepted=True,
    )


def prepare_test_session(
    client: Client, routine: RoutineRecord, *, key: str = "prep-key-1", mode: str = "DYNAMIC"
) -> dict:
    variables = {
        "input": {
            "routineId": str(routine.routine_id),
            "routineVersion": routine.version,
            "mode": mode,
            "intensity": "PLANNED",
            "coachingTone": "MOTIVATIONAL",
            "captureDeviceId": "camera-1",
            "idempotencyKey": key,
            "dynamic": {
                "frequency": "STANDARD",
                "allowedChallengeTypes": ["HOLD_POSE", "QUICK_REPS"],
                "scoringEnabled": True,
                "narrationEnabled": True,
            }
            if mode == "DYNAMIC"
            else None,
        }
    }
    response = client.post(
        "/graphql/",
        data={"query": PREPARE_SESSION, "variables": variables},
        content_type="application/json",
    ).json()
    return response["data"]["prepareSession"]["session"]


@pytest.mark.django_db
def test_full_session_lifecycle_with_revisions_and_pause_reason(
    athlete: User, accepted_routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(athlete)

    # 1. Prepare
    session = prepare_test_session(client, accepted_routine)
    session_id = session["id"]
    assert session["state"] == "READY"
    assert session["revision"] == 1
    assert session["configuration"]["requestedMode"] == "DYNAMIC"
    assert session["configuration"]["activeMode"] == "DYNAMIC"

    # 2. Start (revision 1 -> 2)
    start_resp = client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "start-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["startSession"]
    assert start_resp["errors"] == []
    assert start_resp["session"]["state"] == "ACTIVE"
    assert start_resp["session"]["revision"] == 2
    assert start_resp["session"]["pauseReason"] is None

    # 3. Pause (revision 2 -> 3)
    pause_resp = client.post(
        "/graphql/",
        data={
            "query": PAUSE_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 2,
                    "idempotencyKey": "pause-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["pauseSession"]
    assert pause_resp["errors"] == []
    assert pause_resp["session"]["state"] == "PAUSED"
    assert pause_resp["session"]["revision"] == 3
    assert pause_resp["session"]["pauseReason"] == "USER_REQUEST"

    # 4. Disable dynamic mode while paused (revision 3 -> 4)
    disable_resp = client.post(
        "/graphql/",
        data={
            "query": DISABLE_DYNAMIC_MODE,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 3,
                    "idempotencyKey": "disable-dynamic-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["disableDynamicMode"]
    assert disable_resp["errors"] == []
    assert disable_resp["session"]["revision"] == 4
    assert disable_resp["session"]["configuration"]["requestedMode"] == "DYNAMIC"
    assert disable_resp["session"]["configuration"]["activeMode"] == "NORMAL"
    assert disable_resp["session"]["state"] == "PAUSED"

    # 5. Resume (revision 4 -> 5)
    resume_resp = client.post(
        "/graphql/",
        data={
            "query": RESUME_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 4,
                    "idempotencyKey": "resume-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["resumeSession"]
    assert resume_resp["errors"] == []
    assert resume_resp["session"]["state"] == "ACTIVE"
    assert resume_resp["session"]["revision"] == 5
    assert resume_resp["session"]["pauseReason"] is None

    # 6. Finish (revision 5 -> 6)
    finish_resp = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 5,
                    "idempotencyKey": "finish-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["finishSession"]
    assert finish_resp["errors"] == []
    assert finish_resp["session"]["state"] == "COMPLETED"
    assert finish_resp["session"]["revision"] == 6

    # Verify DB record
    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.state == "COMPLETED"
    assert record.revision == 6
    assert record.pause_reason is None


@pytest.mark.django_db
def test_abandon_session_flows(athlete: User, accepted_routine: RoutineRecord) -> None:
    client = Client()
    client.force_login(athlete)

    # Abandon from READY
    s1 = prepare_test_session(client, accepted_routine, key="prep-abandon-1")
    abandon_1 = client.post(
        "/graphql/",
        data={
            "query": ABANDON_SESSION,
            "variables": {
                "command": {
                    "sessionId": s1["id"],
                    "expectedRevision": 1,
                    "idempotencyKey": "abandon-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["abandonSession"]
    assert abandon_1["errors"] == []
    assert abandon_1["session"]["state"] == "ABANDONED"
    assert abandon_1["session"]["revision"] == 2

    # Abandon from ACTIVE
    s2 = prepare_test_session(client, accepted_routine, key="prep-abandon-2")
    client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": s2["id"],
                    "expectedRevision": 1,
                    "idempotencyKey": "start-abandon-2",
                }
            },
        },
        content_type="application/json",
    )
    abandon_2 = client.post(
        "/graphql/",
        data={
            "query": ABANDON_SESSION,
            "variables": {
                "command": {
                    "sessionId": s2["id"],
                    "expectedRevision": 2,
                    "idempotencyKey": "abandon-2",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["abandonSession"]
    assert abandon_2["errors"] == []
    assert abandon_2["session"]["state"] == "ABANDONED"
    assert abandon_2["session"]["revision"] == 3


@pytest.mark.django_db
def test_revision_conflict_rejection(athlete: User, accepted_routine: RoutineRecord) -> None:
    client = Client()
    client.force_login(athlete)

    session = prepare_test_session(client, accepted_routine)
    session_id = session["id"]

    # Send command with wrong expectedRevision (e.g. 5 instead of 1)
    response = client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 5,
                    "idempotencyKey": "wrong-rev-key",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["startSession"]

    assert response["session"] is None
    assert response["errors"][0]["code"] == "REVISION_CONFLICT"
    assert response["errors"][0]["field"] == "expectedRevision"


@pytest.mark.django_db
def test_optimistic_concurrency_and_transaction_integrity(
    athlete: User, accepted_routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(athlete)

    session = prepare_test_session(client, accepted_routine)
    session_id = session["id"]

    # First transaction starts the session (revision 1 -> 2)
    first_start = client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "tx-key-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["startSession"]
    assert first_start["session"]["state"] == "ACTIVE"
    assert first_start["session"]["revision"] == 2

    # A concurrent client that also expected revision 1 now attempts an update with revision 1
    stale_update = client.post(
        "/graphql/",
        data={
            "query": PAUSE_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "tx-key-2",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["pauseSession"]

    assert stale_update["session"] is None
    assert stale_update["errors"][0]["code"] == "REVISION_CONFLICT"

    # Verify that session state was not corrupted
    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.state == "ACTIVE"
    assert record.revision == 2


@pytest.mark.django_db
def test_idempotent_command_retry_and_conflict(
    athlete: User, accepted_routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(athlete)

    session = prepare_test_session(client, accepted_routine)
    session_id = session["id"]

    cmd = {
        "sessionId": session_id,
        "expectedRevision": 1,
        "idempotencyKey": "idempotent-start-key",
    }

    # First call
    first = client.post(
        "/graphql/",
        data={"query": START_SESSION, "variables": {"command": cmd}},
        content_type="application/json",
    ).json()["data"]["startSession"]
    assert first["session"]["state"] == "ACTIVE"
    assert first["session"]["revision"] == 2

    # Retry exact same call with same idempotency key
    retry = client.post(
        "/graphql/",
        data={"query": START_SESSION, "variables": {"command": cmd}},
        content_type="application/json",
    ).json()["data"]["startSession"]
    assert retry["errors"] == []
    assert retry["session"]["id"] == first["session"]["id"]
    assert retry["session"]["revision"] == 2
    assert retry["session"]["state"] == "ACTIVE"

    # Only one receipt for this operation exists
    assert (
        IdempotencyReceipt.objects.filter(
            operation="workouts.start_session", key="idempotent-start-key"
        ).count()
        == 1
    )

    # Reusing the idempotency key with a DIFFERENT payload (different expected revision)
    conflict_cmd = {
        "sessionId": session_id,
        "expectedRevision": 99,
        "idempotencyKey": "idempotent-start-key",
    }
    conflict = client.post(
        "/graphql/",
        data={"query": START_SESSION, "variables": {"command": conflict_cmd}},
        content_type="application/json",
    ).json()["data"]["startSession"]

    assert conflict["session"] is None
    assert conflict["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict["errors"][0]["field"] == "idempotencyKey"


@pytest.mark.django_db
def test_invalid_state_transitions_rejected(
    athlete: User, accepted_routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(athlete)

    session = prepare_test_session(client, accepted_routine)
    session_id = session["id"]

    # Cannot pause a READY session
    resp = client.post(
        "/graphql/",
        data={
            "query": PAUSE_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "invalid-pause-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["pauseSession"]
    assert resp["session"] is None
    assert resp["errors"][0]["code"] == "INVALID_SESSION_STATE"

    # Cannot resume a READY session
    resp2 = client.post(
        "/graphql/",
        data={
            "query": RESUME_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "invalid-resume-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["resumeSession"]
    assert resp2["session"] is None
    assert resp2["errors"][0]["code"] == "INVALID_SESSION_STATE"

    # Cannot finish a READY session
    resp3 = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "invalid-finish-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["finishSession"]
    assert resp3["session"] is None
    assert resp3["errors"][0]["code"] == "INVALID_SESSION_STATE"


@pytest.mark.django_db
def test_cross_user_isolation(
    athlete: User, other_athlete: User, accepted_routine: RoutineRecord
) -> None:
    client_a = Client()
    client_a.force_login(athlete)

    session = prepare_test_session(client_a, accepted_routine)
    session_id = session["id"]

    # User B attempts to start User A's session
    client_b = Client()
    client_b.force_login(other_athlete)

    response = client_b.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "intruder-start",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["startSession"]

    assert response["session"] is None
    assert response["errors"][0]["code"] == "SESSION_NOT_FOUND"
    assert response["errors"][0]["field"] == "sessionId"


@pytest.mark.django_db
def test_unauthenticated_requests_rejected(accepted_routine: RoutineRecord) -> None:
    anonymous_client = Client()

    response = anonymous_client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": str(uuid4()),
                    "expectedRevision": 1,
                    "idempotencyKey": "anon-key",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["startSession"]

    assert response["session"] is None
    assert response["errors"][0]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.django_db
def test_invalid_uuid_rejected(athlete: User) -> None:
    client = Client()
    client.force_login(athlete)

    response = client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": "not-a-valid-uuid",
                    "expectedRevision": 1,
                    "idempotencyKey": "bad-uuid-key",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["startSession"]

    assert response["session"] is None
    assert response["errors"][0]["code"] == "INVALID_INPUT"
    assert response["errors"][0]["field"] == "sessionId"


@pytest.mark.django_db
@patch("kinetiq.interfaces.graphql.schema.confirm_session_target", _fake_confirm_session_target)
@patch(
    "kinetiq.interfaces.graphql.schema.start_session_vision_analysis",
    _fake_start_session_vision_analysis,
)
def test_confirm_session_target_lifecycle(athlete: User, accepted_routine: RoutineRecord) -> None:
    client = Client()
    client.force_login(athlete)

    session = prepare_test_session(client, accepted_routine, key="prep-confirm-target")
    session_id = session["id"]
    assert session["revision"] == 1

    # Confirming before a Vision analysis has been started is rejected.
    premature_resp = client.post(
        "/graphql/",
        data={
            "query": CONFIRM_SESSION_TARGET,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "confirm-too-early",
                },
                "targetPersonId": "person-target-alpha",
            },
        },
        content_type="application/json",
    ).json()["data"]["confirmSessionTarget"]
    assert premature_resp["session"] is None
    assert premature_resp["errors"][0]["code"] == "VISION_ANALYSIS_NOT_STARTED"

    # Start the Vision analysis first -- the split enrollment lifecycle's
    # first step (revision 1 -> 2).
    start_analysis_resp = client.post(
        "/graphql/",
        data={
            "query": START_SESSION_VISION_ANALYSIS,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "start-analysis-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["startSessionVisionAnalysis"]
    assert start_analysis_resp["errors"] == []
    assert start_analysis_resp["session"]["revision"] == 2

    # Confirm target now that an analysis exists (revision 2 -> 3)
    response = client.post(
        "/graphql/",
        data={
            "query": CONFIRM_SESSION_TARGET,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 2,
                    "idempotencyKey": "confirm-target-1",
                },
                "targetPersonId": "person-target-alpha",
            },
        },
        content_type="application/json",
    ).json()["data"]["confirmSessionTarget"]

    assert response["errors"] == []
    assert response["session"]["id"] == session_id
    assert response["session"]["revision"] == 3
    assert response["session"]["targetPersonId"] == "person-target-alpha"

    # Verify session query also returns targetPersonId
    session_query = """
    query GetSession($id: ID!) {
      session(id: $id) {
        id
        revision
        targetPersonId
      }
    }
    """
    query_resp = client.post(
        "/graphql/",
        data={"query": session_query, "variables": {"id": session_id}},
        content_type="application/json",
    ).json()["data"]["session"]
    assert query_resp["targetPersonId"] == "person-target-alpha"

    # Idempotent re-execution returns identical result
    idempotent_resp = client.post(
        "/graphql/",
        data={
            "query": CONFIRM_SESSION_TARGET,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 2,
                    "idempotencyKey": "confirm-target-1",
                },
                "targetPersonId": "person-target-alpha",
            },
        },
        content_type="application/json",
    ).json()["data"]["confirmSessionTarget"]

    assert idempotent_resp["errors"] == []
    assert idempotent_resp["session"]["revision"] == 3
    assert idempotent_resp["session"]["targetPersonId"] == "person-target-alpha"

    # Revision conflict with stale expectedRevision
    conflict_resp = client.post(
        "/graphql/",
        data={
            "query": CONFIRM_SESSION_TARGET,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 2,
                    "idempotencyKey": "confirm-target-2",
                },
                "targetPersonId": "person-target-beta",
            },
        },
        content_type="application/json",
    ).json()["data"]["confirmSessionTarget"]

    assert conflict_resp["session"] is None
    assert conflict_resp["errors"][0]["code"] == "REVISION_CONFLICT"
