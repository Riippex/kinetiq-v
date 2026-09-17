from uuid import uuid4

import pytest
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import (
    ObservationCoverageRecord,
    PerformedSetRecord,
    SessionFeedbackRecord,
    WorkoutSessionRecord,
)

PREPARE_SESSION = """
mutation PrepareSession($input: PrepareSessionInput!) {
  prepareSession(input: $input) {
    session {
      id
      revision
      state
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
    }
    errors { code message field }
  }
}
"""

FINISH_SESSION = """
mutation FinishSession(
  $command: SessionCommandInput!
  $performedSets: [PerformedSetInput!]
  $observationCoverage: ObservationCoverageInput
  $feedback: SessionFeedbackInput
) {
  finishSession(
    command: $command
    performedSets: $performedSets
    observationCoverage: $observationCoverage
    feedback: $feedback
  ) {
    session {
      id
      revision
      state
      confirmedRepetitions
      performedSets {
        exerciseId
        setOrder
        repetitions
        durationSeconds
      }
      observationCoverage {
        coverageRatio
        trackedSeconds
        totalSeconds
        fullyVisibleRatio
        untrackedReasons
      }
      feedback {
        perceivedEffort
        comments
      }
    }
    errors { code message field }
  }
}
"""

RECORD_FEEDBACK = """
mutation RecordSessionFeedback(
  $command: SessionCommandInput!
  $feedback: SessionFeedbackInput!
) {
  recordSessionFeedback(
    command: $command
    feedback: $feedback
  ) {
    session {
      id
      revision
      state
      confirmedRepetitions
      feedback {
        perceivedEffort
        comments
      }
    }
    errors { code message field }
  }
}
"""

QUERY_SESSION = """
query GetSession($id: ID!) {
  session(id: $id) {
    id
    revision
    state
    confirmedRepetitions
    performedSets {
      exerciseId
      setOrder
      repetitions
      durationSeconds
    }
    observationCoverage {
      coverageRatio
      trackedSeconds
      totalSeconds
    }
    feedback {
      perceivedEffort
      comments
    }
  }
}
"""


@pytest.fixture
def athlete() -> User:
    return User.objects.create_user(username="athlete-activity")


@pytest.fixture
def other_athlete() -> User:
    return User.objects.create_user(username="other-athlete-activity")


@pytest.fixture
def accepted_routine(athlete: User) -> RoutineRecord:
    return RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="Activity Routine",
        rationale="Testing activity persistence.",
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
                    "exerciseId": "exercise-plank-v1",
                    "exerciseVersion": 1,
                    "name": "Plank",
                    "visionSupported": True,
                    "sets": 1,
                    "repetitions": None,
                    "durationSeconds": 45,
                },
            ]
        },
        accepted=True,
    )


def prepare_and_start_session(client: Client, routine: RoutineRecord) -> dict:
    prep_resp = client.post(
        "/graphql/",
        data={
            "query": PREPARE_SESSION,
            "variables": {
                "input": {
                    "routineId": str(routine.routine_id),
                    "routineVersion": routine.version,
                    "mode": "NORMAL",
                    "intensity": "PLANNED",
                    "coachingTone": "CALM",
                    "captureDeviceId": "phone-cam",
                    "idempotencyKey": f"prep-{uuid4()}",
                }
            },
        },
        content_type="application/json",
    ).json()
    session_data = prep_resp["data"]["prepareSession"]["session"]
    session_id = session_data["id"]

    start_resp = client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": f"start-{uuid4()}",
                }
            },
        },
        content_type="application/json",
    ).json()
    return start_resp["data"]["startSession"]["session"]


