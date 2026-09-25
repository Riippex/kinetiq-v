from django.http import HttpResponse
from django.test import RequestFactory

from kinetiq.bootstrap.health import (
    InternalHealthCheckMiddleware,
    host_without_port,
    normalize_ipv4_addresses,
)


def test_internal_task_ip_health_check_bypasses_normal_request_stack() -> None:
    request = RequestFactory().get("/health/", HTTP_HOST="10.0.12.152:8000")
    middleware = InternalHealthCheckMiddleware(
        lambda _: HttpResponse(status=418),
        local_addresses=frozenset({"10.0.12.152"}),
    )

    response = middleware(request)

    assert response.status_code == 200
    assert response.content == b'{"service": "kinetiq-backend", "status": "ok"}'


def test_public_health_check_continues_through_normal_request_stack() -> None:
    request = RequestFactory().get("/health/", HTTP_HOST="kinetiqv.rafaelpatinodiaz.com")
    middleware = InternalHealthCheckMiddleware(
        lambda _: HttpResponse(status=204),
        local_addresses=frozenset({"10.0.12.152"}),
    )

    assert middleware(request).status_code == 204


def test_internal_task_ip_does_not_bypass_other_routes() -> None:
    request = RequestFactory().get("/graphql/", HTTP_HOST="10.0.12.152:8000")
    middleware = InternalHealthCheckMiddleware(
        lambda _: HttpResponse(status=418),
        local_addresses=frozenset({"10.0.12.152"}),
    )

    assert middleware(request).status_code == 418


def test_only_valid_ipv4_addresses_are_trusted() -> None:
    assert normalize_ipv4_addresses(
        ["10.0.12.152", "10.0.12.152", "::1", "not-an-address"]
    ) == frozenset({"10.0.12.152"})


def test_host_port_is_removed_only_for_numeric_ports() -> None:
    assert host_without_port("10.0.12.152:8000") == "10.0.12.152"
    assert host_without_port("kinetiq.example") == "kinetiq.example"
    assert host_without_port("kinetiq.example:not-a-port") == "kinetiq.example:not-a-port"
