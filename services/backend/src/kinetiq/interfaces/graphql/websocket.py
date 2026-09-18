from dataclasses import dataclass
from typing import Any

from strawberry.channels import GraphQLWSConsumer


@dataclass
class ChannelsWebSocketRequest:
    """Minimal stand-in for Django's HttpRequest, exposing exactly the
    attribute _authenticated_owner_id (schema.py) reads: `.user`, as
    populated into the ASGI scope by channels.auth.AuthMiddlewareStack from
    the connection's session cookie."""

    user: Any


@dataclass
class ChannelsWebSocketContext:
    """GraphQL context for a websocket-transported operation, shaped so the
    same `_authenticated_owner_id(info)` helper used by every HTTP query,
    mutation, and the (already-implemented) transientSessionUpdates
    subscription resolver also works unmodified over this transport."""

    request: ChannelsWebSocketRequest


class AuthenticatedGraphQLWSConsumer(GraphQLWSConsumer):
    """Websocket GraphQL consumer wired for Django session authentication.

    strawberry's base GraphQLWSConsumer.get_context() returns a context
    whose "request" is the consumer itself -- useful for accessing the
    raw ASGI scope, but it has no `.user`, so resolvers relying on
    `_authenticated_owner_id` (every query/mutation resolver, and the
    transientSessionUpdates subscription) would treat every websocket
    connection as anonymous. This override instead surfaces
    `self.scope["user"]`, which channels.auth.AuthMiddlewareStack (wired in
    bootstrap/asgi.py) populates from the connection's session cookie --
    the same mechanism Django's synchronous HTTP auth middleware uses, just
    read from the ASGI scope instead of an HttpRequest.
    """

    async def get_context(
        self, request: "AuthenticatedGraphQLWSConsumer", response: "AuthenticatedGraphQLWSConsumer"
    ) -> ChannelsWebSocketContext:
        user = self.scope.get("user")
        return ChannelsWebSocketContext(request=ChannelsWebSocketRequest(user=user))
