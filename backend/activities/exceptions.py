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
