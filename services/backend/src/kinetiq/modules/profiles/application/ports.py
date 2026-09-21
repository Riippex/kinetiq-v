from __future__ import annotations

from typing import Protocol
from uuid import UUID

from kinetiq.modules.profiles.domain.entities import UserProfile


class ProfileRepository(Protocol):
    def get_by_owner_id(self, owner_id: UUID) -> UserProfile | None: ...

    def save(self, profile: UserProfile) -> None: ...
