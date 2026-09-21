from __future__ import annotations

from typing import Protocol
from uuid import UUID

from kinetiq.modules.routines.domain.entities import Routine


class RoutineRepository(Protocol):
    def save(self, routine: Routine) -> None: ...

    def get_by_id(self, record_id: UUID) -> Routine | None: ...

    def get_by_routine_id(
        self, owner_id: UUID, routine_id: UUID, version: int
    ) -> Routine | None: ...

    def get_latest_for_owner(self, owner_id: UUID) -> Routine | None: ...

    def get_active_accepted(self, owner_id: UUID) -> Routine | None: ...

    def list_for_owner(self, owner_id: UUID) -> list[Routine]: ...
