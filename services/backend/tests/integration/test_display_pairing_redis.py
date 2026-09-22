"""Display-pairing store and ownership-claim races against a real Redis server.

Run with a reachable Redis (default `redis://127.0.0.1:16379/15`, override
with KINETIQ_TEST_REDIS_URL). The module is skipped, not failed, when no Redis
answers, so without one the default suite has NO real-Redis verification of the
atomic claim. The tests use database 15 and only touch keys under the pairing
prefix.
"""

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import redis

from kinetiq.modules.workouts.application.display_pairing_use_cases import (
    IssueDisplayPairingCodeUseCase,
    PairDisplayDeviceUseCase,
)
from kinetiq.modules.workouts.domain.display_pairing import (
    DisplayDeviceType,
    DisplayPairingCode,
    DisplayPairingCodePaired,
    DisplayPairingStatus,
)
from kinetiq.modules.workouts.infrastructure.display_pairing_store import (
    PAIRING_KEY_PREFIX,
    RedisDisplayPairingStore,
)

REDIS_URL = os.getenv("KINETIQ_TEST_REDIS_URL", "redis://127.0.0.1:16379/15")


def _client() -> "redis.Redis[str]":
    return redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)


def _redis_reachable() -> bool:
    try:
        return bool(_client().ping())
    except redis.RedisError:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(),
    reason=f"a real Redis server is required at {REDIS_URL} (KINETIQ_TEST_REDIS_URL)",
)


@pytest.fixture
def client() -> Iterator["redis.Redis[str]"]:
    conn = _client()

    def cleanup() -> None:
        for key in conn.scan_iter(f"{PAIRING_KEY_PREFIX}*"):
            conn.delete(key)

    cleanup()
    yield conn
    cleanup()


class NoSessionRepo:
    def get_session(self, *, owner_id: object, session_id: object) -> None:
        return None


class ReadBarrierRedisStore(RedisDisplayPairingStore):
    """Real Redis store whose first `get` per thread waits for all racers, so
    every racer has read the code as UNPAIRED before anyone commits."""

    def __init__(self, client: "redis.Redis[Any]", racers: int) -> None:
        super().__init__(client)
        self._barrier = threading.Barrier(racers)
        self._seen = threading.local()
        self.armed = False  # only the racing phase waits on the barrier

    def get(self, code: str) -> DisplayPairingCode | None:
        value = super().get(code)
        if self.armed and not getattr(self._seen, "waited", False):
            self._seen.waited = True
            self._barrier.wait(timeout=10)
        return value


def _race(store: RedisDisplayPairingStore, owners: list[str], code: str) -> list[object]:
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
        thread.join(timeout=20)
        assert not thread.is_alive()
    if hasattr(store, "armed"):
        store.armed = False
    return outcomes


def _new_code() -> DisplayPairingCode:
    now = datetime.now(UTC)
    return DisplayPairingCode(
        code=f"FIRE-{uuid4().hex[:6].upper()}",
        device_type=DisplayDeviceType.FIRE_TV,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )


def test_store_round_trips_and_sets_an_expiry(client: "redis.Redis[str]") -> None:
    store = RedisDisplayPairingStore(client, ttl_seconds=120)
    pairing = _new_code()

    assert store.create_if_absent(pairing) is True
    assert store.get(pairing.code) == pairing
    ttl = client.ttl(f"{PAIRING_KEY_PREFIX}{pairing.code}")
    assert 0 < ttl <= 120


def test_create_if_absent_never_overwrites_an_existing_code(client: "redis.Redis[str]") -> None:
    store = RedisDisplayPairingStore(client)
    pairing = _new_code()
    assert store.create_if_absent(pairing) is True

    other = DisplayPairingCode(
        code=pairing.code,
        device_type=DisplayDeviceType.VEGA_OS,
        created_at=pairing.created_at,
        expires_at=pairing.expires_at,
    )
    assert store.create_if_absent(other) is False
    assert store.get(pairing.code) == pairing


def test_compare_and_save_only_commits_when_the_version_is_unchanged(
    client: "redis.Redis[str]",
) -> None:
    store = RedisDisplayPairingStore(client)
    pairing = _new_code()
    store.create_if_absent(pairing)
    owner = str(uuid4())
    claimed = DisplayPairingCode(
        code=pairing.code,
        device_type=pairing.device_type,
        created_at=pairing.created_at,
        expires_at=pairing.expires_at,
        status=DisplayPairingStatus.PAIRED,
        owner_id=owner,
        version=1,
    )

    assert store.compare_and_save(expected_version=0, pairing=claimed) is True
    # The same stale expectation must now fail, and a missing key never matches.
    assert store.compare_and_save(expected_version=0, pairing=claimed) is False
    missing = DisplayPairingCode(
        code="FIRE-NOPE00",
        device_type=pairing.device_type,
        created_at=pairing.created_at,
        expires_at=pairing.expires_at,
        version=1,
    )
    assert store.compare_and_save(expected_version=0, pairing=missing) is False
    assert store.get(pairing.code) == claimed


def test_racing_owners_on_a_real_redis_produce_exactly_one_owner(
    client: "redis.Redis[str]",
) -> None:
    racers = 8
    store = ReadBarrierRedisStore(client, racers)
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    owners = [str(uuid4()) for _ in range(racers)]

    outcomes = _race(store, owners, pairing.code)

    winners = [o for o in outcomes if isinstance(o, DisplayPairingCode)]
    assert len(winners) == 1, outcomes
    losers = [o for o in outcomes if o is not winners[0]]
    assert all(isinstance(o, DisplayPairingCodePaired) for o in losers), outcomes
    stored = RedisDisplayPairingStore(client).get(pairing.code)
    assert stored is not None
    assert stored.owner_id == winners[0].owner_id
    assert stored.version == 1  # one committed claim, not eight


def test_unforced_parallel_claims_still_yield_one_owner_across_many_rounds(
    client: "redis.Redis[str]",
) -> None:
    for _ in range(25):
        store = RedisDisplayPairingStore(client)
        pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.VEGA_OS)
        owners = [str(uuid4()) for _ in range(6)]

        outcomes = _race(store, owners, pairing.code)

        winners = [o for o in outcomes if isinstance(o, DisplayPairingCode)]
        assert len(winners) == 1, outcomes
        stored = store.get(pairing.code)
        assert stored is not None and stored.owner_id == winners[0].owner_id


def test_same_owner_racing_with_itself_on_a_real_redis_is_never_rejected(
    client: "redis.Redis[str]",
) -> None:
    store = ReadBarrierRedisStore(client, 4)
    pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
    owner = str(uuid4())

    outcomes = _race(store, [owner] * 4, pairing.code)

    assert all(isinstance(o, DisplayPairingCode) for o in outcomes), outcomes
    stored = store.get(pairing.code)
    assert stored is not None and stored.owner_id == owner


def test_concurrent_issuance_never_hands_out_the_same_code_twice(
    client: "redis.Redis[str]",
) -> None:
    store = RedisDisplayPairingStore(client)
    issued: list[str] = []
    guard = threading.Lock()

    def worker() -> None:
        pairing = IssueDisplayPairingCodeUseCase(store).execute(DisplayDeviceType.FIRE_TV)
        with guard:
            issued.append(pairing.code)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert len(issued) == 20 and len(set(issued)) == 20
