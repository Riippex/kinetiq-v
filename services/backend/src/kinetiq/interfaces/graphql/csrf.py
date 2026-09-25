from __future__ import annotations

from typing import Any

from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import CsrfViewMiddleware


class GraphQLBearerAwareCsrfMiddleware(CsrfViewMiddleware):
    """Keep cookie CSRF checks while allowing token-authenticated GraphQL clients.

    Cognito bearer tokens are explicit, non-cookie credentials. Their signature and
    claims are validated by ``CognitoBearerAuthenticationMiddleware`` before any
    GraphQL resolver runs. Malformed or invalid bearer credentials still fail with
    HTTP 401 there; requests that rely on a browser session remain CSRF protected.
    """

    def process_view(
        self,
        request: HttpRequest,
        callback: Any,
        callback_args: tuple[Any, ...],
        callback_kwargs: dict[str, Any],
    ) -> HttpResponse | None:
        if _is_graphql_bearer_request(request):
            return None
        return super().process_view(request, callback, callback_args, callback_kwargs)


def _is_graphql_bearer_request(request: HttpRequest) -> bool:
    if request.path.rstrip("/") != "/graphql":
        return False

    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    return separator == " " and scheme.lower() == "bearer" and bool(token.strip())
