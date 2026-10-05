"""Stable, secret-safe failures at the Hermes boundary."""

from __future__ import annotations

from typing import ClassVar


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


class IncomingFileError(HermesError):
    code = "incoming_file_invalid"


class PublicationInputError(IncomingFileError):
    """Classified local publication input failures safe to show to the user."""

    messages: ClassVar[dict[str, str]] = {
        "invalid_paths": (
            "Use a workspace-relative or contained absolute file path. "
            "Create or copy the file into the current workspace, then try again."
        ),
        "file_not_found": (
            "The file was not found. Create or copy the file into the current "
            "workspace, then try again."
        ),
        "file_unreadable": (
            "The file could not be read. Create or copy the file into the current "
            "workspace, then try again."
        ),
        "file_too_large": (
            "The file is too large to publish. Create or copy a smaller file into "
            "the current workspace, then try again."
        ),
    }

    def __init__(self, code: str, detail: str) -> None:
        if code not in self.messages:
            raise ValueError("publication input code was invalid")
        self.code = code
        self.publication_code = code
        self.publication_message = self.messages[code]
        super().__init__(detail)


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
    "IncomingFileError",
    "PublicationInputError",
]
