class ChatError(Exception):
    code = "chat_error"


class ConversationUnavailable(ChatError):
    code = "conversation_unavailable"


class OnboardingHandoffUnavailable(ConversationUnavailable):
    code = "onboarding_handoff_unavailable"


class OnboardingHandoffRepairRequired(ConversationUnavailable):
    code = "onboarding_handoff_repair_required"


class MessageValidation(ChatError):
    code = "validation_error"


class IdempotencyConflict(ChatError):
    code = "idempotency_conflict"


class QueueFull(ChatError):
    code = "conversation_queue_full"


class SendRateLimited(ChatError):
    code = "send_rate_limited"


class CursorInvalid(ChatError):
    code = "cursor_invalid"


class TurnConflict(ChatError):
    code = "turn_terminal_conflict"


class ChatUnavailable(ChatError):
    code = "internal_error"


class DispatchUnavailable(ChatError):
    code = "dispatch_unavailable"


class DispatchConflict(ChatError):
    code = "dispatch_conflict"
