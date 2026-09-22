"""Ownership claims on a live display code must be atomic.

These tests force the interleaving that used to break the claim: two owners
both read the code as UNPAIRED before either one commits. They run against the
in-memory store; tests/integration/test_display_pairing_redis.py repeats the
scenario against a real Redis server.
"""

import threading
from uuid import uuid4

import pytest

from kinetiq.modules.workouts.application.display_pairing_use_cases import (
    IssueDisplayPairingCodeUseCase,
    PairDisplayDeviceUseCase,
)
from kinetiq.modules.workouts.domain.display_pairing import (
    DisplayDeviceType,
    DisplayPairingCode,
    DisplayPairingCodePaired,
    DisplayPairingContention,
    DisplayPairingStatus,
    InMemoryDisplayPairingStore,
)


class NoSessionRepo:
    def get_session(self, *, owner_id: object, session_id: object) -> None:
        return None


class ReadBarrierStore(InMemoryDisplayPairingStore):
    """Makes every first `get` wait until all racers have read the code."""

    def __init__(self, racers: int) -> None:
        super().__init__()
        self._barrier = threading.Barrier(racers)
        self._seen = threading.local()
        self.armed = False  # only the racing phase waits on the barrier

    def get(self, code: str) -> DisplayPairingCode | None:
        value = super().get(code)
        if self.armed and not getattr(self._seen, "waited", False):
            self._seen.waited = True
            self._barrier.wait(timeout=10)
        return value


def _race(store: InMemoryDisplayPairingStore, owners: list[str], code: str) -> list[object]:
    use_case = PairDisplayDeviceUseCase(store, NoSessionRepo())  # type: ignore[arg-type]
    outcomes: list[object] = [None] * len(owners)
    if hasattr(store, "armed"):
        store.armed = True

    def worker(index: int) -> None:
        try:
            outcomes[index] = use_case.execute(owners[index], code)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcomes[index] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(owners))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    if hasattr(store, "armed"):
        store.armed = False
    return outcomes


def test_two_owners_reading_unpaired_cannot_both_claim_the_code() -> None:
    store = ReadBarrierStore(racers=2)
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    owner_a, owner_b = str(uuid4()), str(uuid4())

    outcomes = _race(store, [owner_a, owner_b], pairing.code)

    winners = [o for o in outcomes if isinstance(o, DisplayPairingCode)]
    losers = [o for o in outcomes if isinstance(o, DisplayPairingCodePaired)]
    assert len(winners) == 1, outcomes
    assert len(losers) == 1, outcomes
    stored = store.get(pairing.code)
    assert stored is not None
    assert stored.owner_id == winners[0].owner_id
    assert stored.status == DisplayPairingStatus.PAIRED
    assert stored.version == 1  # exactly one committed claim


def test_many_owners_racing_produce_exactly_one_owner() -> None:
    racers = 8
    store = ReadBarrierStore(racers=racers)
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.VEGA_OS)
    owners = [str(uuid4()) for _ in range(racers)]

    outcomes = _race(store, owners, pairing.code)

    winners = [o for o in outcomes if isinstance(o, DisplayPairingCode)]
    assert len(winners) == 1, outcomes
    assert all(isinstance(o, DisplayPairingCodePaired) for o in outcomes if o is not winners[0])
    stored = store.get(pairing.code)
    assert stored is not None and stored.owner_id == winners[0].owner_id


def test_same_owner_racing_with_itself_is_never_rejected() -> None:
    store = ReadBarrierStore(racers=4)
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    owner = str(uuid4())

    outcomes = _race(store, [owner] * 4, pairing.code)

    assert all(isinstance(o, DisplayPairingCode) for o in outcomes), outcomes
    stored = store.get(pairing.code)
    assert stored is not None and stored.owner_id == owner


def test_claim_gives_up_with_contention_error_when_the_code_keeps_changing() -> None:
    class AlwaysLosesStore(InMemoryDisplayPairingStore):
        def compare_and_save(self, *, expected_version: int, pairing: DisplayPairingCode) -> bool:
            return False

    store = AlwaysLosesStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)

    with pytest.raises(DisplayPairingContention):
        PairDisplayDeviceUseCase(store, NoSessionRepo()).execute(  # type: ignore[arg-type]
            str(uuid4()), pairing.code
        )
    assert store.get(pairing.code) == pairing  # nothing was overwritten


def test_issue_retries_when_a_generated_code_already_exists() -> None:
    class CollidingStore(InMemoryDisplayPairingStore):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def create_if_absent(self, pairing: DisplayPairingCode) -> bool:
            self.attempts += 1
            if self.attempts <= 3:
                return False
            return super().create_if_absent(pairing)

    store = CollidingStore()
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)

    assert store.attempts == 4
    assert store.get(pairing.code) == pairing
