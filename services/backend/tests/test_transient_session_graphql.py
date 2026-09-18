from dataclasses import dataclass
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.cache import cache

from kinetiq.interfaces.graphql.schema import schema
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application import (
    ConfirmSessionTargetUseCase,
    StartSessionVisionAnalysisUseCase,
)
from kinetiq.modules.workouts.application.ports import (
    TransientSessionUpdate,
    VisionAnalysisHandle,
    VisionCandidateInfo,
    VisionTargetConfirmation,
)
from kinetiq.modules.workouts.infrastructure.repositories import (
    DjangoRoutineItemLookup,
    DjangoSessionLifecycleRepository,
)
from kinetiq.modules.workouts.infrastructure.transient_store import RedisSessionTransientStore


def _publish_server_produced_update(update: TransientSessionUpdate) -> None:
    """Simulates PollVisionObservationsUseCase publishing a validated
    update -- the only producer of transient state now that
    publishTransientSessionUpdate has been removed as a public mutation.
    """
    RedisSessionTransientStore().publish_transient_update(update)


@dataclass
class DummyContext:
    user: User | None = None


class _FakeVisionSessionAnalysisPort:
    """Deterministic Vision double: any candidate_id is treated as detected,
    so these tests exercise confirmSessionTarget's real wiring without a
    live Vision service."""

    def create_analysis(
        self, *, session_id, source_id, exercise_key, exercise_version, idempotency_key
    ):
        return VisionAnalysisHandle(
            analysis_id=f"fake-{session_id}", epoch=1, state="AWAITING_SELECTION"
        )

    def list_candidates(self, *, analysis_id):
        return (VisionCandidateInfo(candidate_id="vision-target-01", confidence=0.95),)

    def select_target(self, *, analysis_id, candidate_id, expected_epoch, idempotency_key):
        return VisionTargetConfirmation(
            target_person_id=candidate_id, epoch=expected_epoch, state="TRACKING"
        )


def _fake_confirm_session_target() -> ConfirmSessionTargetUseCase:
    return ConfirmSessionTargetUseCase(
        DjangoSessionLifecycleRepository(),
        _FakeVisionSessionAnalysisPort(),
    )


def _fake_start_session_vision_analysis() -> StartSessionVisionAnalysisUseCase:
    return StartSessionVisionAnalysisUseCase(
        DjangoSessionLifecycleRepository(),
        _FakeVisionSessionAnalysisPort(),
        DjangoRoutineItemLookup(),
    )


def _confirm_target(
    session_id: str, user: User, *, expected_revision: int, idempotency_key: str
) -> None:
    """Starts the session's Vision analysis (the now-mandatory first step
    of the split target-enrollment lifecycle) and then confirms a target,
    bumping the revision once for each of those two steps."""
    start_mutation = """
    mutation StartSessionVisionAnalysis($command: SessionCommandInput!) {
      startSessionVisionAnalysis(command: $command) {
        session { id revision }
        errors { code message field }
      }
    }
    """
    with patch(
        "kinetiq.interfaces.graphql.schema.start_session_vision_analysis",
        _fake_start_session_vision_analysis,
    ):
        start_result = schema.execute_sync(
            start_mutation,
            variable_values={
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": expected_revision,
                    "idempotencyKey": f"{idempotency_key}-start",
                }
            },
            context_value=DummyContext(user=user),
        )
    assert start_result.errors is None
    assert start_result.data["startSessionVisionAnalysis"]["errors"] == []

    confirm_mutation = """
    mutation ConfirmSessionTarget($command: SessionCommandInput!, $targetPersonId: String!) {
      confirmSessionTarget(command: $command, targetPersonId: $targetPersonId) {
        session { id revision }
        errors { code message field }
      }
    }
    """
    with patch(
        "kinetiq.interfaces.graphql.schema.confirm_session_target", _fake_confirm_session_target
    ):
        result = schema.execute_sync(
            confirm_mutation,
            variable_values={
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": expected_revision + 1,
                    "idempotencyKey": idempotency_key,
                },
                "targetPersonId": "vision-target-01",
            },
            context_value=DummyContext(user=user),
        )
    assert result.errors is None
    assert result.data["confirmSessionTarget"]["errors"] == []


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _create_user(username: str) -> User:
    return User.objects.create_user(username=username)


def _create_routine(user: User) -> RoutineRecord:
    return RoutineRecord.objects.create(
        owner=user,
        routine_id=uuid4(),
        version=1,
        title="Foundation Routine",
        rationale="Test routine",
        accepted=True,
        prescription={
            "items": [
                {
                    "order": 1,
                    "exerciseId": "goblet-squat",
                    "exerciseVersion": 1,
                    "name": "Goblet Squat",
                    "sets": 3,
                    "repetitions": 10,
                }
            ]
        },
    )


