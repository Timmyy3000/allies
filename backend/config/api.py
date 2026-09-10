import hashlib
import logging

from ninja.errors import ValidationError

from activities.api.register import register as register_activities_api
from allies.api.register import register as register_allies_api
from auths.api.common import error_json
from auths.api.register import register as register_auths_api
from chat.api.register import register as register_chat_api
from config.health import HealthController
from config.openapi import AlliesAPI
from files.api.register import register as register_files_api
from routines.api.register import register as register_routines_api
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
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "value_error",
        "json_invalid",
        "int_parsing",
        "string_parsing",
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

    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", None)
    route_template = f"/{str(route).lstrip('/')}" if route else "unknown_route"
    error_type = type(exc).__name__
    error_fingerprint = hashlib.sha256(error_type.encode()).hexdigest()[:16]
    logger.error(
        "unhandled API exception",
        extra={
            "request_method": request.method,
            "route_template": route_template,
            "error_type": error_type,
            "error_fingerprint": error_fingerprint,
        },
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
    register_chat_api(api)
    register_files_api(api)
    register_activities_api(api)
    register_routines_api(api)


register_all_apis()
