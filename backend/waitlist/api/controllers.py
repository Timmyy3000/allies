"""Cookie-bound public waitlist API controllers."""

from dataclasses import asdict

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja_extra import ControllerBase, api_controller, http_get, http_patch, http_post

from auths.api.common import (
    _auth_rate_limit_identity,
    _client_identity,
    _require_origin,
    _set_auth_throttle_cookie,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse

from ..admission import (
    admit_bootstrap,
    admit_capability,
    admit_creation,
)
from ..capabilities import (
    capability_cookie_name,
    new_capability,
    refresh_capability,
    resolve_capability,
    set_capability_cookie,
    set_csrf_cookie,
)
from ..exceptions import (
    AdmissionUnavailable,
    Throttled,
    WaitlistError,
    WaitlistValidationError,
)
from ..services.drafts import (
    create_or_resume_draft,
    get_draft,
    revoke_expired_capability,
    snapshot_for,
    update_configuration,
)
from ..services.generation import generate_greeting
from ..services.join import join_waitlist, mask_email
from ..services.reply import record_reply
from .schemas import (
    WaitlistAcknowledgement,
    WaitlistConfigurationRequest,
    WaitlistGreetingRequest,
    WaitlistJoinConfirmation,
    WaitlistJoinRequest,
    WaitlistReplyRequest,
    WaitlistSnapshot,
)


def _enabled() -> bool:
    return bool(getattr(settings, "ALLIES_WAITLIST_ENABLED", False))


def _disabled() -> JsonResponse:
    return error_json("waitlist_unavailable", "waitlist unavailable", 503)


def _validation_error(exc: WaitlistValidationError | None = None) -> JsonResponse:
    field = getattr(exc, "field", "request") or "request"
    reason_code = getattr(exc, "reason_code", "value_error")
    if reason_code not in {
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
    }:
        reason_code = "value_error"
    return error_json(
        "validation_error",
        "request validation failed",
        422,
        details={"errors": [{"field": field, "code": reason_code}]},
    )


def _idempotency_key(request: HttpRequest) -> str | None:
    return request.headers.get("Idempotency-Key")


def _origin_error(request: HttpRequest):
    return _require_origin(request)


def _same_site_origin_error(request: HttpRequest):
    """Reject cross-site bootstrap before this GET mutates browser state.

    Session bootstrap is intentionally exempt from the CSRF-token half of the
    mutation guard because it issues the first CSRF token.  It still validates
    any supplied Origin/Referer against the trusted frontend origins before
    admission, capability rotation, or expiry revocation can occur.
    """

    origin = request.headers.get("Origin")
    if not origin:
        referer = request.headers.get("Referer")
        if referer:
            origin = "/".join(referer.split("/", 3)[:3])
    if not origin or origin not in set(getattr(settings, "CSRF_TRUSTED_ORIGINS", ())):
        return error_json("origin_rejected", "origin rejected", 403)
    return None


def _status_for(exc: WaitlistError) -> int:
    return {
        "waitlist_draft_unavailable": 404,
        "waitlist_draft_stale": 409,
        "waitlist_invalid_state": 409,
        "idempotency_conflict": 409,
        "waitlist_operation_in_progress": 409,
        "generation_outcome_unknown": 503,
        "generation_unavailable": 503,
        "throttled": 429,
        "waitlist_unavailable": 503,
        "validation_error": 422,
    }.get(getattr(exc, "code", ""), 400)


def _waitlist_error(exc: WaitlistError) -> JsonResponse:
    code = getattr(exc, "code", "waitlist_error")
    if code == "validation_error":
        return _validation_error(
            exc if isinstance(exc, WaitlistValidationError) else None
        )
    message = (
        "waitlist unavailable"
        if code == "waitlist_unavailable"
        else "waitlist request failed"
    )
    return error_json(
        code,
        message,
        _status_for(exc),
    )


def _ack_json(ack, message: str = "Waitlist updated") -> JsonResponse:
    return success_json(
        WaitlistAcknowledgement(
            operation=ack.operation,
            result_revision=ack.result_revision,
            result_lifecycle=ack.result_lifecycle,
        ),
        message,
    )


def _snapshot_json(draft) -> JsonResponse:
    snapshot = snapshot_for(draft)
    return success_json(WaitlistSnapshot(**asdict(snapshot)), "Waitlist draft restored")


def _refresh_capability_response(
    response: HttpResponse, request: HttpRequest
) -> HttpResponse:
    raw = request.COOKIES.get(capability_cookie_name())
    if raw:
        # All callers have already accepted this cookie through
        # resolve_capability.  Do not re-check its age after a slow provider
        # call: crossing the boundary here would rotate the nonce and orphan
        # the draft that the request just mutated.
        set_capability_cookie(response, refresh_capability(raw, validated=True))
    return response


@api_controller("/waitlist", tags=["Waitlist"])
class WaitlistController(ControllerBase):
    @http_get("/session", response={204: None, **error_responses(403, 429, 503)})
    def session(self, request: HttpRequest):
        if not _enabled():
            return _disabled()
        origin_error = _same_site_origin_error(request)
        if origin_error:
            return origin_error
        try:
            identity = _auth_rate_limit_identity(request)
            if not identity:
                # Cookie-less Railway callers need a bounded network admission
                # gate before a fresh capability can be minted.
                identity = f"unbound:{_client_identity(request)}"
            admit_bootstrap(identity)
        except (AdmissionUnavailable, Throttled) as exc:
            return _waitlist_error(exc)
        response = HttpResponse(status=204)
        set_csrf_cookie(response, request)
        if getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
            _set_auth_throttle_cookie(response, request)
        resolution = resolve_capability(request)
        if resolution.issue_cookie:
            if resolution.expired_digest:
                revoke_expired_capability(
                    capability_digest=resolution.expired_digest,
                    force=True,
                )
            set_capability_cookie(response, resolution.issue_cookie)
        elif resolution.digest and revoke_expired_capability(
            capability_digest=resolution.digest
        ):
            set_capability_cookie(response, new_capability())
        else:
            current = request.COOKIES.get(capability_cookie_name())
            set_capability_cookie(
                response, refresh_capability(current) if current else new_capability()
            )
        return response

    @http_post(
        "/draft",
        response={
            200: SuccessResponse[WaitlistAcknowledgement],
            **error_responses(403, 404, 409, 422, 429, 503),
        },
    )
    def create(self, request: HttpRequest):
        if not _enabled():
            return _disabled()
        origin_error = _origin_error(request)
        if origin_error:
            return origin_error
        key = _idempotency_key(request)
        resolution = resolve_capability(request)
        if not resolution.digest:
            return error_json("waitlist_draft_unavailable", "waitlist unavailable", 404)
        if not key:
            return _validation_error()
        try:
            identity = _auth_rate_limit_identity(request)
            if identity:
                # Existing Railway browsers retain a server-issued identity;
                # creation is the point at which that per-browser admission
                # protects storage when a capability is rotated.
                admit_bootstrap(identity)
            elif getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
                # A caller that clears both cookies remains unbound. Keep
                # this distributed creation budget separate from harmless
                # session/cookie issuance so one attacker cannot hold the
                # session endpoint hostage for every new browser.
                admit_creation("railway:unbound")
            admit_capability(resolution.digest)
            ack = create_or_resume_draft(
                capability_digest=resolution.digest, raw_key=key
            )
        except (WaitlistError, ValueError) as exc:
            return (
                _waitlist_error(exc)
                if isinstance(exc, WaitlistError)
                else _validation_error()
            )
        return _refresh_capability_response(
            _ack_json(ack, "Waitlist draft ready"), request
        )

    @http_get(
        "/draft",
        response={
            200: SuccessResponse[WaitlistSnapshot],
            **error_responses(403, 404, 429, 503),
        },
    )
    def restore(self, request: HttpRequest):
        if not _enabled():
            return _disabled()
        origin_error = _same_site_origin_error(request)
        if origin_error:
            return origin_error
        resolution = resolve_capability(request)
        try:
            if resolution.digest:
                admit_capability(resolution.digest)
            return _refresh_capability_response(
                _snapshot_json(get_draft(capability_digest=resolution.digest or "")),
                request,
            )
        except (WaitlistError, AdmissionUnavailable, Throttled) as exc:
            return _waitlist_error(exc)

    @http_patch(
        "/draft/configuration",
        response={
            200: SuccessResponse[WaitlistAcknowledgement],
            **error_responses(403, 404, 409, 422, 429, 503),
        },
    )
    def configuration(
        self, request: HttpRequest, payload: WaitlistConfigurationRequest
    ):
        if not _enabled():
            return _disabled()
        origin_error = _origin_error(request)
        if origin_error:
            return origin_error
        key = _idempotency_key(request)
        if not key:
            return _validation_error()
        resolution = resolve_capability(request)
        if not resolution.digest:
            return error_json("waitlist_draft_unavailable", "waitlist unavailable", 404)
        changes = payload.model_dump(exclude={"revision"}, exclude_none=True)
        try:
            admit_capability(resolution.digest)
            ack = update_configuration(
                capability_digest=resolution.digest,
                revision=payload.revision,
                changes=changes,
                raw_key=key,
            )
        except (WaitlistError, ValueError) as exc:
            return (
                _waitlist_error(exc)
                if isinstance(exc, WaitlistError)
                else _validation_error()
            )
        return _refresh_capability_response(
            _ack_json(ack, "Waitlist configuration saved"), request
        )

    @http_post(
        "/draft/greeting",
        response={
            200: SuccessResponse[WaitlistAcknowledgement],
            **error_responses(403, 404, 409, 422, 429, 503),
        },
    )
    def greeting(self, request: HttpRequest, payload: WaitlistGreetingRequest):
        if not _enabled():
            return _disabled()
        origin_error = _origin_error(request)
        if origin_error:
            return origin_error
        key = _idempotency_key(request)
        resolution = resolve_capability(request)
        if not resolution.digest:
            return error_json("waitlist_draft_unavailable", "waitlist unavailable", 404)
        if not key:
            return _validation_error()
        generation_identity = _auth_rate_limit_identity(request)
        if not generation_identity:
            generation_identity = f"unbound:{_client_identity(request)}"
        try:
            # Generation owns its capability and global cost admission so
            # direct service callers and this HTTP path consume one token.
            ack = generate_greeting(
                capability_digest=resolution.digest,
                revision=payload.revision,
                raw_key=key,
                generation_identity=generation_identity,
            )
        except (WaitlistError, ValueError) as exc:
            return (
                _waitlist_error(exc)
                if isinstance(exc, WaitlistError)
                else _validation_error()
            )
        return _refresh_capability_response(_ack_json(ack, "Greeting ready"), request)

    @http_post(
        "/draft/reply",
        response={
            200: SuccessResponse[WaitlistAcknowledgement],
            **error_responses(403, 404, 409, 422, 429, 503),
        },
    )
    def reply(self, request: HttpRequest, payload: WaitlistReplyRequest):
        if not _enabled():
            return _disabled()
        origin_error = _origin_error(request)
        if origin_error:
            return origin_error
        key = _idempotency_key(request)
        resolution = resolve_capability(request)
        if not resolution.digest:
            return error_json("waitlist_draft_unavailable", "waitlist unavailable", 404)
        if not key:
            return _validation_error()
        try:
            admit_capability(resolution.digest)
            ack = record_reply(
                capability_digest=resolution.digest,
                revision=payload.revision,
                text=payload.text,
                raw_key=key,
            )
        except (WaitlistError, ValueError) as exc:
            return (
                _waitlist_error(exc)
                if isinstance(exc, WaitlistError)
                else _validation_error()
            )
        return _refresh_capability_response(_ack_json(ack, "Reply preserved"), request)

    @http_post(
        "/draft/join",
        response={
            200: SuccessResponse[WaitlistJoinConfirmation],
            **error_responses(403, 404, 409, 422, 429, 503),
        },
    )
    def join(self, request: HttpRequest, payload: WaitlistJoinRequest):
        if not _enabled():
            return _disabled()
        origin_error = _origin_error(request)
        if origin_error:
            return origin_error
        key = _idempotency_key(request)
        resolution = resolve_capability(request)
        if not resolution.digest:
            return error_json("waitlist_draft_unavailable", "waitlist unavailable", 404)
        if not key:
            return _validation_error()
        try:
            admit_capability(resolution.digest)
            ack = join_waitlist(
                capability_digest=resolution.digest,
                revision=payload.revision,
                email=payload.email,
                consent_version=payload.consent_version,
                raw_key=key,
            )
        except (WaitlistError, ValueError) as exc:
            return (
                _waitlist_error(exc)
                if isinstance(exc, WaitlistError)
                else _validation_error()
            )
        # Keep the immutable acknowledgement small; masking is recomputed by
        # restore from the joined snapshot and never exposes normalized email.
        return _refresh_capability_response(
            success_json(
                WaitlistJoinConfirmation(
                    operation=ack.operation,
                    result_revision=ack.result_revision,
                    result_lifecycle=ack.result_lifecycle,
                    email=mask_email(payload.email),
                ),
                "Waitlist joined",
            ),
            request,
        )