@pytest.mark.django_db
def test_finish_session_persists_performed_sets_coverage_and_feedback(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    performed_sets = [
        {"exerciseId": "exercise-push-up-v1", "setOrder": 1, "repetitions": 10},
        {"exerciseId": "exercise-push-up-v1", "setOrder": 2, "repetitions": 12},
        {"exerciseId": "exercise-plank-v1", "setOrder": 1, "durationSeconds": 45},
    ]
    observation_coverage = {
        "coverageRatio": 0.94,
        "trackedSeconds": 140,
        "totalSeconds": 150,
        "fullyVisibleRatio": 0.90,
        "untrackedReasons": ["CAMERA_OCCLUDED"],
    }
    feedback = {"perceivedEffort": 8, "comments": "Tough last set"}

    finish_resp = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-key-1",
                },
                "performedSets": performed_sets,
                "observationCoverage": observation_coverage,
                "feedback": feedback,
            },
        },
        content_type="application/json",
    ).json()

    data = finish_resp["data"]["finishSession"]
    assert data["errors"] == []
    finished_session = data["session"]
    assert finished_session["state"] == "COMPLETED"
    assert finished_session["revision"] == 3
    assert finished_session["confirmedRepetitions"] == 22
    assert len(finished_session["performedSets"]) == 3
    assert finished_session["observationCoverage"]["coverageRatio"] == 0.94
    assert finished_session["observationCoverage"]["untrackedReasons"] == ["CAMERA_OCCLUDED"]
    assert finished_session["feedback"]["perceivedEffort"] == 8
    assert finished_session["feedback"]["comments"] == "Tough last set"

    # Verify DB persistence
    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.state == "COMPLETED"
    assert record.confirmed_repetitions == 22
    assert PerformedSetRecord.objects.filter(session=record).count() == 3
    cov_rec = ObservationCoverageRecord.objects.get(session=record)
    assert cov_rec.tracked_seconds == 140
    fb_rec = SessionFeedbackRecord.objects.get(session=record)
    assert fb_rec.perceived_effort == 8


@pytest.mark.django_db
def test_finish_session_rejects_duplicate_performed_set_pair(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    """Regression test: two performed sets sharing the same
    (exercise_id, set_order) pair within one finish call must be rejected
    before any activity is persisted, not silently deduplicated."""
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    performed_sets = [
        {"exerciseId": "exercise-push-up-v1", "setOrder": 1, "repetitions": 10},
        {"exerciseId": "exercise-push-up-v1", "setOrder": 1, "repetitions": 20},
    ]

    finish_resp = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-duplicate-set",
                },
                "performedSets": performed_sets,
            },
        },
        content_type="application/json",
    ).json()

    data = finish_resp["data"]["finishSession"]
    assert data["session"] is None
    assert any(err["code"] == "DUPLICATE_PERFORMED_SET" for err in data["errors"])

    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.state == "ACTIVE"
    assert PerformedSetRecord.objects.filter(session=record).count() == 0


@pytest.mark.django_db
def test_finish_session_rejects_exercise_not_in_accepted_routine(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    """Regression test: a performed set naming an exercise outside the
    accepted routine version must be rejected rather than silently accepted
    into the session's confirmed activity."""
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    performed_sets = [
        {"exerciseId": "exercise-burpee-v1", "setOrder": 1, "repetitions": 10},
    ]

    finish_resp = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-foreign-exercise",
                },
                "performedSets": performed_sets,
            },
        },
        content_type="application/json",
    ).json()

    data = finish_resp["data"]["finishSession"]
    assert data["session"] is None
    assert any(err["code"] == "UNKNOWN_ROUTINE_EXERCISE" for err in data["errors"])

    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.state == "ACTIVE"
    assert PerformedSetRecord.objects.filter(session=record).count() == 0


@pytest.mark.django_db
def test_finish_session_rejects_measurement_inconsistent_with_prescription(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    """Regression test: a repetitions-prescribed exercise submitted with only
    a duration measurement (and vice versa) must be rejected."""
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    # exercise-push-up-v1 is prescribed by repetitions in the fixture routine;
    # submitting only a duration must be rejected.
    performed_sets = [
        {"exerciseId": "exercise-push-up-v1", "setOrder": 1, "durationSeconds": 30},
    ]

    finish_resp = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-inconsistent-measurement",
                },
                "performedSets": performed_sets,
            },
        },
        content_type="application/json",
    ).json()

    data = finish_resp["data"]["finishSession"]
    assert data["session"] is None
    assert any(err["code"] == "INCONSISTENT_PERFORMED_SET_MEASUREMENT" for err in data["errors"])

    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.state == "ACTIVE"
    assert PerformedSetRecord.objects.filter(session=record).count() == 0