@pytest.mark.django_db
def test_transient_session_state_query_reads_server_produced_update():
    """Regression test for the Block 4 finding: publishTransientSessionUpdate
    let any authenticated owner of a session with a confirmed target
    submit arbitrary progress values, forging a "live Vision result".
    That mutation is removed; the only way transient state now reaches
    the store is a server-side producer (PollVisionObservationsUseCase),
    simulated here by publishing directly through
    RedisSessionTransientStore. The transientSessionState query must
    still read whatever the server produced."""
    user = _create_user("transient1")
    routine = _create_routine(user)

    prep_mutation = """
    mutation PrepareSession($input: PrepareSessionInput!) {
      prepareSession(input: $input) {
        session { id revision state }
        errors { code message field }
      }
    }
    """
    prep_result = schema.execute_sync(
        prep_mutation,
        variable_values={
            "input": {
                "routineId": str(routine.routine_id),
                "routineVersion": routine.version,
                "mode": "NORMAL",
                "intensity": "PLANNED",
                "coachingTone": "CALM",
                "captureDeviceId": "phone-cam-01",
                "idempotencyKey": "transient-prep-01",
            }
        },
        context_value=DummyContext(user=user),
    )
    assert prep_result.errors is None
    session_id = prep_result.data["prepareSession"]["session"]["id"]

    # Confirm target: transient updates require a Vision-confirmed target.
    _confirm_target(session_id, user, expected_revision=1, idempotency_key="transient-confirm-01")

    # Simulate the real producer (PollVisionObservationsUseCase) publishing
    # a validated update -- there is no client-facing way to do this now.
    _publish_server_produced_update(
        TransientSessionUpdate(
            session_id=UUID(session_id),
            active_exercise_id="goblet-squat",
            current_repetitions=8,
            pose_confidence=0.94,
            visibility_status="VISIBLE",
            timestamp="2026-09-17T13:20:00Z",
        )
    )

    # Query transient state
    query_str = """
    query GetTransientState($sessionId: ID!) {
      transientSessionState(sessionId: $sessionId) {
        sessionId
        activeExerciseId
        currentRepetitions
        poseConfidence
        visibilityStatus
        timestamp
      }
    }
    """
    query_result = schema.execute_sync(
        query_str,
        variable_values={"sessionId": session_id},
        context_value=DummyContext(user=user),
    )
    assert query_result.errors is None
    transient_data = query_result.data["transientSessionState"]
    assert transient_data is not None
    assert transient_data["sessionId"] == session_id
    assert transient_data["activeExerciseId"] == "goblet-squat"
    assert transient_data["currentRepetitions"] == 8
    assert transient_data["poseConfidence"] == 0.94
    assert transient_data["visibilityStatus"] == "VISIBLE"


@pytest.mark.django_db
def test_redis_loss_degrades_gracefully_and_restores_committed_state():
    user = _create_user("transient2")
    routine = _create_routine(user)

    prep_mutation = """
    mutation PrepareSession($input: PrepareSessionInput!) {
      prepareSession(input: $input) {
        session { id revision state }
        errors { code message field }
      }
    }
    """
    prep_result = schema.execute_sync(
        prep_mutation,
        variable_values={
            "input": {
                "routineId": str(routine.routine_id),
                "routineVersion": routine.version,
                "mode": "NORMAL",
                "intensity": "PLANNED",
                "coachingTone": "CALM",
                "captureDeviceId": "phone-cam-02",
                "idempotencyKey": "transient-prep-02",
            }
        },
        context_value=DummyContext(user=user),
    )
    session_id = prep_result.data["prepareSession"]["session"]["id"]

    # Confirm target: transient updates require a Vision-confirmed target.
    # Must happen before finish (target cannot be confirmed on a finished
    # session). _confirm_target performs two revision-bumping steps
    # (startSessionVisionAnalysis, then confirmSessionTarget), which shifts
    # the start/finish revisions below by two.
    _confirm_target(session_id, user, expected_revision=1, idempotency_key="transient-confirm-02")

    # Start session
    start_mutation = """
    mutation StartSession($command: SessionCommandInput!) {
      startSession(command: $command) {
        session { id revision state }
        errors { code message field }
      }
    }
    """
    schema.execute_sync(
        start_mutation,
        variable_values={
            "command": {
                "sessionId": session_id,
                "expectedRevision": 3,
                "idempotencyKey": "start-02",
            }
        },
        context_value=DummyContext(user=user),
    )

    # Finish session with committed performance
    finish_mutation = """
    mutation FinishSession(
      $command: SessionCommandInput!
      $performedSets: [PerformedSetInput!]
    ) {
      finishSession(command: $command, performedSets: $performedSets) {
        session { id revision state confirmedRepetitions }
        errors { code message field }
      }
    }
    """
    finish_result = schema.execute_sync(
        finish_mutation,
        variable_values={
            "command": {
                "sessionId": session_id,
                "expectedRevision": 4,
                "idempotencyKey": "finish-02",
            },
            "performedSets": [
                {"exerciseId": "goblet-squat", "setOrder": 1, "repetitions": 10}
            ],
        },
        context_value=DummyContext(user=user),
    )
    assert finish_result.errors is None
    assert finish_result.data["finishSession"]["session"]["state"] == "COMPLETED"
    assert finish_result.data["finishSession"]["session"]["confirmedRepetitions"] == 10

    # Simulate the real producer publishing before a Redis flush.
    _publish_server_produced_update(
        TransientSessionUpdate(
            session_id=UUID(session_id),
            active_exercise_id="goblet-squat",
            current_repetitions=10,
        )
    )

    # Simulate complete Redis flush/loss
    cache.clear()

    # Querying transient state now returns None
    query_transient = """
    query GetTransientState($sessionId: ID!) {
      transientSessionState(sessionId: $sessionId) {
        sessionId
        currentRepetitions
      }
    }
    """
    t_result = schema.execute_sync(
        query_transient,
        variable_values={"sessionId": session_id},
        context_value=DummyContext(user=user),
    )
    assert t_result.errors is None
    assert t_result.data["transientSessionState"] is None

    # Reconnect check: Querying committed session state from PostgreSQL succeeds intact!
    query_session = """
    query GetSession($id: ID!) {
      session(id: $id) {
        id
        state
        confirmedRepetitions
        performedSets { exerciseId setOrder repetitions }
      }
    }
    """
    s_result = schema.execute_sync(
        query_session,
        variable_values={"id": session_id},
        context_value=DummyContext(user=user),
    )
    assert s_result.errors is None
    session_data = s_result.data["session"]
    assert session_data is not None
    assert session_data["state"] == "COMPLETED"
    assert session_data["confirmedRepetitions"] == 10
    assert len(session_data["performedSets"]) == 1
    assert session_data["performedSets"][0]["exerciseId"] == "goblet-squat"


