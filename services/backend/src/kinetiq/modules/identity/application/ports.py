from typing import Protocol
from uuid import UUID


class SubjectDirectory(Protocol):
    """Maps an identity-provider subject (`sub`) to a local user."""

    def active_user_id_for_subject(self, subject: str) -> UUID | None:
        """Return the local user id for an active user, or None."""
