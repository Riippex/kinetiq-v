"""Declared Alexa+ simulation over a real uvicorn server.

There is no Alexa+ device or account in this repository, so an MCP client
plays the Alexa+ caller ("alexa-plus-simulator"). Everything on the server
side is real: a uvicorn server runs the MCP ASGI app under the standard ASGI
lifespan, bearer tokens are RS256 JWTs whose keys are fetched over HTTP from a
local JWKS endpoint by the production `JWKSClientResolver`, and the tools run
against the real product use cases and database.
"""

import asyncio
import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from httpx2 import AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from kinetiq.interfaces.mcp import OIDCTokenVerifier
from kinetiq.interfaces.mcp.auth import JWKSClientResolver
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
from kinetiq.modules.goals.infrastructure.models import GoalRevisionRecord
from kinetiq.modules.identity.infrastructure.models import User
from mcp_support import (
    ATTACKER_KEY,
    UvicornThread,
    make_app,
    mint_token,
    oidc_settings,
    result_payload,
    trusted_jwks,
)

SUBJECT = "cccccccc-0000-4000-8000-00000000000c"


class _JWKSHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = json.dumps(trusted_jwks()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def jwks_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _JWKSHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/.well-known/jwks.json"
    server.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def mcp_uvicorn_url(jwks_url: str) -> Iterator[str]:
    settings = oidc_settings(jwks_url=jwks_url)
    app = make_app(
        oidc=settings,
        verifier=OIDCTokenVerifier(settings, JWKSClientResolver(jwks_url)),
        resource_url="http://127.0.0.1/mcp",
        allowed_hosts=["127.0.0.1", "127.0.0.1:*"],
    )
    baseline_threads = set(threading.enumerate())
    harness = UvicornThread(app, _free_port())
    harness.start()

    yield f"http://127.0.0.1:{harness.port}/mcp"

    # Lifespan shutdown must complete, the loop must close with no unexpected
    # pending task, and no thread started by the server may outlive it.
    harness.stop()
    lingering = [
        t for t in set(threading.enumerate()) - baseline_threads
        if t.is_alive() and not t.name.startswith(("ThreadPoolExecutor", "asgiref"))
    ]
    for thread in lingering:
        thread.join(timeout=5)
    assert [t.name for t in lingering if t.is_alive()] == []


async def _alexa_call(session: ClientSession, tool: str, **arguments: Any) -> Any:
    return result_payload(await session.call_tool(tool, arguments))


@pytest.mark.django_db(transaction=True)
def test_declared_alexa_plus_simulation_over_real_uvicorn(mcp_uvicorn_url: str) -> None:
    athlete = User.objects.create(
        username="alexa_athlete", email="alexa@kinetiq.test", cognito_subject=SUBJECT
    )
    SeedCatalogUseCase(
        catalog_repo=DjangoCatalogRepository(), vision_capabilities=FileBasedVisionCapabilities()
    ).execute(
        goals=CANONICAL_GOALS, exercises=CANONICAL_EXERCISES, templates=CANONICAL_TEMPLATES
    )

    async def scenario() -> list[str]:
        transcript: list[str] = []

        # 1. Callers without a valid signed token never reach a tool.
        for label, token in (
            ("no token", None),
            ("forged uuid", str(athlete.id)),
            ("forged signature", mint_token(SUBJECT, key=ATTACKER_KEY)),
        ):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            async with AsyncClient(headers=headers) as client:
                with pytest.raises(Exception):  # noqa: B017 - HTTP 401 during initialize
                    transport = streamable_http_client(mcp_uvicorn_url, http_client=client)
                    async with transport as (r, w):
                        async with ClientSession(r, w) as session:
                            await session.initialize()
            transcript.append(f"rejected: {label}")

        # 2. The simulated Alexa+ caller, authenticated with a valid token.
        headers = {"Authorization": f"Bearer {mint_token(SUBJECT)}"}
        async with AsyncClient(headers=headers) as client:
            async with streamable_http_client(mcp_uvicorn_url, http_client=client) as (r, w):
                async with ClientSession(r, w) as alexa:
                    init = await alexa.initialize()
                    transcript.append(f"connected to {init.server_info.name}")

                    profile = await _alexa_call(alexa, "get_profile")
                    assert profile["id"] == str(athlete.id)
                    transcript.append("Alexa: what is my profile? -> ok")

                    goal_args = {
                        "idempotency_key": "alexa-utterance-0001",
                        "description": "Train three times a week",
                        "measure": "weekly_completed_sessions",
                        "baseline": 0.0,
                        "target": 3.0,
                        "unit": "sessions/week",
                    }
                    first = await _alexa_call(alexa, "set_goal", **goal_args)
                    retry = await _alexa_call(alexa, "set_goal", **goal_args)  # Alexa retries
                    assert first == retry
                    transcript.append("Alexa: set my goal (retried) -> one revision")

                    proposal = await _alexa_call(
                        alexa, "propose_routine", idempotency_key="alexa-utterance-0002"
                    )
                    routine = await _alexa_call(
                        alexa,
                        "accept_routine",
                        idempotency_key="alexa-utterance-0003",
                        routine_id=proposal["routine_id"],
                        version=proposal["version"],
                    )
                    assert routine["status"] == "ACCEPTED"
                    transcript.append("Alexa: propose and accept my routine -> ok")

                    progress = await _alexa_call(alexa, "get_progress_summary")
                    assert progress["goal_progress"]["target"] == 3.0
                    transcript.append("Alexa: how is my progress? -> ok")

                    tool_names = {t.name for t in (await alexa.list_tools()).tools}
                    assert not any("photo" in name for name in tool_names)
                    transcript.append("no photo tool exposed")
        return transcript

    transcript = asyncio.run(scenario())
    assert transcript[0] == "rejected: no token"
    assert GoalRevisionRecord.objects.filter(owner_id=athlete.id).count() == 1
    print("\n".join(["ALEXA+ SIMULATION TRANSCRIPT", *transcript]))
