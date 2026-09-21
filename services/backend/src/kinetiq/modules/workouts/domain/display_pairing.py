from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol


class DisplayDeviceType(StrEnum):
    FIRE_TV = "FIRE_TV"
    VEGA_OS = "VEGA_OS"


class DisplayPairingStatus(StrEnum):
    UNPAIRED = "UNPAIRED"
    PAIRED = "PAIRED"
    EXPIRED = "EXPIRED"


class DisplayPairingError(Exception):
    """Base exception for display pairing errors."""


class DisplayPairingCodeNotFound(DisplayPairingError):
    def __init__(self, code: str) -> None:
        super().__init__(f"Display pairing code '{code}' not found")
        self.code = code


class DisplayPairingCodeExpired(DisplayPairingError):
    def __init__(self, code: str) -> None:
        super().__init__(f"Display pairing code '{code}' has expired")
        self.code = code


class DisplayPairingCodePaired(DisplayPairingError):
    """Raised when a code already paired to one owner is presented by a
    different owner. Without this check, a second athlete who observed or
    guessed a live code could re-pair it to their own session and read
    someone else's live workout progress on the display."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Display pairing code '{code}' is already paired to another account")
        self.code = code


@dataclass(frozen=True)
class DisplayPairingCode:
    code: str
    device_type: DisplayDeviceType
    created_at: datetime
    expires_at: datetime
    status: DisplayPairingStatus = DisplayPairingStatus.UNPAIRED
    paired_session_id: str | None = None
    owner_id: str | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        return current_time > self.expires_at


class DisplayPairingStore(Protocol):
    def save(self, pairing: DisplayPairingCode) -> None:
        ...

    def get(self, code: str) -> DisplayPairingCode | None:
        ...


class InMemoryDisplayPairingStore:
    def __init__(self) -> None:
        self._store: dict[str, DisplayPairingCode] = {}

    def save(self, pairing: DisplayPairingCode) -> None:
        self._store[pairing.code] = pairing

    def get(self, code: str) -> DisplayPairingCode | None:
        return self._store.get(code)
