class WaitlistError(Exception):
    code = "waitlist_error"


class WaitlistUnavailable(WaitlistError):
    code = "waitlist_unavailable"


class EntryUnavailable(WaitlistError):
    code = "waitlist_entry_unavailable"


class InvalidEntryState(WaitlistError):
    code = "waitlist_invalid_state"


class GenerationUnavailable(WaitlistError):
    code = "generation_unavailable"


class AdmissionUnavailable(WaitlistError):
    code = "waitlist_unavailable"


class Throttled(WaitlistError):
    code = "throttled"


class WaitlistValidationError(WaitlistError):
    code = "validation_error"

    def __init__(
        self, message: str, *, field: str = "request", reason_code: str = "value_error"
    ):
        super().__init__(message)
        self.field = field
        self.reason_code = reason_code
