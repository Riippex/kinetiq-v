from __future__ import annotations

from typing import Protocol
from uuid import UUID

from kinetiq.modules.goals.domain.entities import GoalRevision


class GoalRepository(Protocol):
    def get_active_goal(self, owner_id: UUID) -> GoalRevision | None: ...

    def list_revisions(self, owner_id: UUID) -> list[GoalRevision]: ...

    def save_revision(self, revision: GoalRevision) -> None: ...
