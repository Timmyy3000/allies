"""Domain errors for the Cloud integrations vault and grants."""


class IntegrationError(Exception):
    code = "integration_error"


class IntegrationUnavailable(IntegrationError):
    code = "integration_unavailable"


class IntegrationInvalid(IntegrationError):
    code = "validation_error"


class IntegrationConflict(IntegrationError):
    code = "integration_conflict"


class GrantDenied(IntegrationError):
    code = "grant_denied"


class RefreshRevoked(IntegrationError):
    code = "refresh_revoked"


class ProviderUnavailable(IntegrationError):
    code = "provider_unavailable"


class ScopeInsufficient(IntegrationError):
    code = "scope_insufficient"


class WebSearchKeyRejected(IntegrationInvalid):
    code = "web_search_key_rejected"


class WebSearchCheckFailed(IntegrationUnavailable):
    code = "web_search_check_failed"


class WebSearchNotConnected(IntegrationConflict):
    code = "web_search_not_connected"