@pytest.mark.django_db
def test_transient_session_state_query_requires_authentication_and_ownership():
    """The read side must stay ownership-protected even though the write
    side (publishTransientSessionUpdate) is gone: an unauthenticated
    caller is rejected outright, and a different user's session must not
    leak another owner's transient progress."""
    user1 = _create_user("owner1")
    user2 = _create_user("owner2")
    routine = _create_routine(user1)

    prep_result = schema.execute_sync(
        """
        mutation PrepareSession($input: PrepareSessionInput!) {
          prepareSession(input: $input) { session { id revision state } }
        }
        """,
        variable_values={
            "input": {
                "routineId": str(routine.routine_id),
                "routineVersion": routine.version,
                "mode": "NORMAL",
                "intensity": "PLANNED",
                "coachingTone": "CALM",
                "captureDeviceId": "phone-cam-03",
                "idempotencyKey": "transient-prep-03",
            }
        },
        context_value=DummyContext(user=user1),
    )
    session_id = prep_result.data["prepareSession"]["session"]["id"]
    _publish_server_produced_update(
        TransientSessionUpdate(session_id=UUID(session_id), current_repetitions=5)
    )

    query_str = """
    query GetTransientState($sessionId: ID!) {
      transientSessionState(sessionId: $sessionId) { sessionId currentRepetitions }
    }
    """

    # Unauthenticated attempt
    unauth_res = schema.execute_sync(
        query_str,
        variable_values={"sessionId": session_id},
        context_value=DummyContext(user=None),
    )
    assert unauth_res.errors is not None
    assert "AUTHENTICATION_REQUIRED" in str(unauth_res.errors[0])

    # User 2 querying User 1's session must not see it.
    wrong_res = schema.execute_sync(
        query_str,
        variable_values={"sessionId": session_id},
        context_value=DummyContext(user=user2),
    )
    assert wrong_res.errors is None
    assert wrong_res.data["transientSessionState"] is None

    # The real owner still sees it.
    owner_res = schema.execute_sync(
        query_str,
        variable_values={"sessionId": session_id},
        context_value=DummyContext(user=user1),
    )
    assert owner_res.errors is None
    assert owner_res.data["transientSessionState"]["currentRepetitions"] == 5


def test_publish_transient_session_update_mutation_no_longer_exists():
    """Regression test for the Block 4 finding: publishTransientSessionUpdate
    let any authenticated owner of a session with a confirmed target
    forge arbitrary "live Vision result" values. The mutation, and its
    TransientSessionUpdateInput/TransientSessionUpdateResult types, must
    no longer be part of the public schema at all -- not merely
    access-restricted further."""
    result = schema.execute_sync(
        """
        mutation PublishTransient($input: TransientSessionUpdateInput!) {
          publishTransientSessionUpdate(input: $input) {
            success
            errors { code message field }
          }
        }
        """,
        variable_values={"input": {"sessionId": str(uuid4()), "currentRepetitions": 5}},
        context_value=DummyContext(user=None),
    )
    assert result.errors is not None
    assert any("publishTransientSessionUpdate" in str(error) for error in result.errors)


def test_redis_store_handles_exceptions_safely():
    store = RedisSessionTransientStore()
    dummy_session_id = uuid4()
    update = TransientSessionUpdate(session_id=dummy_session_id, current_repetitions=3)

    # Mock cache.set raising an exception
    with patch("django.core.cache.cache.set", side_effect=RuntimeError("Redis connection lost")):
        success = store.publish_transient_update(update)
        assert success is False

    # Mock cache.get raising an exception
    with patch("django.core.cache.cache.get", side_effect=RuntimeError("Redis connection lost")):
        res = store.get_transient_update(dummy_session_id)
        assert res is None
