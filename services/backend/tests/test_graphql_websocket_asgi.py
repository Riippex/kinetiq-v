"""Real ASGI websocket handshake and subscription tests.

Unlike tests/test_graphql_websocket_auth.py (which calls
AuthenticatedGraphQLWSConsumer.get_context directly, bypassing the ASGI
protocol entirely) and packages/session-client's fake-WebSocket tests
(which never touch the server), these tests drive the actual
bootstrap.asgi.application through channels.testing.WebsocketCommunicator:
a real ASGI handshake, real channels.security.websocket.
AllowedHostsOriginValidator origin checks, real channels.auth.
AuthMiddlewareStack session-cookie resolution, and a real
graphql-transport-ws protocol exchange over it -- including an end-to-end
subscription delivery through a real Redis Pub/Sub channel.
"""

import asyncio
import json
from uuid import uuid4

import pytest
from channels.testing import WebsocketCommunicator
from django.test import Client

from kinetiq.bootstrap.asgi import application
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.routines.infrastructure.models import RoutineRecord
from kinetiq.modules.workouts.infrastructure.models import WorkoutSessionRecord

TEST_REDIS_URL = "redis://127.0.0.1:16379/0"

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

SUBSCRIPTION_QUERY = """
subscription TransientSessionUpdates($sessionId: ID!) {
  transientSessionUpdates(sessionId: $sessionId) {
    sessionId
    currentRepetitions
    visibilityStatus
  }
}
"""


def _create_session(athlete: User) -> WorkoutSessionRecord:
    routine = RoutineRecord.objects.create(
        owner=athlete,
        routine_id=uuid4(),
        version=1,
        title="WS ASGI Test Routine",
        rationale="Real ASGI websocket handshake/subscription test routine.",
        prescription={"items": []},
        accepted=True,
    )
    return WorkoutSessionRecord.objects.create(
        id=uuid4(),
        owner=athlete,
        routine=routine,
        revision=1,
        state="ACTIVE",
        configuration=CONFIGURATION,
    )


def _session_cookie_header(athlete: User) -> bytes:
    client = Client()
    client.force_login(athlete)
    # Force the session to actually persist a cookie (force_login alone
    # sets client.cookies without necessarily hitting the session store
    # until a request is made).
    client.get("/health/")
    session_cookie = client.cookies["sessionid"]
    return f"sessionid={session_cookie.value}".encode()


@pytest.mark.django_db(transaction=True)
def test_websocket_handshake_rejects_missing_origin() -> None:
    """AllowedHostsOriginValidator must deny the handshake outright when
    no Origin header is present, before auth or the consumer ever run."""

    async def run() -> None:
        communicator = WebsocketCommunicator(application, "/graphql")
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    asyncio.run(run())


@pytest.mark.django_db(transaction=True)
def test_websocket_handshake_rejects_disallowed_origin() -> None:
    async def run() -> None:
        communicator = WebsocketCommunicator(
            application,
            "/graphql",
            headers=[(b"origin", b"http://evil.example.com")],
        )
        connected, _ = await communicator.connect()
        assert connected is False
        await communicator.disconnect()

    asyncio.run(run())


@pytest.mark.django_db(transaction=True)
def test_websocket_subscription_without_session_cookie_is_unauthenticated(
    settings,
) -> None:
    """The handshake itself succeeds (origin validation only cares about
    Origin, not auth), but subscribing without a session cookie must fail
    with an authentication error -- proving the anonymous case is rejected
    over the real transport, not just in the direct-context unit test."""
    settings.REDIS_URL = TEST_REDIS_URL
    athlete = User.objects.create_user(username=f"ws-anon-{uuid4().hex[:8]}")
    session = _create_session(athlete)

    async def run() -> None:
        communicator = WebsocketCommunicator(
            application,
            "/graphql",
            headers=[(b"origin", b"http://localhost")],
            subprotocols=["graphql-transport-ws"],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to({"type": "connection_init"})
        ack = await communicator.receive_json_from(timeout=5)
        assert ack["type"] == "connection_ack"

        await communicator.send_json_to(
            {
                "type": "subscribe",
                "id": "1",
                "payload": {
                    "query": SUBSCRIPTION_QUERY,
                    "variables": {"sessionId": str(session.id)},
                },
            }
        )
        # A resolver-raised error surfaces as a 'next' message carrying a
        # GraphQL errors array (graphql-transport-ws protocol semantics
        # for a runtime error, as opposed to a top-level 'error' message
        # reserved for request-level failures like a malformed query).
        message = await communicator.receive_json_from(timeout=5)
        assert message["type"] == "next"
        assert message["id"] == "1"
        errors = message["payload"]["errors"]
        assert len(errors) == 1
        assert "AUTHENTICATION_REQUIRED" in errors[0]["message"]

        await communicator.disconnect()

    asyncio.run(run())


@pytest.mark.django_db(transaction=True)
def test_websocket_authenticated_subscription_receives_real_redis_publish(
    settings,
) -> None:
    """Full real-transport round trip: a real ASGI handshake behind real
    origin validation, a real Django session cookie authenticating the
    connection via AuthMiddlewareStack, a real graphql-transport-ws
    subscribe, and a real message published to Redis by an independent
    client (simulating PollVisionObservationsUseCase's publisher)
    delivered back over the websocket as a 'next' message."""
    settings.REDIS_URL = TEST_REDIS_URL
    athlete = User.objects.create_user(username=f"ws-auth-{uuid4().hex[:8]}")
    session = _create_session(athlete)
    cookie_header = _session_cookie_header(athlete)

    async def run() -> None:
        import redis.asyncio as aioredis

        communicator = WebsocketCommunicator(
            application,
            "/graphql",
            headers=[
                (b"origin", b"http://localhost"),
                (b"cookie", cookie_header),
            ],
            subprotocols=["graphql-transport-ws"],
        )
        connected, _ = await communicator.connect()
        assert connected is True

        await communicator.send_json_to({"type": "connection_init"})
        ack = await communicator.receive_json_from(timeout=5)
        assert ack["type"] == "connection_ack"

        await communicator.send_json_to(
            {
                "type": "subscribe",
                "id": "1",
                "payload": {
                    "query": SUBSCRIPTION_QUERY,
                    "variables": {"sessionId": str(session.id)},
                },
            }
        )

        # Give the resolver a moment to actually subscribe to the Redis
        # channel before we publish, then publish exactly as
        # RedisSessionTransientStore does.
        await asyncio.sleep(0.3)
        redis_client = aioredis.Redis.from_url(TEST_REDIS_URL)
        try:
            channel = f"kinetiq:session:{session.id}:stream"
            payload = {
                "session_id": str(session.id),
                "active_exercise_id": None,
                "current_repetitions": 7,
                "current_duration_seconds": None,
                "pose_confidence": 0.93,
                "visibility_status": "VISIBLE",
                "timestamp": "2026-09-18T00:00:00Z",
            }
            receivers = await redis_client.publish(channel, json.dumps(payload))
            assert receivers >= 1, "the resolver was not subscribed when we published"
        finally:
            await redis_client.aclose()

        message = await communicator.receive_json_from(timeout=5)
        assert message["type"] == "next"
        assert message["id"] == "1"
        update = message["payload"]["data"]["transientSessionUpdates"]
        assert update["sessionId"] == str(session.id)
        assert update["currentRepetitions"] == 7
        assert update["visibilityStatus"] == "VISIBLE"

        await communicator.disconnect()

    asyncio.run(run())
