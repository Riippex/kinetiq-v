class IdempotencyKeyError(ValueError):
    """The caller-provided idempotency key is missing or malformed."""


class IdempotencyConflictError(Exception):
    """The idempotency key was already used with a different request."""