@pytest.mark.django_db
def test_finish_session_confirmed_repetitions_matches_persisted_sets(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    """Regression test: confirmed_repetitions must always equal the sum of
    the sets actually persisted, never a value derived from rejected or
    unpersisted input."""
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    performed_sets = [
        {"exerciseId": "exercise-push-up-v1", "setOrder": 1, "repetitions": 8},
        {"exerciseId": "exercise-push-up-v1", "setOrder": 2, "repetitions": 9},
        {"exerciseId": "exercise-plank-v1", "setOrder": 1, "durationSeconds": 45},
    ]

    finish_resp = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-consistency-check",
                },
                "performedSets": performed_sets,
            },
        },
        content_type="application/json",
    ).json()

    data = finish_resp["data"]["finishSession"]
    assert data["errors"] == []

    record = WorkoutSessionRecord.objects.get(id=session_id)
    persisted_repetitions = sum(
        s.repetitions or 0 for s in PerformedSetRecord.objects.filter(session=record)
    )
    assert record.confirmed_repetitions == persisted_repetitions == 17
    assert PerformedSetRecord.objects.filter(session=record).count() == 3


@pytest.mark.django_db
def test_duplicate_finish_calls_cannot_double_count_progress(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    performed_sets = [
        {"exerciseId": "exercise-push-up-v1", "setOrder": 1, "repetitions": 15},
        {"exerciseId": "exercise-push-up-v1", "setOrder": 2, "repetitions": 15},
    ]

    finish_payload = {
        "command": {
            "sessionId": session_id,
            "expectedRevision": session["revision"],
            "idempotencyKey": "idempotent-finish-key",
        },
        "performedSets": performed_sets,
        "observationCoverage": {
            "coverageRatio": 1.0,
            "trackedSeconds": 100,
            "totalSeconds": 100,
        },
        "feedback": {"perceivedEffort": 6},
    }

    # First finish call
    resp1 = client.post(
        "/graphql/",
        data={"query": FINISH_SESSION, "variables": finish_payload},
        content_type="application/json",
    ).json()
    data1 = resp1["data"]["finishSession"]
    assert data1["errors"] == []
    assert data1["session"]["confirmedRepetitions"] == 30
    assert len(data1["session"]["performedSets"]) == 2

    # Second identical finish call (retry with same idempotency key)
    resp2 = client.post(
        "/graphql/",
        data={"query": FINISH_SESSION, "variables": finish_payload},
        content_type="application/json",
    ).json()
    data2 = resp2["data"]["finishSession"]
    assert data2["errors"] == []
    assert data2["session"]["confirmedRepetitions"] == 30
    assert len(data2["session"]["performedSets"]) == 2

    # Verify sets were not duplicated in PostgreSQL
    record = WorkoutSessionRecord.objects.get(id=session_id)
    assert record.confirmed_repetitions == 30
    assert PerformedSetRecord.objects.filter(session=record).count() == 2

    # Third call with new idempotency key on completed session fails
    resp3 = client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                **finish_payload,
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 2,  # stale revision
                    "idempotencyKey": "new-finish-attempt",
                },
            },
        },
        content_type="application/json",
    ).json()
    data3 = resp3["data"]["finishSession"]
    assert any(err["code"] == "REVISION_CONFLICT" for err in data3["errors"])

    # Verify no double counting after all calls
    record.refresh_from_db()
    assert record.confirmed_repetitions == 30
    assert PerformedSetRecord.objects.filter(session=record).count() == 2


@pytest.mark.django_db
def test_record_session_feedback_post_finish(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    # Finish without feedback
    client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-no-feedback",
                }
            },
        },
        content_type="application/json",
    )

    # Exerciser records feedback post-finish
    fb_resp = client.post(
        "/graphql/",
        data={
            "query": RECORD_FEEDBACK,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 3,
                    "idempotencyKey": "feedback-key-1",
                },
                "feedback": {"perceivedEffort": 9, "comments": "Very intense workout!"},
            },
        },
        content_type="application/json",
    ).json()

    data = fb_resp["data"]["recordSessionFeedback"]
    assert data["errors"] == []
    assert data["session"]["revision"] == 4
    assert data["session"]["feedback"]["perceivedEffort"] == 9
    assert data["session"]["feedback"]["comments"] == "Very intense workout!"

    # Query session to verify it returns feedback
    query_resp = client.post(
        "/graphql/",
        data={"query": QUERY_SESSION, "variables": {"id": session_id}},
        content_type="application/json",
    ).json()
    retrieved = query_resp["data"]["session"]
    assert retrieved["id"] == session_id
    assert retrieved["feedback"]["perceivedEffort"] == 9
    assert retrieved["feedback"]["comments"] == "Very intense workout!"


