class ProjectionError(Exception):
    code = "projection_error"


class ProjectionNotFound(ProjectionError):
    code = "projection_unavailable"


class ProjectionConflict(ProjectionError):
    code = "projection_conflict"


class ProjectionInvalid(ProjectionError):
    code = "projection_invalid"


class ProjectionSequenceGap(ProjectionError):
    code = "sequence_gap"


class ProjectionCursorGap(ProjectionError):
    code = "activity_cursor_gap"


class ProjectionCursorExpired(ProjectionError):
    code = "activity_cursor_expired"


class ProjectionCursorInvalid(ProjectionError):
    code = "activity_cursor_invalid"


class ApprovalNotFound(ProjectionError):
    code = "approval_unavailable"


class ApprovalConflict(ProjectionError):
    code = "approval_conflict"


class ApprovalInvalid(ProjectionError):
    code = "approval_invalid"
