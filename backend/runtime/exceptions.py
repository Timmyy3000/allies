class RuntimeDomainError(Exception):
    """Base exception for internal runtime-domain write failures."""


class RuntimeValidationError(RuntimeDomainError, ValueError):
    """The caller supplied a value outside the domain contract."""


class RuntimeConflictError(RuntimeDomainError):
    """The requested write conflicts with durable runtime state."""


class RuntimeAuthorizationError(RuntimeDomainError):
    """The caller cannot mutate the requested runtime state."""
