import json
from uuid import uuid4

import pytest
from django.test import Client

from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.application.ports import TransientSessionUpdate
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord
from kinetiq.modules.workouts.infrastructure.transient_store import RedisSessionTransientStore

ISSUE_MUTATION = """
mutation IssueCode($deviceType: DisplayDeviceType!) {
  issueDisplayPairingCode(deviceType: $deviceType) {
    code
    deviceType
    status
  }
}
"""

PAIR_MUTATION = """
mutation PairDevice($code: String!, $sessionId: ID) {
  pairDisplayDevice(code: $code, sessionId: $sessionId) {
    deviceType
    status
    sessionId
  }
}
"""

STATE_QUERY = """
query DisplayState($code: String!) {
  displaySessionState(code: $code) {
    deviceType
    status
    sessionId
    mode
    intensity
    state
    activeExercise
    confirmedReps
    visibilityStatus
  }
}
"""

CONFIGURATION = {
    "requested_mode": "NORMAL",
    "active_mode": "NORMAL",
    "intensity": "PLANNED",
    "coaching_tone": "CALM",
    "capture_device_id": "phone-camera",
    "display_device_id": None,
    "prompt_for_progress_photo": False,
    "dynamic": None,
}


@pytest.fixture
def athlete(db) -> User:
    return User.objects.create_user(username="display-athlete")


@pytest.fixture
def other_athlete(db) -> User:
    return User.objects.create_user(username="other-display-athlete")


def _issue_code(client: Client, device_type: str) -> str:
    resp = client.post(
        "/graphql/",
        data={"query": ISSUE_MUTATION, "variables": {"deviceType": device_type}},
        content_type="application/json",
    )
    data = resp.json()["data"]["issueDisplayPairingCode"]
    assert data["deviceType"] == device_type
    assert data["status"] == "UNPAIRED"
    return data["code"]


def _create_session(owner: User) -> WorkoutSessionRecord:
    routine = RoutineRecord.objects.create(
        owner=owner,
        routine_id=uuid4(),
        version=1,
        title="Display Pairing Test Routine",
        rationale="Integration test routine.",
        prescription={"items": []},
        accepted=True,
    )
    return WorkoutSessionRecord.objects.create(
        id=uuid4(),
        owner=owner,
        routine=routine,
        revision=1,
        state="ACTIVE",
        configuration=CONFIGURATION,
    )


def test_issue_display_pairing_code_is_not_predictable(client: Client) -> None:
    """Regression test: the issued code must never be the old fixed
    default -- a guessable code would let an unrelated party pair their
    own display to someone else's session."""
    code = _issue_code(client, "FIRE_TV")
    assert code != "FIRE-7892"
    assert code.startswith("FIRE-")

    state_resp = client.post(
        "/graphql/",
        data={"query": STATE_QUERY, "variables": {"code": code}},
        content_type="application/json",
    )
    assert state_resp.status_code == 200
    state_data = state_resp.json()["data"]["displaySessionState"]
    assert state_data["deviceType"] == "FIRE_TV"
    assert state_data["status"] == "UNPAIRED"
    assert state_data["sessionId"] is None


def test_pair_display_device_with_real_session_and_transient_update(
    athlete: User,
) -> None:
    """Integration test with a real owned session and a real transient
    update: proves the paired-session branch reads the actual repository
    and transient-store ports correctly end to end, rather than calling a
    nonexistent method or mismatched fields that only an AttributeError
    at runtime would have caught."""
    client = Client()
    client.force_login(athlete)

    code = _issue_code(client, "VEGA_OS")
    session = _create_session(athlete)

    pair_resp = client.post(
        "/graphql/",
        data={
            "query": PAIR_MUTATION,
            "variables": {"code": code, "sessionId": str(session.id)},
        },
        content_type="application/json",
    )
    assert pair_resp.status_code == 200
    pair_payload = pair_resp.json()
    assert "errors" not in pair_payload, pair_payload
    pair_data = pair_payload["data"]["pairDisplayDevice"]
    assert pair_data["deviceType"] == "VEGA_OS"
    assert pair_data["status"] == "PAIRED"
    assert pair_data["sessionId"] == str(session.id)

    # Before any transient update exists, the display must show no
    # fabricated progress -- zero reps, no invented exercise name.
    state_resp = client.post(
        "/graphql/",
        data={"query": STATE_QUERY, "variables": {"code": code}},
        content_type="application/json",
    )
    state_data = state_resp.json()["data"]["displaySessionState"]
    assert state_data["sessionId"] == str(session.id)
    assert state_data["mode"] == "NORMAL"
    assert state_data["intensity"] == "PLANNED"
    assert state_data["state"] == "ACTIVE"
    assert state_data["activeExercise"] is None
    assert state_data["confirmedReps"] == 0

    # Simulate the real producer (PollVisionObservationsUseCase) publishing
    # a validated update -- there is no client-facing way to fabricate one.
    RedisSessionTransientStore().publish_transient_update(
        TransientSessionUpdate(
            session_id=session.id,
            active_exercise_id="bodyweight_squat",
            current_repetitions=4,
            visibility_status="VISIBLE",
        )
    )

    refreshed_resp = client.post(
        "/graphql/",
        data={"query": STATE_QUERY, "variables": {"code": code}},
        content_type="application/json",
    )
    refreshed_data = refreshed_resp.json()["data"]["displaySessionState"]
    assert refreshed_data["activeExercise"] == "bodyweight_squat"
    assert refreshed_data["confirmedReps"] == 4
    assert refreshed_data["visibilityStatus"] == "VISIBLE"

    # A later Vision update -- the TV polling this same query again later
    # in the workout must see the newest state, not the first snapshot it
    # ever read. Proves genuine refresh, not a one-shot read cached at
    # pairing time.
    RedisSessionTransientStore().publish_transient_update(
        TransientSessionUpdate(
            session_id=session.id,
            active_exercise_id="push_up",
            current_repetitions=9,
            visibility_status="PARTIALLY_VISIBLE",
        )
    )

    later_resp = client.post(
        "/graphql/",
        data={"query": STATE_QUERY, "variables": {"code": code}},
        content_type="application/json",
    )
    later_data = later_resp.json()["data"]["displaySessionState"]
    assert later_data["activeExercise"] == "push_up"
    assert later_data["confirmedReps"] == 9
    assert later_data["visibilityStatus"] == "PARTIALLY_VISIBLE"


