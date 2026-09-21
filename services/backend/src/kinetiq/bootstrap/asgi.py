import os
from typing import Any

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
from django.urls import re_path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kinetiq.bootstrap.settings")

# get_asgi_application() runs django.setup() as a side effect; anything that
# imports Django models/ORM (the GraphQL schema, transitively) must be
# imported only after this call.
django_asgi_app = get_asgi_application()

from kinetiq.interfaces.graphql.schema import schema  # noqa: E402
from kinetiq.interfaces.graphql.websocket import AuthenticatedGraphQLWSConsumer  # noqa: E402
from kinetiq.interfaces.mcp import create_mcp_asgi_app  # noqa: E402

# The MCP app owns its session manager through the standard ASGI lifespan
# protocol: run this module under an ASGI server that speaks lifespan (uvicorn).
mcp_asgi_app = create_mcp_asgi_app(path="/mcp")

_MCP_PATHS = ("/mcp", "/.well-known/oauth-protected-resource/mcp")


async def http_dispatcher(scope: Any, receive: Any, send: Any) -> None:
    path = scope.get("path", "")
    if any(path == mcp_path or path.startswith(f"{mcp_path}/") for mcp_path in _MCP_PATHS):
        await mcp_asgi_app(scope, receive, send)
    else:
        await django_asgi_app(scope, receive, send)


_protocol_router = ProtocolTypeRouter(
    {
        "http": http_dispatcher,
        # AllowedHostsOriginValidator rejects the WebSocket handshake
        # outright (before AuthMiddlewareStack or the consumer ever run)
        # unless the connection's Origin header matches ALLOWED_HOSTS --
        # the same setting that already bounds which Host header HTTP
        # requests accept, reused here rather than introducing a second,
        # separately-maintained allow-list. Without this, any origin could
        # open a WebSocket to this endpoint and ride the browser's session
        # cookie cross-site (the WebSocket handshake is not subject to the
        # same-origin policy the way a fetch() is).
        #
        # AuthMiddlewareStack resolves scope["user"] from the connection's
        # session cookie, the same way Django's synchronous auth
        # middleware does for HTTP -- so authenticated queries, mutations,
        # and subscriptions (transientSessionUpdates) all see a real user
        # over this transport rather than treating every connection as
        # anonymous. See AuthenticatedGraphQLWSConsumer for how that user
        # reaches _authenticated_owner_id. This transport is cookie-only:
        # there is no bearer-token/connection_init-payload authentication
        # path, matching the rest of this Django app.
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(
                    [
                        re_path(
                            r"^graphql/?$",
                            AuthenticatedGraphQLWSConsumer.as_asgi(schema=schema),
                        ),
                    ]
                )
            )
        ),
    }
)


async def application(scope: Any, receive: Any, send: Any) -> None:
    if scope["type"] == "lifespan":
        # Startup/shutdown drive the MCP session manager (and only it).
        await mcp_asgi_app(scope, receive, send)
    else:
        await _protocol_router(scope, receive, send)
