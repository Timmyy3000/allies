"""Typed, provider-neutral failures used by lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Mapping

from runtime.exceptions import RuntimeDomainError

_SAFE_DETAIL_KEYS = frozenset(
    {"resource_type", "resource_id", "status", "retry_after", "region", "reason"}
)


class ProviderError(RuntimeDomainError):
    """Base error with retry and side-effect uncertainty made explicit."""

    code = "provider_error"
    retryable = False
    uncertain = False

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        status_code: int | None = None,
        retryable: bool | None = None,
        uncertain: bool | None = None,
        details: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable
        if uncertain is not None:
            self.uncertain = uncertain
        # Provider response bodies are intentionally not retained.  Keep only
        # a small allow-list of non-sensitive diagnostics for operational
        # evidence; credentials, headers, and arbitrary payload keys never
        # cross this boundary.
        self.details = {
            key: value
            for key, value in (details or {}).items()
            if key in _SAFE_DETAIL_KEYS
        }


class ProviderRetryableError(ProviderError):
    code = "provider_retryable"
    retryable = True


class ProviderTerminalError(ProviderError):
    code = "provider_terminal"
    retryable = False


class ProviderProtocolError(ProviderTerminalError):
    code = "provider_protocol"


class ProviderInvalidConfigurationError(ProviderTerminalError):
    """The provider rejected a request that cannot succeed unchanged."""

    code = "invalid_configuration"


class ProviderTimeoutError(ProviderRetryableError):
    code = "provider_timeout"
    uncertain = True


class ProviderCapacityError(ProviderRetryableError):
    code = "provider_capacity"


class ProviderRateLimitError(ProviderRetryableError):
    code = "provider_rate_limited"


class ProviderConflictError(ProviderTerminalError):
    code = "provider_conflict"


class ProviderAttachmentConflictError(ProviderConflictError):
    code = "volume_attachment_conflict"

    def __init__(
        self,
        message: str = "volume is attached to another Machine",
        *,
        volume_id: str | None = None,
        attached_machine_id: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(message, **kwargs)
        self.volume_id = volume_id
        self.attached_machine_id = attached_machine_id


class ProviderNotFoundError(ProviderTerminalError):
    code = "provider_not_found"


class ProviderUnauthorizedError(ProviderTerminalError):
    code = "provider_unauthorized"


class ProviderOwnershipError(ProviderTerminalError):
    code = "provider_ownership"


class ProviderUnsupportedTopologyError(ProviderTerminalError):
    code = "unsupported_topology"


# Readable aliases for callers that refer to these as failures rather than
# errors.  Keeping one implementation avoids parallel exception hierarchies
# at the provider/lifecycle seam.
ProviderFailure = ProviderError
RetryableProviderError = ProviderRetryableError
TerminalProviderError = ProviderTerminalError
AttachmentConflictError = ProviderAttachmentConflictError
InvalidConfigurationError = ProviderInvalidConfigurationError
OwnershipError = ProviderOwnershipError
RateLimitError = ProviderRateLimitError


__all__ = [
    "AttachmentConflictError",
    "InvalidConfigurationError",
    "OwnershipError",
    "ProviderAttachmentConflictError",
    "ProviderCapacityError",
    "ProviderConflictError",
    "ProviderError",
    "ProviderFailure",
    "ProviderInvalidConfigurationError",
    "ProviderNotFoundError",
    "ProviderOwnershipError",
    "ProviderProtocolError",
    "ProviderRateLimitError",
    "ProviderRetryableError",
    "ProviderTerminalError",
    "ProviderTimeoutError",
    "ProviderUnauthorizedError",
    "ProviderUnsupportedTopologyError",
    "RateLimitError",
    "RetryableProviderError",
    "TerminalProviderError",
]