def test_pair_display_device_rejects_repairing_to_a_different_owner(
    athlete: User, other_athlete: User
) -> None:
    """A code already paired to one owner must never be re-pairable by a
    different owner -- that would let a second athlete who observed or
    guessed a live code redirect the display to their own session, or read
    the original owner's live progress."""
    client = Client()
    client.force_login(athlete)
    code = _issue_code(client, "FIRE_TV")
    session = _create_session(athlete)

    first_pair_resp = client.post(
        "/graphql/",
        data={"query": PAIR_MUTATION, "variables": {"code": code, "sessionId": str(session.id)}},
        content_type="application/json",
    )
    assert "errors" not in first_pair_resp.json()

    other_client = Client()
    other_client.force_login(other_athlete)
    other_session = _create_session(other_athlete)

    hijack_resp = other_client.post(
        "/graphql/",
        data={
            "query": PAIR_MUTATION,
            "variables": {"code": code, "sessionId": str(other_session.id)},
        },
        content_type="application/json",
    )
    payload = hijack_resp.json()
    assert payload.get("data") is None or payload["data"].get("pairDisplayDevice") is None
    assert "errors" in payload
    assert any("already paired" in str(e.get("message", "")).lower() for e in payload["errors"])

    # The original pairing must be completely unaffected by the rejected
    # attempt -- still the original owner's session, not the attacker's.
    state_resp = client.post(
        "/graphql/",
        data={"query": STATE_QUERY, "variables": {"code": code}},
        content_type="application/json",
    )
    state_data = state_resp.json()["data"]["displaySessionState"]
    assert state_data["sessionId"] == str(session.id)


def test_pair_display_device_allows_same_owner_to_repair(athlete: User) -> None:
    """The same owner reconnecting (e.g. the TV app restarting and
    re-pairing the same code) must not be rejected as a hijack attempt."""
    client = Client()
    client.force_login(athlete)
    code = _issue_code(client, "FIRE_TV")
    session = _create_session(athlete)

    for _ in range(2):
        resp = client.post(
            "/graphql/",
            data={
                "query": PAIR_MUTATION,
                "variables": {"code": code, "sessionId": str(session.id)},
            },
            content_type="application/json",
        )
        payload = resp.json()
        assert "errors" not in payload, payload
        assert payload["data"]["pairDisplayDevice"]["status"] == "PAIRED"


def test_pair_display_device_rejects_nonexistent_session_id(athlete: User) -> None:
    client = Client()
    client.force_login(athlete)
    code = _issue_code(client, "FIRE_TV")

    resp = client.post(
        "/graphql/",
        data={
            "query": PAIR_MUTATION,
            "variables": {"code": code, "sessionId": str(uuid4())},
        },
        content_type="application/json",
    )
    payload = resp.json()
    assert payload.get("data") is None or payload["data"].get("pairDisplayDevice") is None
    assert "errors" in payload
    assert any("not found" in str(e.get("message", "")).lower() for e in payload["errors"])

    # The pairing must remain UNPAIRED, not half-applied with the rejected id.
    state_resp = client.post(
        "/graphql/",
        data={"query": STATE_QUERY, "variables": {"code": code}},
        content_type="application/json",
    )
    state_data = state_resp.json()["data"]["displaySessionState"]
    assert state_data["status"] == "UNPAIRED"
    assert state_data["sessionId"] is None


def test_pair_display_device_rejects_foreign_session_id(
    athlete: User, other_athlete: User
) -> None:
    """A session that exists but belongs to a different owner must be
    rejected exactly like a nonexistent one -- pairing must never let a
    display show another athlete's session."""
    client = Client()
    client.force_login(athlete)
    code = _issue_code(client, "FIRE_TV")

    foreign_session = _create_session(other_athlete)

    resp = client.post(
        "/graphql/",
        data={
            "query": PAIR_MUTATION,
            "variables": {"code": code, "sessionId": str(foreign_session.id)},
        },
        content_type="application/json",
    )
    payload = resp.json()
    assert payload.get("data") is None or payload["data"].get("pairDisplayDevice") is None
    assert "errors" in payload


def test_pair_display_device_requires_authentication(client: Client) -> None:
    code = _issue_code(client, "FIRE_TV")

    resp = client.post(
        "/graphql/",
        data={"query": PAIR_MUTATION, "variables": {"code": code, "sessionId": None}},
        content_type="application/json",
    )
    payload = resp.json()
    assert payload.get("data") is None or payload["data"].get("pairDisplayDevice") is None
    assert "errors" in payload
    assert "AUTHENTICATION_REQUIRED" in json.dumps(payload["errors"])
