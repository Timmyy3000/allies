"""Public two-request waitlist API."""

from urllib.parse import urlsplit

from auths.api.common import _client_identity, error_json, error_responses, success_json
from auths.api.schemas import SuccessResponse
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from ninja_extra import ControllerBase, api_controller, http_post

from ..exceptions import WaitlistError, WaitlistValidationError
from ..services.entries import complete_entry, create_entry
from .schemas import (
    WaitlistEntryCompletionRequest,
    WaitlistEntryCompletionResponse,
    WaitlistEntryRequest,
    WaitlistEntryResponse,
)


def _origin_is_trusted(origin: str) -> bool:
    candidate = urlsplit(origin)
    if candidate.scheme not in {"http", "https"} or not candidate.hostname:
        return False
    for configured in getattr(settings, "CSRF_TRUSTED_ORIGINS", ()):
        trusted = urlsplit(configured)
        if candidate.scheme != trusted.scheme:
            continue
        if trusted.hostname and trusted.hostname.startswith("*."):
            suffix = trusted.hostname[1:]
            if candidate.hostname.endswith(suffix) and candidate.port == trusted.port:
                return True
        elif candidate.netloc == trusted.netloc:
            return True
    return False


def _trusted_origin_error(request: HttpRequest):
    origin = request.headers.get("Origin")
    if not origin:
        referer = request.headers.get("Referer")
        if referer:
            origin = "/".join(referer.split("/", 3)[:3])
    if not origin or not _origin_is_trusted(origin):
        return error_json("origin_rejected", "origin rejected", 403)
    return None


def _status_for(error: WaitlistError) -> int:
    return {
        "waitlist_entry_unavailable": 404,
        "waitlist_invalid_state": 409,
        "generation_unavailable": 503,
        "throttled": 429,
        "waitlist_unavailable": 503,
        "validation_error": 422,
    }.get(error.code, 400)


def _error(error: WaitlistError) -> JsonResponse:
    if isinstance(error, WaitlistValidationError):
        return error_json(
            "validation_error",
            "request validation failed",
            422,
            details={"errors": [{"field": error.field, "code": error.reason_code}]},
        )
    return error_json(error.code, "waitlist request failed", _status_for(error))


@api_controller("/waitlist", tags=["Waitlist"])
class WaitlistController(ControllerBase):
    @http_post(
        "/entries",
        response={
            200: SuccessResponse[WaitlistEntryResponse],
            **error_responses(403, 409, 422, 429, 503),
        },
    )
    def create(self, request: HttpRequest, payload: WaitlistEntryRequest):
        if not getattr(settings, "ALLIES_WAITLIST_ENABLED", False):
            return error_json("waitlist_unavailable", "waitlist unavailable", 503)
        if origin_error := _trusted_origin_error(request):
            return origin_error
        try:
            entry = create_entry(
                **payload.model_dump(),
                generation_identity=f"public:{_client_identity(request)}",
            )
        except WaitlistError as error:
            return _error(error)
        return success_json(
            WaitlistEntryResponse(
                attempt_token=entry.attempt_token,
                greeting=entry.greeting,
            ),
            "Waitlist greeting ready",
        )

    @http_post(
        "/entries/complete",
        response={
            200: SuccessResponse[WaitlistEntryCompletionResponse],
            **error_responses(403, 404, 409, 422, 503),
        },
    )
    def complete(self, request: HttpRequest, payload: WaitlistEntryCompletionRequest):
        if not getattr(settings, "ALLIES_WAITLIST_ENABLED", False):
            return error_json("waitlist_unavailable", "waitlist unavailable", 503)
        if origin_error := _trusted_origin_error(request):
            return origin_error
        try:
            email = complete_entry(**payload.model_dump())
        except WaitlistError as error:
            return _error(error)
        return success_json(
            WaitlistEntryCompletionResponse(email=email),
            "Waitlist registration complete",
        )
