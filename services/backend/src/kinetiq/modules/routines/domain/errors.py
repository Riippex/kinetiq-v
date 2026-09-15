from __future__ import annotations


class RoutineDomainError(Exception):
    """Base exception for routine domain operations."""


class NoEligibleRoutineTemplatesError(RoutineDomainError):
    """Raised when no catalog templates meet the athlete's eligibility constraints."""


class InvalidCoachingOutputError(RoutineDomainError):
    """Raised when a coaching provider returns an unapproved template or invalid format."""
