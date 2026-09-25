import pytest
from django.test import Client


@pytest.mark.django_db
def test_graphql_cookie_request_without_csrf_token_is_rejected() -> None:
    response = Client(enforce_csrf_checks=True).post(
        "/graphql/",
        {"query": "query { me { id } }"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_graphql_bearer_request_reaches_token_authentication_without_csrf_cookie() -> None:
    response = Client(enforce_csrf_checks=True).post(
        "/graphql/",
        {"query": "query { me { id } }"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer invalid-token",
    )

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="kinetiq-v"'
