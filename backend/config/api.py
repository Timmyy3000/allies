import logging

from ninja.errors import ValidationError

from auths.api.common import error_json
from auths.api.register import register as register_auths_api
from config.health import HealthController
from config.openapi import AlliesAPI
from workspaces.api.register import register as register_workspaces_api

logger = logging.getLogger(__name__)

api = AlliesAPI(
    title="Allies Cloud API",
    version="0.1.0",
)


def _validation_error(request, exc: ValidationError):
    """Keep framework-level request validation inside the public envelope."""

    return error_json(
        "validation_error",
        "request validation failed",
        422,
        details={"errors": exc.errors},
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


register_all_apis()
