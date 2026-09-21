"""Real-concurrency evidence for the MCP idempotency ledger.

Must run against a real PostgreSQL server:

    DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres \\
        uv run pytest tests/postgres -q

Each worker thread uses its own database connection. The threads are released
together by a barrier, and the winning request holds its transaction open
while it performs a real product effect, so the other requests reach the
unique-constraint race path (INSERT blocks on the uncommitted receipt and then
fails with an IntegrityError). SQLite cannot show this: it serializes writers
at the database level and gives each thread's in-memory connection an
independent database, so the suite skips these tests unless PostgreSQL is the
configured backend. In the default (SQLite) suite there is therefore NO real
concurrency verification of the ledger.
"""

import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import connection, connections

from kinetiq.bootstrap.container import set_goal
from kinetiq.modules.goals.application import SetGoalCommand
from kinetiq.modules.goals.infrastructure.models import GoalRevisionRecord
from kinetiq.modules.identity.infrastructure.models import User
from kinetiq.modules.integrations.application import (
    IdempotencyConflictError,
    IdempotentToolRunner,
)
from kinetiq.modules.integrations.infrastructure.models import McpToolReceipt
from kinetiq.modules.integrations.infrastructure.receipt_store import DjangoToolReceiptStore

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason=(
        "Real concurrent unique-constraint evidence requires PostgreSQL; run with "
        "DJANGO_SETTINGS_MODULE=kinetiq.bootstrap.test_settings_postgres"
    ),
)

WORKERS = 6
HOLD_TRANSACTION_SECONDS = 0.4


class RaceObservingStore(DjangoToolReceiptStore):
    """Counts how many requests lost the unique-constraint race and replayed."""

    def __init__(self) -> None:
        self.race_replays = 0
        self._lock = threading.Lock()

    def _replay_after_race(
        self, owner_id: UUID, tool: str, key: str, request_fingerprint: str
    ) -> dict[str, Any]:
        with self._lock:
            self.race_replays += 1
        return super()._replay_after_race(owner_id, tool, key, request_fingerprint)


def _run_parallel(
    calls: list[Callable[[], object]],
) -> list[object | BaseException]:
    """Run each call on its own thread and database connection, all released at once."""
    barrier = threading.Barrier(len(calls))
    outcomes: list[object | BaseException] = [None] * len(calls)
    thread_connections: set[int] = set()
    guard = threading.Lock()

    def worker(index: int) -> None:
        try:
            with guard:
                thread_connections.add(id(connections["default"]))
            barrier.wait(timeout=10)
            outcomes[index] = calls[index]()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcomes[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "a worker thread is still running"
    assert len(thread_connections) == len(calls), "workers did not use separate connections"
    return outcomes


def _goal_effect(owner_id: UUID, description: str) -> Callable[[], dict[str, Any]]:
    def effect() -> dict[str, Any]:
        goal = set_goal().execute(owner_id, SetGoalCommand(description=description))
        time.sleep(HOLD_TRANSACTION_SECONDS)  # keep the winner's transaction open
        return {"goal_id": str(goal.goal_id), "description": goal.description}

    return effect


@pytest.mark.django_db(transaction=True)
def test_parallel_identical_requests_have_exactly_one_effect_via_the_unique_constraint() -> None:
    owner = User.objects.create_user(username=f"receipt-race-{uuid4().hex[:8]}")
    store = RaceObservingStore()
    runner = IdempotentToolRunner(store)
    executed = 0
    executed_lock = threading.Lock()

    def make_call() -> Callable[[], object]:
        effect = _goal_effect(owner.id, "Race goal")

        def counted_effect() -> dict[str, Any]:
            nonlocal executed
            with executed_lock:
                executed += 1
            return effect()

        return lambda: runner.run(
            owner_id=owner.id,
            tool="set_goal",
            key="race-key",
            payload={"description": "Race goal"},
            effect=counted_effect,
        )

    outcomes = _run_parallel([make_call() for _ in range(WORKERS)])

    errors = [o for o in outcomes if isinstance(o, BaseException)]
    assert errors == [], errors
    assert executed == 1, "the effect must run exactly once"
    assert len({str(o) for o in outcomes}) == 1, "every caller sees the same response"
    assert GoalRevisionRecord.objects.filter(owner_id=owner.id).count() == 1
    assert McpToolReceipt.objects.filter(owner_id=owner.id, key="race-key").count() == 1
    # The race path was actually taken: other requests passed the initial
    # lookup, lost the INSERT on the unique constraint, and replayed.
    assert store.race_replays >= 1


@pytest.mark.django_db(transaction=True)
def test_parallel_requests_reusing_a_key_with_different_payloads_conflict() -> None:
    owner = User.objects.create_user(username=f"receipt-conflict-{uuid4().hex[:8]}")
    store = RaceObservingStore()
    runner = IdempotentToolRunner(store)

    def make_call(description: str) -> Callable[[], object]:
        return lambda: runner.run(
            owner_id=owner.id,
            tool="set_goal",
            key="shared-race-key",
            payload={"description": description},
            effect=_goal_effect(owner.id, description),
        )

    outcomes = _run_parallel([make_call(f"Goal {i}") for i in range(WORKERS)])

    winners = [o for o in outcomes if isinstance(o, dict)]
    conflicts = [o for o in outcomes if isinstance(o, IdempotencyConflictError)]
    assert len(winners) == 1, outcomes
    assert len(conflicts) == WORKERS - 1, outcomes
    assert GoalRevisionRecord.objects.filter(owner_id=owner.id).count() == 1
    assert McpToolReceipt.objects.filter(owner_id=owner.id).count() == 1


@pytest.mark.django_db(transaction=True)
def test_effect_failure_rolls_back_the_claim_so_a_retry_can_run() -> None:
    owner = User.objects.create_user(username=f"receipt-rollback-{uuid4().hex[:8]}")
    runner = IdempotentToolRunner(DjangoToolReceiptStore())

    def failing_effect() -> dict[str, Any]:
        set_goal().execute(owner.id, SetGoalCommand(description="Doomed goal"))
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        runner.run(
            owner_id=owner.id, tool="set_goal", key="retry-key",
            payload={"description": "Doomed goal"}, effect=failing_effect,
        )
    assert GoalRevisionRecord.objects.filter(owner_id=owner.id).count() == 0
    assert McpToolReceipt.objects.filter(owner_id=owner.id).count() == 0

    result = runner.run(
        owner_id=owner.id, tool="set_goal", key="retry-key",
        payload={"description": "Doomed goal"}, effect=_goal_effect(owner.id, "Doomed goal"),
    )
    assert result["description"] == "Doomed goal"
    assert GoalRevisionRecord.objects.filter(owner_id=owner.id).count() == 1