@pytest.mark.django_db
def test_record_session_feedback_validates_effort_bounds(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    # Finish session
    client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-for-validation",
                }
            },
        },
        content_type="application/json",
    )

    # Attempt effort 0
    resp_low = client.post(
        "/graphql/",
        data={
            "query": RECORD_FEEDBACK,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 3,
                    "idempotencyKey": "fb-low",
                },
                "feedback": {"perceivedEffort": 0},
            },
        },
        content_type="application/json",
    ).json()
    errors_low = resp_low["data"]["recordSessionFeedback"]["errors"]
    assert any(err["code"] == "INVALID_INPUT" for err in errors_low)

    # Attempt effort 11
    resp_high = client.post(
        "/graphql/",
        data={
            "query": RECORD_FEEDBACK,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 3,
                    "idempotencyKey": "fb-high",
                },
                "feedback": {"perceivedEffort": 11},
            },
        },
        content_type="application/json",
    ).json()
    errors_high = resp_high["data"]["recordSessionFeedback"]["errors"]
    assert any(err["code"] == "INVALID_INPUT" for err in errors_high)


@pytest.mark.django_db
def test_session_query_returns_full_activity_through_use_cases(
    client: Client, athlete: User, accepted_routine: RoutineRecord
) -> None:
    """Regression test: the `session` query resolver must return the same
    performed sets, coverage, and feedback whether read through the use-case
    path or freshly persisted, since it no longer queries workouts tables
    directly (see GetWorkoutSessionUseCase)."""
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-for-query",
                },
                "performedSets": [
                    {"exerciseId": "exercise-push-up-v1", "setOrder": 1, "repetitions": 10},
                ],
                "observationCoverage": {
                    "coverageRatio": 0.8,
                    "trackedSeconds": 80,
                    "totalSeconds": 100,
                },
                "feedback": {"perceivedEffort": 7},
            },
        },
        content_type="application/json",
    )

    query_resp = client.post(
        "/graphql/",
        data={"query": QUERY_SESSION, "variables": {"id": session_id}},
        content_type="application/json",
    ).json()
    retrieved = query_resp["data"]["session"]

    assert retrieved["id"] == session_id
    assert retrieved["state"] == "COMPLETED"
    assert retrieved["confirmedRepetitions"] == 10
    assert retrieved["performedSets"] == [
        {
            "exerciseId": "exercise-push-up-v1",
            "setOrder": 1,
            "repetitions": 10,
            "durationSeconds": None,
        }
    ]
    assert retrieved["observationCoverage"]["coverageRatio"] == 0.8
    assert retrieved["feedback"]["perceivedEffort"] == 7


@pytest.mark.django_db
def test_session_query_enforces_owner_isolation(
    client: Client, athlete: User, other_athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    other_client = Client()
    other_client.force_login(other_athlete)
    response = other_client.post(
        "/graphql/",
        data={"query": QUERY_SESSION, "variables": {"id": session_id}},
        content_type="application/json",
    ).json()

    assert response["data"]["session"] is None


@pytest.mark.django_db
def test_cross_user_session_feedback_rejected(
    client: Client, athlete: User, other_athlete: User, accepted_routine: RoutineRecord
) -> None:
    client.force_login(athlete)
    session = prepare_and_start_session(client, accepted_routine)
    session_id = session["id"]

    client.post(
        "/graphql/",
        data={
            "query": FINISH_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": session["revision"],
                    "idempotencyKey": "finish-owner",
                }
            },
        },
        content_type="application/json",
    )

    # Other athlete attempts to record feedback
    client.force_login(other_athlete)
    resp = client.post(
        "/graphql/",
        data={
            "query": RECORD_FEEDBACK,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 3,
                    "idempotencyKey": "other-feedback",
                },
                "feedback": {"perceivedEffort": 5},
            },
        },
        content_type="application/json",
    ).json()
    errors = resp["data"]["recordSessionFeedback"]["errors"]
    assert any(err["code"] == "SESSION_NOT_FOUND" for err in errors)
