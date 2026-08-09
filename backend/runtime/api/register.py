from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja.errors import ValidationError as NinjaValidationError
from ninja_extra import NinjaExtraAPI

from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeDomainError,
    RuntimeValidationError,
)
from runtime.services.attempts import complete_attempt, fail_attempt
from runtime.services.claims import claim_next_execution
from runtime.services.events import append_runtime_event
from runtime.services.leases import acknowledge_stopped, renew_lease
from runtime.services.runtime_auth import authenticate_runtime_token
from runtime.services.sessions import update_session_binding

from .schemas import (
    ClaimRequest,
    CompleteRequest,
    EventRequest,
    FailRequest,
    SessionBindingRequest,
    StoppedRequest,
)


def register(api: NinjaExtraAPI) -> None:
    api.add_exception_handler(NinjaValidationError, _validation_error)

    @api.post("/runtime/claims", auth=None)
    def claims(request: HttpRequest, payload: ClaimRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            claim = claim_next_execution(
                context, payload.claim_id, payload.available_slots
            )
            if claim is None:
                return HttpResponse(status=204)
            return JsonResponse(_claim_json(claim), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/lease/renew", auth=None)
    def renew(request: HttpRequest, attempt_id):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = renew_lease(context, attempt_id, _lease_token(request))
            return JsonResponse(
                {"lease_id": str(receipt.lease_id), "expires_at": _timestamp(receipt.expires_at)},
                status=200,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/events", auth=None)
    def events(request: HttpRequest, attempt_id, payload: EventRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            event = append_runtime_event(
                context,
                attempt_id,
                _lease_token(request),
                payload.event_id,
                payload.stream_id,
                payload.sequence,
                payload.type,
                payload.payload,
            )
            return JsonResponse(
                {"event_id": str(event.event_id), "sequence": event.sequence},
                status=202,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.put("/runtime/attempts/{attempt_id}/session-binding", auth=None)
    def session_binding(
        request: HttpRequest,
        attempt_id,
        payload: SessionBindingRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            binding = update_session_binding(
                context,
                attempt_id,
                _lease_token(request),
                payload.cloud_conversation_ref,
                payload.expected_session_id,
                payload.effective_session_id,
            )
            return JsonResponse({"session_id": binding.hermes_session_id}, status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/stopped", auth=None)
    def stopped(request: HttpRequest, attempt_id, payload: StoppedRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = acknowledge_stopped(
                context,
                attempt_id,
                _lease_token(request),
                payload.reason,
            )
            return JsonResponse(
                {
                    "attempt_id": str(receipt.attempt_id),
                    "state": receipt.state,
                    "requeued": receipt.requeued,
                },
                status=200,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/complete", auth=None)
    def complete(request: HttpRequest, attempt_id, payload: CompleteRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = complete_attempt(
                context, attempt_id, _lease_token(request), payload.receipt
            )
            return JsonResponse(_terminal_json(receipt), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/fail", auth=None)
    def fail(request: HttpRequest, attempt_id, payload: FailRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = fail_attempt(
                context,
                attempt_id,
                _lease_token(request),
                {
                    "code": payload.code,
                    "retryable": payload.retryable,
                    "receipt": payload.receipt,
                },
            )
            return JsonResponse(_terminal_json(receipt), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)


def _bearer(request: HttpRequest) -> str:
    value = request.headers.get("Authorization", "")
    if not value.startswith("Bearer "):
        raise RuntimeAuthorizationError("invalid runtime credential")
    token = value[7:]
    if not token:
        raise RuntimeAuthorizationError("invalid runtime credential")
    return token


def _lease_token(request: HttpRequest) -> str:
    value = request.headers.get("X-Foundry-Lease-Token", "")
    if not value:
        raise RuntimeAuthorizationError("missing lease token")
    return value


def _error(exc: RuntimeDomainError) -> JsonResponse:
    if isinstance(exc, RuntimeAuthorizationError):
        status = 401
    elif isinstance(exc, RuntimeValidationError):
        status = 422
    else:
        status = 409
    return JsonResponse(
        {"code": getattr(exc, "code", "CONFLICT"), "message": str(exc)},
        status=status,
    )


def _validation_error(request: HttpRequest, exc: NinjaValidationError) -> JsonResponse:
    return JsonResponse(
        {"code": "INVALID_REQUEST", "message": "request body is invalid"},
        status=422,
    )


def _timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


def _claim_json(claim):
    return {
        "attempt_id": str(claim.attempt_id),
        "execution_id": str(claim.execution_id),
        "profile_id": str(claim.profile_id),
        "hermes_profile_key": claim.hermes_profile_key,
        "conversation_id": claim.conversation_id,
        "session_id": claim.session_id,
        "stream_id": claim.stream_id,
        "lease_id": str(claim.lease_id),
        "lease_token": claim.lease_token,
        "expires_at": _timestamp(claim.expires_at),
        "payload": claim.payload,
        "claim_id": str(claim.claim_id),
    }


def _terminal_json(receipt):
    return {
        "attempt_id": str(receipt.attempt_id),
        "status": receipt.status,
        "receipt_id": str(receipt.receipt_id),
        "requeued": receipt.requeued,
        "receipt": receipt.receipt,
    }
