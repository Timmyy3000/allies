class RuntimeDomainError(Exception):
    """Base exception for internal runtime-domain write failures."""

    code = "RUNTIME_ERROR"


class RuntimeValidationError(RuntimeDomainError, ValueError):
    """The caller supplied a value outside the domain contract."""

    code = "INVALID_REQUEST"


class RuntimeConflictError(RuntimeDomainError):
    """The requested write conflicts with durable runtime state."""

    code = "CONFLICT"


class RuntimeAuthorizationError(RuntimeDomainError):
    """The caller cannot mutate the requested runtime state."""

    code = "INVALID_CREDENTIAL"


class RuntimeNotFoundError(RuntimeDomainError):
    """The requested contract binding is not available to this caller."""

    code = "NOT_FOUND"


class RuntimeFencedError(RuntimeConflictError):
    """The authenticated credential belongs to a retired Machine generation."""

    code = "FENCED"


class RuntimeNotReadyError(RuntimeConflictError):
    """The Workspace cannot issue or claim work yet."""

    code = "NOT_READY"


class RuntimeRepairRequiredError(RuntimeConflictError):
    """Durable state needs explicit repair before it can be used again."""

    code = "REPAIR_REQUIRED"


class RuntimeLeaseConflictError(RuntimeConflictError):
    """The lease or attempt does not authorize this operation."""

    code = "LEASE_CONFLICT"


class RuntimeIdempotencyConflictError(RuntimeConflictError):
    """A replay identifier was reused with different content."""

    code = "IDEMPOTENCY_CONFLICT"
