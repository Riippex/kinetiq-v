"""Streamable HTTP transport tests for the Kinetiq MCP server.

Verifies transport-level authentication (rejected before any tool runs),
DNS-rebinding protection, the exposed tool surface, and ASGI lifespan
management of the session manager.
"""

import asyncio
import inspect
from typing import Any

import pytest

from kinetiq.bootstrap.asgi import application, http_dispatcher
from kinetiq.interfaces.mcp import server as mcp_server_module
from kinetiq.interfaces.mcp import tools as mcp_tools_module
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.profiles.infrastructure.models import UserProfileRecord
from mcp_support import (
    ATTACKER_KEY,
    LifespanRunner,
    make_app,
    mcp_session,
    mint_token,
    oidc_settings,
    raw_mcp_post,
    result_payload,
)

SUBJECT = "aaaaaaaa-0000-4000-8000-000000000001"

MUTATING_TOOLS = {
    "update_profile",
    "set_goal",
    "propose_routine",
    "accept_routine",
    "prepare_session",
    "start_session",
    "pause_session",
    "resume_session",
    "abandon_session",
    "finish_session",
}
READ_ONLY_TOOLS = {
    "get_profile",
    "get_active_goal",
    "list_goal_revisions",
    "get_current_routine",
    "get_latest_session",
    "get_progress_summary",
}


@pytest.fixture
def athlete(db: object) -> User:
    return User.objects.create(
        username="mcp_http_athlete", email="http@kinetiq.test", cognito_subject=SUBJECT
    )


@pytest.mark.django_db(transaction=True)
def test_tool_surface_is_coaching_only_and_requires_idempotency_keys(athlete: User) -> None:
    async def scenario() -> None:
        app = make_app()
        async with LifespanRunner(app):
            async with mcp_session(app, mint_token(SUBJECT)) as session:
                tools = {t.name: t for t in (await session.list_tools()).tools}

        assert set(tools) == MUTATING_TOOLS | READ_ONLY_TOOLS
        assert not any("photo" in name or "media" in name for name in tools)
        for name in MUTATING_TOOLS:
            assert "idempotency_key" in tools[name].input_schema["required"], name
        for name in READ_ONLY_TOOLS:
            assert "idempotency_key" not in tools[name].input_schema.get("properties", {}), name
        # No tool lets the caller choose whose data to act on.
        for tool in tools.values():
            properties = set(tool.input_schema.get("properties", {}))
            assert not {"owner_id", "user_id", "athlete_id"} & properties

    asyncio.run(scenario())


@pytest.mark.django_db(transaction=True)
def test_authenticated_call_returns_the_token_subjects_profile(athlete: User) -> None:
    async def scenario() -> None:
        app = make_app()
        async with LifespanRunner(app):
            async with mcp_session(app, mint_token(SUBJECT)) as session:
                result = await session.call_tool("get_profile", {})
        assert result_payload(result)["id"] == str(athlete.id)

    asyncio.run(scenario())


@pytest.mark.django_db(transaction=True)
def test_project_dispatcher_routes_mcp_and_fails_closed_without_oidc_settings(
    athlete: User,
) -> None:
    async def scenario() -> None:
        # The module-level app is configured from Django settings, which have
        # no OIDC issuer/audience in tests, so it must reject every token.
        async with LifespanRunner(application):
            response = await raw_mcp_post(
                http_dispatcher, {"Authorization": f"Bearer {mint_token(SUBJECT)}"}
            )
        assert response.status_code == 401

    asyncio.run(scenario())


def _forged_credentials(athlete: User) -> dict[str, dict[str, str]]:
    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return {
        "no credentials": {},
        "forged user uuid": bearer(str(athlete.id)),
        "forged cognito subject": bearer(SUBJECT),
        "x-user-id header": {"X-User-Id": str(athlete.id)},
        "x-user-id with garbage bearer": {
            "X-User-Id": str(athlete.id),
            "Authorization": "Bearer nonsense",
        },
        "invalid signature": bearer(mint_token(SUBJECT, key=ATTACKER_KEY)),
        "expired token": bearer(mint_token(SUBJECT, expires_in=-60)),
        "incorrect issuer": bearer(mint_token(SUBJECT, issuer="https://evil.example/pool")),
        "incorrect audience": bearer(mint_token(SUBJECT, client_id="other-client")),
        "wrong token use": bearer(mint_token(SUBJECT, token_use="id")),
        "missing scope": bearer(mint_token(SUBJECT, scope="openid")),
    }


