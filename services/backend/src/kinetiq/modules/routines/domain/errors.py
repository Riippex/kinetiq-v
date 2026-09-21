from __future__ import annotations


class RoutineDomainError(Exception):
    """Base exception for routine domain operations."""


class NoEligibleRoutineTemplatesError(RoutineDomainError):
    """Raised when no catalog templates meet the athlete's eligibility constraints."""


class UnsupportedLimitationError(RoutineDomainError):
    """Raised when the catalog has no explicitly supported adaptation for a
    self-reported athlete limitation, so no safe routine can be proposed or edited."""


class InvalidCoachingOutputError(RoutineDomainError):
    """Raised when a coaching provider returns an unapproved template or invalid format."""


class RoutineNotFoundError(RoutineDomainError):
    """Raised when a requested routine or version does not exist for the athlete."""


class InvalidRoutineEditError(RoutineDomainError):
    """Raised when editing a routine violates catalog invariants or constraints."""
