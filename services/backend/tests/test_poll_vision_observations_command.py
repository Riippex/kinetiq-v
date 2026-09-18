from io import StringIO
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.management import call_command
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application import (
    ConfirmSessionTargetUseCase,
    PollVisionObservationsUseCase,
    StartSessionVisionAnalysisUseCase,
)
from kinetiq.modules.workouts.application.ports import (
    TransientSessionUpdate,
    VisionAnalysisHandle,
    VisionCandidateInfo,
    VisionObservationsPage,
    VisionTargetConfirmation,
)
from kinetiq.modules.workouts.domain import SessionState
from kinetiq.modules.workouts.infrastructure.repositories import (
    DjangoRoutineItemLookup,
    DjangoSessionLifecycleRepository,
)


class _FakeVisionSessionAnalysisPort:
    def create_analysis(
        self, *, session_id, source_id, exercise_key, exercise_version, idempotency_key
    ):
        return VisionAnalysisHandle(
            analysis_id=f"fake-{session_id}", epoch=1, state="AWAITING_SELECTION"
        )

    def list_candidates(self, *, analysis_id):
        return (VisionCandidateInfo(candidate_id="vision-target-poll", confidence=0.95),)

    def select_target(self, *, analysis_id, candidate_id, expected_epoch, idempotency_key):
        return VisionTargetConfirmation(
            target_person_id=candidate_id, epoch=expected_epoch, state="TRACKING"
        )


class _FakeVisionObservationSourcePort:
    def __init__(self, page: VisionObservationsPage) -> None:
        self.page = page

    def poll_observations(self, *, analysis_id, after_cursor, limit):
        return self.page


class _FakeSessionTransientStore:
    def __init__(self) -> None:
        self.published: list[TransientSessionUpdate] = []

    def publish_transient_update(self, update: TransientSessionUpdate) -> bool:
        self.published.append(update)
        return True

    def get_transient_update(self, session_id: UUID) -> TransientSessionUpdate | None:
        return self.published[-1] if self.published else None


def _fake_start_session_vision_analysis() -> StartSessionVisionAnalysisUseCase:
    return StartSessionVisionAnalysisUseCase(
        DjangoSessionLifecycleRepository(),
        _FakeVisionSessionAnalysisPort(),
        DjangoRoutineItemLookup(),
    )


def _fake_confirm_session_target() -> ConfirmSessionTargetUseCase:
    return ConfirmSessionTargetUseCase(
        DjangoSessionLifecycleRepository(), _FakeVisionSessionAnalysisPort()
    )


