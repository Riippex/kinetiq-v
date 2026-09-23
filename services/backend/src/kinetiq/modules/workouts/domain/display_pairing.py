import threading
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


class DisplayPairingContention(DisplayPairingError):
    """Raised when a pairing could not be committed because the code kept
    changing under concurrent requests."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Display pairing code '{code}' is being updated concurrently; retry")
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
    # Optimistic-concurrency token: incremented by every committed change, so
    # a claim is only applied if nobody else changed the code since it was read.
    version: int = 0

    def is_expired(self, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(UTC)
        return current_time > self.expires_at


class DisplayPairingStore(Protocol):
    def get(self, code: str) -> DisplayPairingCode | None: ...

    def create_if_absent(self, pairing: DisplayPairingCode) -> bool:
        """Atomically store a new code; False if the code already exists."""
        ...

    def compare_and_save(self, *, expected_version: int, pairing: DisplayPairingCode) -> bool:
        """Atomically replace the stored code only if its version is still
        `expected_version`; False if it changed or no longer exists."""
        ...


class InMemoryDisplayPairingStore:
    """Process-local store for unit tests and single-process development."""

    def __init__(self) -> None:
        self._store: dict[str, DisplayPairingCode] = {}
        self._lock = threading.Lock()

    def get(self, code: str) -> DisplayPairingCode | None:
        with self._lock:
            return self._store.get(code)

    def create_if_absent(self, pairing: DisplayPairingCode) -> bool:
        with self._lock:
            if pairing.code in self._store:
                return False
            self._store[pairing.code] = pairing
            return True

    def compare_and_save(self, *, expected_version: int, pairing: DisplayPairingCode) -> bool:
        with self._lock:
            current = self._store.get(pairing.code)
            if current is None or current.version != expected_version:
                return False
            self._store[pairing.code] = pairing
            return True
