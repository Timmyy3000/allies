"""Stable, secret-safe failures at the Hermes boundary."""

from __future__ import annotations


class HermesError(RuntimeError):
    """Base class whose message must never include a bearer value."""

    code = "hermes_error"

    def __init__(self, message: str = "Hermes request failed") -> None:
        # Callers pass short, already-classified messages rather than provider
        # exception text.  This keeps an HTTP client exception from echoing a
        # URL, Authorization header, or response body into evidence.
        super().__init__(message)


class HermesAuthenticationError(HermesError):
    code = "authentication_failed"


class HermesMalformedResponse(HermesError):
    code = "malformed_response"


class HermesDisconnected(HermesError):
    code = "disconnected"


class HermesTimeout(HermesError):
    code = "timeout"


class HermesUnavailable(HermesError):
    code = "unavailable"


class HermesSessionExists(HermesError):
    code = "session_exists"


class IdentityIsolationError(HermesError):
    code = "identity_isolation_failed"


class HermesHistoryMismatch(HermesError):
    code = "history_continuity_failed"


class HermesTranscriptConflict(HermesError):
    code = "transcript_conflict"


__all__ = [
    "HermesAuthenticationError",
    "HermesDisconnected",
    "HermesError",
    "HermesHistoryMismatch",
    "HermesMalformedResponse",
    "HermesSessionExists",
    "HermesTimeout",
    "HermesTranscriptConflict",
    "HermesUnavailable",
    "IdentityIsolationError",
]