PREPARE_SESSION = """
mutation PrepareSession($input: PrepareSessionInput!) {
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

START_ANALYSIS = """
mutation StartSessionVisionAnalysis($command: SessionCommandInput!) {
  startSessionVisionAnalysis(command: $command) {
    session { id revision state }
    errors { code message field }
  }
}
"""

CONFIRM_TARGET = """
mutation ConfirmSessionTarget($command: SessionCommandInput!, $targetPersonId: String!) {
  confirmSessionTarget(command: $command, targetPersonId: $targetPersonId) {
    session { id revision state }
    errors { code message field }
  }
}
"""


@pytest.fixture
def athlete() -> User:
    return User.objects.create_user(username="poll-athlete")


@pytest.fixture
def accepted_routine(athlete: User) -> RoutineRecord:
    return RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="Polling test routine",
        rationale="Observation ingestion test routine.",
        prescription={
            "items": [
                {
                    "order": 1,
                    "exerciseId": "bodyweight_squat",
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


def _tracking_session_id(client: Client, routine: RoutineRecord) -> str:
    """Prepares, starts, starts the Vision analysis, and confirms a target
    on a fresh session, leaving it ACTIVE with a confirmed target -- the
    state list_sessions_polling_vision requires."""
    prep = client.post(
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
                    "captureDeviceId": "camera-poll-1",
                    "idempotencyKey": "poll-prep-1",
                }
            },
        },
        content_type="application/json",
    ).json()["data"]["prepareSession"]
    session_id = prep["session"]["id"]

    client.post(
        "/graphql/",
        data={
            "query": START_SESSION,
            "variables": {
                "command": {
                    "sessionId": session_id,
                    "expectedRevision": 1,
                    "idempotencyKey": "poll-start-1",
                }
            },
        },
        content_type="application/json",
    )

    with patch(
        "kinetiq.interfaces.graphql.schema.start_session_vision_analysis",
        _fake_start_session_vision_analysis,
    ):
        client.post(
            "/graphql/",
            data={
                "query": START_ANALYSIS,
                "variables": {
                    "command": {
                        "sessionId": session_id,
                        "expectedRevision": 2,
                        "idempotencyKey": "poll-start-analysis-1",
                    }
                },
            },
            content_type="application/json",
        )

    with patch(
        "kinetiq.interfaces.graphql.schema.confirm_session_target", _fake_confirm_session_target
    ):
        client.post(
            "/graphql/",
            data={
                "query": CONFIRM_TARGET,
                "variables": {
                    "command": {
                        "sessionId": session_id,
                        "expectedRevision": 3,
                        "idempotencyKey": "poll-confirm-1",
                    },
                    "targetPersonId": "vision-target-poll",
                },
            },
            content_type="application/json",
        )

    return session_id


@pytest.mark.django_db
def test_list_sessions_polling_vision_requires_active_analysis_and_target(
    athlete: User, accepted_routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(athlete)

    repo = DjangoSessionLifecycleRepository()
    assert repo.list_sessions_polling_vision() == ()

    session_id = _tracking_session_id(client, accepted_routine)

    eligible = repo.list_sessions_polling_vision()
    assert len(eligible) == 1
    assert str(eligible[0].id) == session_id
    assert eligible[0].state == SessionState.ACTIVE
    assert eligible[0].vision_analysis_id is not None
    assert eligible[0].target_person_id == "vision-target-poll"


@pytest.mark.django_db
def test_advance_vision_observation_cursor_does_not_bump_revision(
    athlete: User, accepted_routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(athlete)
    session_id = _tracking_session_id(client, accepted_routine)

    repo = DjangoSessionLifecycleRepository()
    before = repo.get_session(owner_id=athlete.pk, session_id=UUID(session_id))
    assert before is not None

    repo.advance_vision_observation_cursor(
        owner_id=athlete.pk, session_id=UUID(session_id), cursor="4:12"
    )

    after = repo.get_session(owner_id=athlete.pk, session_id=UUID(session_id))
    assert after is not None
    assert after.vision_observation_cursor == "4:12"
    assert after.revision == before.revision
    assert after.target_person_id == before.target_person_id


@pytest.mark.django_db
def test_poll_vision_observations_command_publishes_and_advances_cursor(
    athlete: User, accepted_routine: RoutineRecord
) -> None:
    client = Client()
    client.force_login(athlete)
    session_id = _tracking_session_id(client, accepted_routine)

    fake_transient_store = _FakeSessionTransientStore()
    repo = DjangoSessionLifecycleRepository()
    session = repo.get_session(owner_id=athlete.pk, session_id=UUID(session_id))
    assert session is not None

    fake_use_case = PollVisionObservationsUseCase(
        repo,
        _FakeVisionObservationSourcePort(
            VisionObservationsPage(
                observations=(),
                next_cursor=None,
                has_more=False,
            )
        ),
        fake_transient_store,
    )

    with patch(
        "kinetiq.modules.workouts.infrastructure.management.commands."
        "poll_vision_observations.poll_vision_observations",
        lambda: fake_use_case,
    ):
        out = StringIO()
        call_command("poll_vision_observations", stdout=out)

    assert "Polled 1 session(s)" in out.getvalue()
