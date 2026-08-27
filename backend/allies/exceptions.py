class AllyError(Exception):
    code = "ally_error"


class OnboardingUnavailable(AllyError):
    code = "onboarding_unavailable"


class OnboardingInvalid(AllyError):
    code = "onboarding_invalid"


class IdempotencyConflict(AllyError):
    code = "idempotency_conflict"


class ProvisioningRetryable(AllyError):
    code = "provisioning_retryable"


class ProvisioningRejected(AllyError):
    code = "provisioning_rejected"


class FoundryGatewayError(AllyError):
    code = "foundry_gateway_error"


class FoundryGatewayRetryable(FoundryGatewayError):
    code = "foundry_unavailable"


class FoundryGatewayUnknownOutcome(FoundryGatewayRetryable):
    code = "foundry_outcome_unknown"


class FoundryGatewayRejected(FoundryGatewayError):
    code = "foundry_rejected"


class FoundryGatewayConflict(FoundryGatewayError):
    code = "foundry_conflict"


class FoundryGatewayNotFound(FoundryGatewayError):
    code = "foundry_not_found"


class FoundryGatewayInvalid(FoundryGatewayError):
    code = "foundry_invalid"
