"""Shared helpers for MCP tests: signed OIDC tokens, a trusted JWKS, an ASGI
lifespan runner, and an authenticated MCP client session."""

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx2 import ASGITransport, AsyncClient
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from starlette.applications import Starlette

from kinetiq.interfaces.mcp import OIDCSettings, OIDCTokenVerifier, create_mcp_asgi_app

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_KINETIQTEST"
AUDIENCE = "kinetiq-alexa-client"
SCOPE = "kinetiq/coach"
MCP_URL = "http://localhost/mcp"
TRUSTED_KID = "trusted-key-1"


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


TRUSTED_KEY = _new_key()
# Same `kid` as the trusted key, different key material: a forged signature.
ATTACKER_KEY = _new_key()


def trusted_jwks() -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(TRUSTED_KEY.public_key()))
    jwk.update({"kid": TRUSTED_KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


class StaticJWKSResolver:
    """Resolves signing keys from a fixed, trusted JWKS document."""

    def __init__(self, jwks: dict[str, Any] | None = None) -> None:
        self._set = jwt.PyJWKSet.from_dict(jwks or trusted_jwks())

    def get_signing_key(self, token: str) -> Any:
        kid = jwt.get_unverified_header(token).get("kid")
        for key in self._set.keys:
            if key.key_id == kid:
                return key.key
        raise jwt.PyJWKClientError(f"Unable to find a signing key that matches kid {kid!r}")


def oidc_settings(**overrides: Any) -> OIDCSettings:
    values: dict[str, Any] = {
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "jwks_url": f"{ISSUER}/.well-known/jwks.json",
        "required_scope": SCOPE,
        "token_use": "access",
    }
    values.update(overrides)
    return OIDCSettings(**values)


def make_verifier(**overrides: Any) -> OIDCTokenVerifier:
    return OIDCTokenVerifier(oidc_settings(**overrides), StaticJWKSResolver())


def mint_token(
    subject: str,
    *,
    key: rsa.RSAPrivateKey = TRUSTED_KEY,
    kid: str = TRUSTED_KID,
    issuer: str = ISSUER,
    client_id: str | None = AUDIENCE,
    aud: str | Sequence[str] | None = None,
    scope: str | None = SCOPE,
    token_use: str | None = "access",
    expires_in: int = 300,
    extra: dict[str, Any] | None = None,
) -> str:
    """Mint a Cognito-style access token (`client_id`, `token_use`, `scope`)."""
    now = int(time.time())
    claims: dict[str, Any] = {"sub": subject, "iss": issuer, "iat": now, "exp": now + expires_in}
    if client_id is not None:
        claims["client_id"] = client_id
    if aud is not None:
        claims["aud"] = aud
    if scope is not None:
        claims["scope"] = scope
    if token_use is not None:
        claims["token_use"] = token_use
    claims.update(extra or {})
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def make_app(**kwargs: Any) -> Starlette:
    """MCP app trusting the test JWKS, with Host/Origin protection enabled."""
    kwargs.setdefault("oidc", oidc_settings())
    kwargs.setdefault("verifier", OIDCTokenVerifier(kwargs["oidc"], StaticJWKSResolver()))
    kwargs.setdefault("resource_url", MCP_URL)
    kwargs.setdefault("allowed_hosts", ["localhost", "localhost:*"])
    kwargs.setdefault("allowed_origins", [])
    return create_mcp_asgi_app(path="/mcp", **kwargs)


class LifespanRunner:
    """Drives the ASGI lifespan protocol (startup/shutdown) for an app."""

    def __init__(self, app: Any, timeout: float = 10.0) -> None:
        self._app = app
        self._timeout = timeout
        self._to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "LifespanRunner":
        scope = {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}
        self._task = asyncio.create_task(self._app(scope, self._to_app.get, self._from_app.put))
        await self._to_app.put({"type": "lifespan.startup"})
        message = await asyncio.wait_for(self._from_app.get(), self._timeout)
        assert message["type"] == "lifespan.startup.complete", message
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._task is not None
        await self._to_app.put({"type": "lifespan.shutdown"})
        message = await asyncio.wait_for(self._from_app.get(), self._timeout)
        assert message["type"] == "lifespan.shutdown.complete", message
        await asyncio.wait_for(self._task, self._timeout)


@asynccontextmanager
async def mcp_session(
    app: Any, token: str | None = None, headers: dict[str, str] | None = None
) -> AsyncIterator[ClientSession]:
    """An initialized MCP client session over Streamable HTTP into `app`."""
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://localhost", headers=request_headers
    ) as client:
        async with streamable_http_client(MCP_URL, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def result_payload(result: CallToolResult) -> Any:
    """Structured payload of a successful tool call."""
    assert not result.is_error, result.content
    structured = result.structured_content
    if isinstance(structured, dict) and set(structured) == {"result"}:
        return structured["result"]
    if structured is not None:
        return structured
    return json.loads("".join(item.text for item in result.content if hasattr(item, "text")))


def error_text(result: CallToolResult) -> str:
    assert result.is_error, result.content
    return "".join(item.text for item in result.content if hasattr(item, "text"))


async def raw_mcp_post(
    app: Any, headers: dict[str, str] | None = None, host: str = "localhost"
) -> Any:
    """POST an MCP `initialize` request without a client session."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    request_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Host": host,
    }
    request_headers.update(headers or {})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as client:
        return await client.post("/mcp", json=body, headers=request_headers)


# Tasks that legitimately outlive `Server.serve()` and are cancelled when the
# server thread's event loop is torn down: sse-starlette runs exactly one
# shutdown watcher per event loop.
_ALLOWED_LEFTOVER_TASKS = {"_shutdown_watcher"}


class UvicornThread:
    """Runs a uvicorn server (lifespan on) in a thread and proves it stops.

    `stop()` requests shutdown, joins the thread, and then verifies that the
    thread ended, its event loop is closed, and that no unexpected task was
    still pending when the server returned. On a hang it fails with the
    server's own state and the stuck tasks instead of just timing out.

    The server thread runs a selector event loop: on Windows' default Proactor
    loop under Python 3.12, `Server.shutdown()` can block forever in
    `asyncio.Server.wait_closed()` (transports of already-closed client
    connections are never detached) before uvicorn ever sends
    `lifespan.shutdown`, even though uvicorn reports zero open connections.
    """

    def __init__(
        self,
        app: Any,
        port: int,
        loop_factory: Callable[[], asyncio.AbstractEventLoop] = asyncio.SelectorEventLoop,
    ) -> None:
        self.port = port
        self._loop_factory = loop_factory
        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on", log_level="warning")
        )
        self.loop: asyncio.AbstractEventLoop | None = None
        self.leftover_tasks: list[str] = []
        self._thread = threading.Thread(target=self._run, name=f"uvicorn-{port}", daemon=True)

    def _run(self) -> None:
        loop = self._loop_factory()
        self.loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.server.serve())
        finally:
            pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
            self.leftover_tasks = [t.get_coro().__name__ for t in pending]  # type: ignore[union-attr]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def start(self, timeout: float = 15.0) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            assert self._thread.is_alive(), "uvicorn thread died during startup"
            assert time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.02)

    def _diagnostics(self) -> str:
        server = self.server
        lines = [
            f"should_exit={server.should_exit} lifespan.should_exit={server.lifespan.should_exit}",
            f"uvicorn connections={len(server.server_state.connections)} "
            f"tasks={len(server.server_state.tasks)}",
        ]
        if self.loop is not None:
            for task in asyncio.all_tasks(self.loop):
                lines.append(f"pending task: {task.get_name()} {task.get_coro()!r}")
        return "\n".join(lines)

    def stop(self, timeout: float = 15.0) -> None:
        self.server.should_exit = True
        self._thread.join(timeout=timeout)
        assert not self._thread.is_alive(), (
            "uvicorn did not shut down:\n" + self._diagnostics()
        )
        assert self.loop is not None and self.loop.is_closed()
        unexpected = [n for n in self.leftover_tasks if n not in _ALLOWED_LEFTOVER_TASKS]
        assert unexpected == [], f"tasks still pending at server exit: {unexpected}"
