"""Domain errors translated by the HTTP/management adapters."""


class AuthDomainError(Exception):
    code = "auth_error"


class ProviderUnavailable(AuthDomainError):
    code = "provider_unavailable"


class InvalidRedirect(AuthDomainError):
    code = "invalid_redirect"


class InvalidFlow(AuthDomainError):
    code = "flow_invalid"


class FlowReplay(InvalidFlow):
    code = "flow_replayed"


class ProviderRejected(AuthDomainError):
    code = "provider_rejected"


class IdentityConflict(AuthDomainError):
    code = "already_linked_elsewhere"


class SessionInvalid(AuthDomainError):
    code = "session_invalid"


class WorkspaceAccessDenied(AuthDomainError):
    code = "workspace_denied"


class WorkspaceInvariantError(AuthDomainError):
    code = "workspace_invariant_failed"


class ValidationError(AuthDomainError):
    code = "validation_error"


class AvatarError(AuthDomainError):
    code = "avatar_invalid"


class AvatarStorageUnavailable(AvatarError):
    code = "storage_unavailable"


class AvatarNotFound(AvatarError):
    code = "avatar_absent"


class AvatarConflict(AvatarError):
    code = "invalid_state"
