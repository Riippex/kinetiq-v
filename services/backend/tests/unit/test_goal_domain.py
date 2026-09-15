from datetime import UTC, datetime
from uuid import uuid4

import pytest

from kinetiq.modules.goals.application import (
    GetActiveGoalUseCase,
    GoalRepository,
    ListGoalRevisionsUseCase,
    SetGoalCommand,
    SetGoalUseCase,
)
from kinetiq.modules.goals.domain import GoalRevision


class InMemoryGoalRepository(GoalRepository):
    def __init__(self) -> None:
        self.revisions: list[GoalRevision] = []

    def get_active_goal(self, owner_id):
        user_revs = [r for r in self.revisions if r.owner_id == owner_id]
        if not user_revs:
            return None
        return sorted(user_revs, key=lambda r: r.revision, reverse=True)[0]

    def list_revisions(self, owner_id):
        user_revs = [r for r in self.revisions if r.owner_id == owner_id]
        return sorted(user_revs, key=lambda r: r.revision, reverse=True)

    def save_revision(self, revision: GoalRevision) -> None:
        self.revisions.append(revision)


def test_goal_revision_invariants() -> None:
    owner_id = uuid4()
    goal_id = uuid4()
    now = datetime.now(UTC)

    # Empty description rejected
    with pytest.raises(ValueError, match="description cannot be empty"):
        GoalRevision(
            id=uuid4(),
            owner_id=owner_id,
            goal_id=goal_id,
            revision=1,
            description="",
            measure="sessions",
            baseline=0.0,
            target=3.0,
            unit="sessions/week",
            created_at=now,
        )

    # Target must be strictly greater than baseline
    with pytest.raises(ValueError, match="strictly greater than baseline"):
        GoalRevision(
            id=uuid4(),
            owner_id=owner_id,
            goal_id=goal_id,
            revision=1,
            description="Consistency",
            measure="sessions",
            baseline=3.0,
            target=2.0,
            unit="sessions/week",
            created_at=now,
        )


def test_set_goal_increments_revision_and_preserves_history() -> None:
    repo = InMemoryGoalRepository()
    set_use_case = SetGoalUseCase(repo)
    get_active_use_case = GetActiveGoalUseCase(repo)
    list_use_case = ListGoalRevisionsUseCase(repo)
    owner_id = uuid4()

    # 1. First goal set -> revision 1
    rev1 = set_use_case.execute(
        owner_id,
        SetGoalCommand(
            description="Exercise 3 times a week",
            measure="weekly_completed_sessions",
            baseline=0.0,
            target=3.0,
            unit="sessions/week",
        ),
    )
    assert rev1.revision == 1
    assert rev1.description == "Exercise 3 times a week"

    # 2. Second goal set -> revision 2, same goal_id
    rev2 = set_use_case.execute(
        owner_id,
        SetGoalCommand(
            description="Exercise 4 times a week",
            measure="weekly_completed_sessions",
            baseline=3.0,
            target=4.0,
            unit="sessions/week",
        ),
    )
    assert rev2.revision == 2
    assert rev2.goal_id == rev1.goal_id
    assert rev2.description == "Exercise 4 times a week"

    # Active goal is revision 2
    active = get_active_use_case.execute(owner_id)
    assert active is not None
    assert active.revision == 2
    assert active.description == "Exercise 4 times a week"

    # Historical revisions list retains BOTH revisions (history preserved!)
    all_revisions = list_use_case.execute(owner_id)
    assert len(all_revisions) == 2
    assert all_revisions[0].revision == 2
    assert all_revisions[1].revision == 1
