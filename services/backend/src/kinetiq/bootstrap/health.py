import ipaddress
import socket
from collections.abc import Callable, Iterable

from django.http import HttpRequest, HttpResponse, JsonResponse

GetResponse = Callable[[HttpRequest], HttpResponse]


def resolve_local_ipv4_addresses() -> frozenset[str]:
    """Return only IPv4 addresses assigned to the current runtime host."""
    try:
        addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return frozenset()
    return normalize_ipv4_addresses(addresses)


def normalize_ipv4_addresses(addresses: Iterable[str]) -> frozenset[str]:
    valid: set[str] = set()
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        if isinstance(parsed, ipaddress.IPv4Address):
            valid.add(str(parsed))
    return frozenset(valid)


def host_without_port(raw_host: str) -> str:
    host, separator, port = raw_host.rpartition(":")
    if separator and port.isdigit():
        return host
    return raw_host


class InternalHealthCheckMiddleware:
    """Answer ALB health checks without weakening Django host validation.

    The ECS task security group accepts port 8000 only from the ALB security
    group. ALB health checks use the task's private IP as the Host header, so
    this middleware accepts that exact runtime IP only for `/health/`.
    """

    def __init__(
        self,
        get_response: GetResponse,
        *,
        local_addresses: frozenset[str] | None = None,
    ) -> None:
        self._get_response = get_response
        self._local_addresses = (
            local_addresses if local_addresses is not None else resolve_local_ipv4_addresses()
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raw_host = request.META.get("HTTP_HOST", "")
        if request.path == "/health/" and host_without_port(raw_host) in self._local_addresses:
            return JsonResponse({"service": "kinetiq-backend", "status": "ok"})
        return self._get_response(request)
