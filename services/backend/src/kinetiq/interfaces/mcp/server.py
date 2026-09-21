from collections.abc import Sequence

from django.conf import settings as django_settings
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from kinetiq.interfaces.mcp.auth import OIDCSettings, OIDCTokenVerifier
from kinetiq.interfaces.mcp.tools import (
    mcp_abandon_session,
    mcp_accept_routine,
    mcp_finish_session,
    mcp_get_active_goal,
    mcp_get_current_routine,
    mcp_get_latest_session,
    mcp_get_profile,
    mcp_get_progress_summary,
    mcp_list_goal_revisions,
    mcp_pause_session,
    mcp_prepare_session,
    mcp_propose_routine,
    mcp_resume_session,
    mcp_set_goal,
    mcp_start_session,
    mcp_update_profile,
)

SERVER_INSTRUCTIONS = (
    "Kinetiq Coach runtime MCP server. Exposes authenticated, user-scoped capabilities "
    "for athlete profiles, goal setting and tracking, routine proposals and immutable versions, "
    "live workout session controls, and consistency/performance progress reviews. "
    "Every mutating tool requires a caller-provided idempotency_key. "
    "Progress photos are not exposed."
)

# Fallback issuer URL used only to satisfy AuthSettings when OIDC is not
# configured; the verifier rejects every token in that case.
_UNCONFIGURED_ISSUER = "https://issuer.invalid"


def oidc_settings_from_django() -> OIDCSettings:
    return OIDCSettings(
        issuer=django_settings.MCP_OIDC_ISSUER,
        audience=django_settings.MCP_OIDC_AUDIENCE,
        jwks_url=django_settings.MCP_OIDC_JWKS_URL
        or (
            f"{django_settings.MCP_OIDC_ISSUER.rstrip('/')}/.well-known/jwks.json"
            if django_settings.MCP_OIDC_ISSUER
            else ""
        ),
        required_scope=django_settings.MCP_OIDC_REQUIRED_SCOPE,
        token_use=django_settings.MCP_OIDC_TOKEN_USE,
    )


def create_mcp_server(
    *, token_verifier: TokenVerifier, auth: AuthSettings
) -> MCPServer:
    """Create a Kinetiq Coach MCP server with all tools.

    A new server (and therefore a new session manager) is created per ASGI
    app instance: a session manager can only be run once.
    """
    server = MCPServer(
        name="kinetiq-coach",
        instructions=SERVER_INSTRUCTIONS,
        token_verifier=token_verifier,
        auth=auth,
    )

    # Profile tools
    server.add_tool(mcp_get_profile, name="get_profile")
    server.add_tool(mcp_update_profile, name="update_profile")

    # Goal tools
    server.add_tool(mcp_get_active_goal, name="get_active_goal")
    server.add_tool(mcp_list_goal_revisions, name="list_goal_revisions")
    server.add_tool(mcp_set_goal, name="set_goal")

    # Routine & Coaching tools
    server.add_tool(mcp_get_current_routine, name="get_current_routine")
    server.add_tool(mcp_propose_routine, name="propose_routine")
    server.add_tool(mcp_accept_routine, name="accept_routine")

    # Session tools
    server.add_tool(mcp_get_latest_session, name="get_latest_session")
    server.add_tool(mcp_prepare_session, name="prepare_session")
    server.add_tool(mcp_start_session, name="start_session")
    server.add_tool(mcp_pause_session, name="pause_session")
    server.add_tool(mcp_resume_session, name="resume_session")
    server.add_tool(mcp_abandon_session, name="abandon_session")
    server.add_tool(mcp_finish_session, name="finish_session")

    # Progress tools
    server.add_tool(mcp_get_progress_summary, name="get_progress_summary")

    return server


def create_mcp_asgi_app(
    path: str = "/mcp",
    *,
    verifier: TokenVerifier | None = None,
    oidc: OIDCSettings | None = None,
    resource_url: str | None = None,
    allowed_hosts: Sequence[str] | None = None,
    allowed_origins: Sequence[str] | None = None,
) -> Starlette:
    """Create the Streamable HTTP ASGI app for the MCP server.

    The returned Starlette app owns the session manager's lifecycle through the
    standard ASGI lifespan protocol: it starts on `lifespan.startup` and stops
    on `lifespan.shutdown`, so the ASGI server (e.g. uvicorn) must run lifespan.

    Bearer authentication runs in the transport, before any tool executes;
    DNS-rebinding protection validates the Host and Origin headers.
    """
    oidc = oidc or oidc_settings_from_django()
    verifier = verifier or OIDCTokenVerifier(oidc)
    auth = AuthSettings(
        issuer_url=oidc.issuer or _UNCONFIGURED_ISSUER,  # type: ignore[arg-type]
        resource_server_url=resource_url or django_settings.MCP_RESOURCE_URL,  # type: ignore[arg-type]
        required_scopes=[oidc.required_scope],
        # The verifier checks the token's audience itself.
        validate_token_resource=False,
    )
    server = create_mcp_server(token_verifier=verifier, auth=auth)
    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(
            allowed_hosts if allowed_hosts is not None else django_settings.MCP_ALLOWED_HOSTS
        ),
        allowed_origins=list(
            allowed_origins if allowed_origins is not None else django_settings.MCP_ALLOWED_ORIGINS
        ),
    )
    return server.streamable_http_app(
        streamable_http_path=path,
        transport_security=transport_security,
    )
