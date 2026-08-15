"""Privacy-safe waitlist domain errors."""


class WaitlistError(Exception):
    code = "waitlist_error"


class WaitlistUnavailable(WaitlistError):
    code = "waitlist_unavailable"


class DraftUnavailable(WaitlistError):
    code = "waitlist_draft_unavailable"


class DraftStale(WaitlistError):
    code = "waitlist_draft_stale"


class InvalidDraftState(WaitlistError):
    code = "waitlist_invalid_state"


class IdempotencyConflict(WaitlistError):
    code = "idempotency_conflict"


class OperationInProgress(WaitlistError):
    code = "waitlist_operation_in_progress"


class GenerationUnknown(WaitlistError):
    code = "generation_outcome_unknown"


class GenerationUnavailable(WaitlistError):
    code = "generation_unavailable"


class AdmissionUnavailable(WaitlistError):
    code = "waitlist_unavailable"


class Throttled(WaitlistError):
    code = "throttled"


class WaitlistValidationError(WaitlistError):
    code = "validation_error"

    def __init__(
        self,
        message: str,
        *,
        field: str = "request",
        reason_code: str = "value_error",
    ):
        super().__init__(message)
        self.field = field
        self.reason_code = reason_code


class ClaimRejected(WaitlistError):
    code = "waitlist_claim_rejected"
