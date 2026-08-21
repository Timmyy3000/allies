import logging

from ninja.errors import ValidationError

from allies.api.register import register as register_allies_api
from auths.api.common import error_json
from auths.api.register import register as register_auths_api
from config.health import HealthController
from config.openapi import AlliesAPI
from waitlist.api.register import register as register_waitlist_api
from workspaces.api.register import register as register_workspaces_api

logger = logging.getLogger(__name__)

api = AlliesAPI(
    title="Allies Cloud API",
    version="0.1.0",
)


def _validation_error(request, exc: ValidationError):
    """Keep framework-level request validation inside the public envelope."""

    # Pydantic's default errors include ``input`` and ``ctx``.  Those values
    # can contain visitor-authored text, email addresses, retry keys, or cookie
    # material, so the public contract exposes only a field location and a
    # low-cardinality reason code.
    allowed_codes = {
        "missing",
        "string_type",
        "string_too_short",
        "string_too_long",
        "int_type",
        "greater_than",
        "less_than",
        "value_error",
        "json_invalid",
        "list_type",
        "dict_type",
        "bool_type",
    }
    safe_errors = []
    for error in getattr(exc, "errors", ()):
        location = error.get("loc", ()) if isinstance(error, dict) else ()
        field = ".".join(str(item) for item in location) or "request"
        raw_code = (
            error.get("type", "value_error")
            if isinstance(error, dict)
            else "value_error"
        )
        safe_errors.append(
            {
                "field": field,
                "code": raw_code if raw_code in allowed_codes else "value_error",
            }
        )

    return error_json(
        "validation_error",
        "request validation failed",
        422,
        details={"errors": safe_errors},
    )


def _unhandled_error(request, exc: Exception):
    """Prevent framework fallbacks from violating the JSON error contract."""

    logger.exception(
        "unhandled API exception",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"request_method": request.method, "request_path": request.path},
    )
    return error_json("internal_error", "internal server error", 500)


api.add_exception_handler(ValidationError, _validation_error)
api.add_exception_handler(Exception, _unhandled_error)


def register_all_apis() -> None:
    api.register_controllers(HealthController)
    register_auths_api(api)
    register_workspaces_api(api)
    register_waitlist_api(api)
    register_allies_api(api)


register_all_apis()
