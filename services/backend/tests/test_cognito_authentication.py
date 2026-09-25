import json
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpRequest, JsonResponse
from django.test import RequestFactory

from kinetiq.modules.identity.infrastructure.cognito_auth import (
    CognitoBearerAuthenticationMiddleware,
)


class StubVerifier:
    def __init__(self, claims: dict[str, Any] | None) -> None:
        self.claims = claims

    def verify(self, token: str) -> dict[str, Any] | None:
        return self.claims if token == "valid-token" else None


def _authenticated_response(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "authenticated": request.user.is_authenticated,
            "subject": getattr(request.user, "cognito_subject", None),
        }
    )


@pytest.mark.django_db
def test_valid_bearer_token_provisions_and_authenticates_local_user() -> None:
    middleware = CognitoBearerAuthenticationMiddleware(
        _authenticated_response,
        verifier=StubVerifier({"sub": "cognito-subject-1"}),
    )
    request = RequestFactory().post("/graphql/", HTTP_AUTHORIZATION="Bearer valid-token")

    response = middleware(request)

    assert response.status_code == 200
    assert json.loads(response.content) == {
        "authenticated": True,
        "subject": "cognito-subject-1",
    }
    assert get_user_model().objects.filter(cognito_subject="cognito-subject-1").count() == 1


@pytest.mark.django_db
def test_repeated_token_reuses_the_same_local_user() -> None:
    middleware = CognitoBearerAuthenticationMiddleware(
        _authenticated_response,
        verifier=StubVerifier({"sub": "cognito-subject-1"}),
    )

    middleware(RequestFactory().post("/graphql/", HTTP_AUTHORIZATION="Bearer valid-token"))
    middleware(RequestFactory().post("/graphql/", HTTP_AUTHORIZATION="Bearer valid-token"))

    assert get_user_model().objects.filter(cognito_subject="cognito-subject-1").count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "authorization",
    ["Bearer invalid-token", "Basic abc", "Bearer", "Bearer "],
)
def test_invalid_authorization_is_rejected(authorization: str) -> None:
    middleware = CognitoBearerAuthenticationMiddleware(
        _authenticated_response,
        verifier=StubVerifier(None),
    )
    request = RequestFactory().post("/graphql/", HTTP_AUTHORIZATION=authorization)

    response = middleware(request)

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="kinetiq-v"'


def test_request_without_bearer_token_remains_anonymous() -> None:
    request = RequestFactory().post("/graphql/")
    request.user = type("Anonymous", (), {"is_authenticated": False})()
    middleware = CognitoBearerAuthenticationMiddleware(
        _authenticated_response,
        verifier=StubVerifier(None),
    )

    response = middleware(request)

    assert response.status_code == 200
    assert json.loads(response.content)["authenticated"] is False