@pytest.mark.django_db(transaction=True)
def test_unauthenticated_and_forged_requests_are_rejected_before_any_tool_runs(
    athlete: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    executed: list[str] = []

    def spy(*args: Any, **kwargs: Any) -> None:
        executed.append("tool executed")
        raise AssertionError("a user-scoped use case ran for an unauthenticated request")

    monkeypatch.setattr(mcp_tools_module, "get_profile", spy)

    async def scenario() -> None:
        app = make_app()
        async with LifespanRunner(app):
            for label, headers in _forged_credentials(athlete).items():
                response = await raw_mcp_post(app, headers)
                assert response.status_code == 401, label
                assert "www-authenticate" in response.headers, label

            # The client library cannot even establish a session.
            with pytest.raises(Exception):  # noqa: B017 - transport-level 401
                async with mcp_session(app, str(athlete.id)) as session:
                    await session.call_tool("get_profile", {})

    asyncio.run(scenario())
    assert executed == []
    assert UserProfileRecord.objects.filter(owner_id=athlete.id).count() == 0


@pytest.mark.django_db(transaction=True)
def test_unconfigured_oidc_rejects_every_token(athlete: User) -> None:
    async def scenario() -> None:
        app = make_app(oidc=oidc_settings(issuer="", audience=""), verifier=None)
        async with LifespanRunner(app):
            response = await raw_mcp_post(
                app, {"Authorization": f"Bearer {mint_token(SUBJECT)}"}
            )
        assert response.status_code == 401

    asyncio.run(scenario())


@pytest.mark.django_db(transaction=True)
def test_dns_rebinding_protection_validates_host_and_origin(athlete: User) -> None:
    good = {"Authorization": f"Bearer {mint_token(SUBJECT)}"}

    async def scenario() -> None:
        app = make_app(allowed_origins=["https://alexa.example.com"])
        async with LifespanRunner(app):
            assert (await raw_mcp_post(app, good)).status_code == 200
            allowed = {**good, "Origin": "https://alexa.example.com"}
            assert (await raw_mcp_post(app, allowed)).status_code == 200
            # Rebinding attempts: unexpected Host or Origin, even with a valid token.
            assert (await raw_mcp_post(app, good, host="evil.example.com")).status_code == 421
            forged_origin = {**good, "Origin": "https://evil.example.com"}
            assert (await raw_mcp_post(app, forged_origin)).status_code == 403

    asyncio.run(scenario())


@pytest.mark.django_db(transaction=True)
def test_dns_rebinding_allow_lists_default_to_django_settings(
    athlete: User, settings: Any
) -> None:
    settings.MCP_ALLOWED_HOSTS = ["mcp.kinetiq.example"]
    settings.MCP_ALLOWED_ORIGINS = ["https://alexa.example.com"]
    good = {"Authorization": f"Bearer {mint_token(SUBJECT)}"}

    async def scenario() -> None:
        app = make_app(allowed_hosts=None, allowed_origins=None)
        async with LifespanRunner(app):
            ok = await raw_mcp_post(app, good, host="mcp.kinetiq.example")
            assert ok.status_code == 200
            assert (await raw_mcp_post(app, good, host="localhost")).status_code == 421
            forged_origin = {**good, "Origin": "https://evil.example.com"}
            blocked = await raw_mcp_post(app, forged_origin, host="mcp.kinetiq.example")
            assert blocked.status_code == 403

    asyncio.run(scenario())


def test_django_settings_derive_mcp_hosts_from_allowed_hosts(settings: Any) -> None:
    assert "localhost" in settings.MCP_ALLOWED_HOSTS
    assert "localhost:*" in settings.MCP_ALLOWED_HOSTS
    assert settings.MCP_ALLOWED_ORIGINS == []


def test_server_does_not_use_private_session_manager_members() -> None:
    source = inspect.getsource(mcp_server_module)
    assert "_task_group" not in source
    assert "_runner" not in source


@pytest.mark.django_db(transaction=True)
def test_multiple_app_instances_run_independently(athlete: User) -> None:
    async def scenario() -> None:
        app_a, app_b = make_app(), make_app()
        async with LifespanRunner(app_a), LifespanRunner(app_b):
            async with mcp_session(app_a, mint_token(SUBJECT)) as a:
                async with mcp_session(app_b, mint_token(SUBJECT)) as b:
                    first, second = await asyncio.gather(
                        a.call_tool("get_profile", {}), b.call_tool("get_profile", {})
                    )
        assert result_payload(first)["id"] == result_payload(second)["id"] == str(athlete.id)

    asyncio.run(scenario())


@pytest.mark.django_db(transaction=True)
def test_startup_shutdown_cycles_terminate_cleanly(athlete: User) -> None:
    async def scenario() -> None:
        baseline = {t for t in asyncio.all_tasks() if not t.done()}
        for _ in range(3):
            app = make_app()
            async with LifespanRunner(app):
                async with mcp_session(app, mint_token(SUBJECT)) as session:
                    result = await session.call_tool("get_profile", {})
                assert result_payload(result)["id"] == str(athlete.id)
            # A cycle with no traffic at all must also start and stop.
            async with LifespanRunner(make_app()):
                pass

        await asyncio.sleep(0)
        leaked = {t for t in asyncio.all_tasks() if not t.done()} - baseline
        # sse-starlette keeps exactly one shutdown watcher per event loop
        # (it ends with the loop); it is not per-app and must not accumulate.
        watchers = {t for t in leaked if t.get_coro().__name__ == "_shutdown_watcher"}
        assert len(watchers) <= 1
        assert leaked - watchers == set(), leaked - watchers

    asyncio.run(scenario())
