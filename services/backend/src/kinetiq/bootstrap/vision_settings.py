from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True, slots=True)
class VisionSettings:
    base_url: str
    timeout_seconds: float
    service_credential: str


def resolve_vision_settings(
    *, base_url: str, timeout_seconds_raw: str, service_credential: str
) -> VisionSettings:
    """Validate raw Vision client environment values and return typed
    settings. Extracted from bootstrap/settings.py so the validation itself
    is directly unit-testable without reloading the Django settings module.
    Raises `ImproperlyConfigured` (Django's standard fail-fast exception)
    for any invalid value.
    """
    if not base_url.startswith(("http://", "https://")):
        raise ImproperlyConfigured(f"VISION_BASE_URL must be an http(s) URL, got: {base_url!r}")

    try:
        timeout_seconds = float(timeout_seconds_raw)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"VISION_TIMEOUT_SECONDS must be a number, got: {timeout_seconds_raw!r}"
        ) from exc
    if timeout_seconds <= 0:
        raise ImproperlyConfigured(
            f"VISION_TIMEOUT_SECONDS must be positive, got: {timeout_seconds}"
        )

    return VisionSettings(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        service_credential=service_credential,
    )
