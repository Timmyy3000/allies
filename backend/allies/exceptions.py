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
