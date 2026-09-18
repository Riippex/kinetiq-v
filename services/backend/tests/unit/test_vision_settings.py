import pytest
from django.core.exceptions import ImproperlyConfigured

from kinetiq.bootstrap.vision_settings import VisionSettings, resolve_vision_settings


def test_resolve_vision_settings_accepts_valid_values() -> None:
    result = resolve_vision_settings(
        base_url="https://vision.internal:8443",
        timeout_seconds_raw="7.5",
        service_credential="secret-token",
    )
    assert result == VisionSettings(
        base_url="https://vision.internal:8443",
        timeout_seconds=7.5,
        service_credential="secret-token",
    )


def test_resolve_vision_settings_allows_empty_credential() -> None:
    result = resolve_vision_settings(
        base_url="http://127.0.0.1:8001",
        timeout_seconds_raw="5.0",
        service_credential="",
    )
    assert result.service_credential == ""


@pytest.mark.parametrize(
    "base_url",
    ["127.0.0.1:8001", "ftp://vision.internal", "", "  "],
)
def test_resolve_vision_settings_rejects_non_http_base_url(base_url: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="VISION_BASE_URL"):
        resolve_vision_settings(
            base_url=base_url, timeout_seconds_raw="5.0", service_credential=""
        )


def test_resolve_vision_settings_rejects_non_numeric_timeout() -> None:
    with pytest.raises(ImproperlyConfigured, match="VISION_TIMEOUT_SECONDS"):
        resolve_vision_settings(
            base_url="http://127.0.0.1:8001",
            timeout_seconds_raw="not-a-number",
            service_credential="",
        )


@pytest.mark.parametrize("timeout_raw", ["0", "-1.0", "-5"])
def test_resolve_vision_settings_rejects_non_positive_timeout(timeout_raw: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="VISION_TIMEOUT_SECONDS"):
        resolve_vision_settings(
            base_url="http://127.0.0.1:8001",
            timeout_seconds_raw=timeout_raw,
            service_credential="",
        )


def test_container_wires_vision_adapter_from_settings(settings) -> None:
    settings.VISION_BASE_URL = "https://vision.example.internal"
    settings.VISION_TIMEOUT_SECONDS = 12.5
    settings.VISION_SERVICE_CREDENTIAL = "test-service-token"

    from kinetiq.bootstrap.container import get_vision_rest_adapter

    adapter = get_vision_rest_adapter()

    assert adapter.config.base_url == "https://vision.example.internal"
    assert adapter.config.timeout_seconds == 12.5
    assert adapter.config.default_headers.get("Authorization") == "Bearer test-service-token"


@pytest.mark.django_db
def test_container_wires_vision_adapter_without_credential_header(settings) -> None:
    settings.VISION_SERVICE_CREDENTIAL = ""

    from kinetiq.bootstrap.container import get_vision_rest_adapter

    adapter = get_vision_rest_adapter()

    assert "Authorization" not in adapter.config.default_headers
