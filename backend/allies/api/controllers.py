from typing import Annotated

from django.http import HttpRequest
from ninja import Header
from ninja_extra import ControllerBase, api_controller, http_get, http_post

from allies.api.schemas import (
    AllyListResponse,
    AllyResponse,
    CreateAllyRequest,
    OnboardingAttemptRequest,
    OnboardingAttemptResponse,
    RuntimeIntentRequest,
    RuntimeIntentResponse,
    WorkspaceRuntimeIntentRequest,
)
from allies.exceptions import (
    IdempotencyConflict,
    OnboardingInvalid,
    OnboardingUnavailable,
    RuntimeIntentInvalid,
)
from allies.gateways.foundry import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
)
from allies.models import Ally, ProvisioningStatus
from allies.services.creation import create_ally, list_allies, retrieve_ally
from allies.services.onboarding import begin_onboarding, digest_value
from allies.services.runtime_intents import (
    request_runtime_intent,
    request_workspace_runtime_intent,
)
from auths.api.common import (
    _client_identity,
    _csrf_binding,
    _require_origin,
    _session,
    check_native_rate_limit,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse
from auths.config import native_enabled
from auths.exceptions import (
    NativeIdentityUnavailable,
    SessionInvalid,
    WorkspaceAccessDenied,
)
from auths.models import SessionClientKind
from auths.throttle import ThrottleExceeded, ThrottleUnavailable
from common.uuids import CanonicalUUID
from waitlist.exceptions import Throttled

_BROWSER_SIGNAL_HEADERS = ("Origin", "Referer", "X-CSRFToken")


def _has_browser_signal(request: HttpRequest) -> bool:
    return (
        bool(request.COOKIES)
        or bool(request.headers.get("Cookie", "").strip())
        or any(
            request.headers.get(name) is not None for name in _BROWSER_SIGNAL_HEADERS
        )
    )


def _is_native_attempt_request(request: HttpRequest) -> bool:
    return (
        not _has_browser_signal(request)
        and request.headers.get("Authorization") is None
    )


def _is_native_create_request(request: HttpRequest) -> bool:
    return request.headers.get("Authorization") is not None and not _has_browser_signal(
        request
    )


def _no_store(response):
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _response(ally: Ally) -> AllyResponse:
    operation = ally.binding.provisioning_operation
    return AllyResponse(
        id=str(ally.id),
        binding_id=str(ally.binding.id),
        operation_id=str(operation.id),
        name=ally.name,
        job=ally.job,
        personality=ally.personality,
        appearance={
            "catalog_version": ally.appearance_catalog_version,
            "key": ally.appearance_key,
        },
        provisioning_state=ally.provisioning_state,
        retryable=operation.status == ProvisioningStatus.RETRYABLE,
    )


@api_controller("/onboarding", tags=["Onboarding"])
class OnboardingController(ControllerBase):
    @http_post(
        "/attempts",
        response={
            200: SuccessResponse[OnboardingAttemptResponse],
            **error_responses(403, 422, 429, 503),
        },
    )
    def begin(self, request: HttpRequest, payload: OnboardingAttemptRequest):
        browser_binding = None
        if _is_native_attempt_request(request):
            if not native_enabled():
                return error_json(
                    "onboarding_unavailable", "onboarding unavailable", 503
                )
            try:
                requester_identity = check_native_rate_limit(request, "onboarding")
            except ThrottleExceeded:
                return error_json("throttled", "try again later", 429)
            except (NativeIdentityUnavailable, ThrottleUnavailable, ValueError):
                return error_json(
                    "onboarding_unavailable", "onboarding unavailable", 503
                )
            generation_identity = f"onboarding:{digest_value(requester_identity)}"
        else:
            if rejected := _require_origin(request):
                return rejected
            browser_binding = _csrf_binding(request)
            generation_identity = f"onboarding:{_client_identity(request)}"
        try:
            start = begin_onboarding(
                name=payload.name,
                job=payload.job,
                personality=payload.personality,
                appearance_catalog_version=payload.appearance.catalog_version,
                appearance_key=payload.appearance.key,
                browser_binding=browser_binding,
                generation_identity=generation_identity,
            )
        except OnboardingInvalid:
            return error_json("validation_error", "request validation failed", 422)
        except Throttled:
            return error_json("throttled", "try again later", 429)
        except OnboardingUnavailable:
            return error_json("onboarding_unavailable", "onboarding unavailable", 503)
        return _no_store(
            success_json(
                OnboardingAttemptResponse(
                    attempt_token=start.attempt_token,
                    greeting=start.greeting,
                ),
                "Onboarding started",
            )
        )

    @http_post(
        "/runtime-intents",
        response={
            200: SuccessResponse[RuntimeIntentResponse],
            202: SuccessResponse[RuntimeIntentResponse],
            **error_responses(401, 403, 404, 409, 422, 429, 503),
        },
    )
    def runtime_intent(
        self,
        request: HttpRequest,
        payload: WorkspaceRuntimeIntentRequest,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=36,
                max_length=36,
                description="Stable UUID for repeating one runtime intent.",
            ),
        ],
    ):
        native_request = bool(
            request.headers.get("Authorization")
        ) and not _has_browser_signal(request)
        if native_request and not native_enabled():
            return error_json("session_invalid", "session invalid", 401)
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(
                request,
                expected_client_kind=(
                    SessionClientKind.NATIVE
                    if native_request
                    else SessionClientKind.BROWSER
                ),
            )
            result = request_workspace_runtime_intent(
                user=session.user,
                intent=payload.intent,
                occurred_at=payload.occurred_at,
                idempotency_key=idempotency_key,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except RuntimeIntentInvalid:
            return error_json("validation_error", "request validation failed", 422)
        except (WorkspaceAccessDenied, ValueError):
            return error_json("workspace_unavailable", "Workspace unavailable", 404)
        except ThrottleExceeded:
            return error_json("rate_limited", "Request temporarily unavailable", 429)
        except ThrottleUnavailable:
            return error_json(
                "throttle_unavailable", "Request temporarily unavailable", 503
            )
        except FoundryGatewayConflict:
            return error_json(
                "runtime_intent_conflict", "Runtime intent unavailable", 409
            )
        except FoundryGatewayNotFound:
            return error_json(
                "runtime_intent_unavailable", "Runtime intent unavailable", 404
            )
        except (
            FoundryGatewayInvalid,
            FoundryGatewayRejected,
            FoundryGatewayRetryable,
            FoundryGatewayUnknownOutcome,
        ):
            return error_json(
                "runtime_intent_unavailable", "Runtime intent unavailable", 503
            )
        response = RuntimeIntentResponse(status=result.status)
        return success_json(
            response,
            "Runtime intent accepted",
            status=202 if result.status == "waking" else 200,
        )


@api_controller("/workspaces/{workspace_id}/allies", tags=["Allies"])
class AllyController(ControllerBase):
    @http_get(
        "",
        response={
            200: SuccessResponse[AllyListResponse],
            **error_responses(401, 404, 500),
        },
    )
    def list(self, request: HttpRequest, workspace_id: CanonicalUUID):
        try:
            session = _session(request)
            allies = list_allies(user=session.user, workspace_id=workspace_id)
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, ValueError):
            return error_json("ally_unavailable", "Ally unavailable", 404)
        return success_json(
            AllyListResponse(allies=[_response(ally) for ally in allies]),
            "Allies loaded",
        )

    @http_post(
        "",
        response={
            201: SuccessResponse[AllyResponse],
            202: SuccessResponse[AllyResponse],
            **error_responses(401, 403, 404, 409, 422, 500),
        },
    )
    def create(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        payload: CreateAllyRequest,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=16,
                max_length=128,
                description=(
                    "Stable key for repeating the exact create request; "
                    "changed content with the same key conflicts."
                ),
            ),
        ],
    ):
        native_request = _is_native_create_request(request)
        if native_request:
            if not native_enabled():
                return error_json("session_invalid", "session invalid", 401)
        elif request.headers.get("Authorization") is not None:
            return error_json("csrf_rejected", "csrf rejected", 403)
        else:
            if rejected := _require_origin(request):
                return rejected
        try:
            session = _session(
                request,
                expected_client_kind=(
                    SessionClientKind.NATIVE
                    if native_request
                    else SessionClientKind.BROWSER
                ),
            )
            result = create_ally(
                user=session.user,
                workspace_id=workspace_id,
                name=payload.name,
                job=payload.job,
                personality=payload.personality,
                appearance_catalog_version=payload.appearance.catalog_version,
                appearance_key=payload.appearance.key,
                onboarding_attempt=payload.onboarding_attempt,
                reply=payload.reply,
                browser_binding=None if native_request else _csrf_binding(request),
                idempotency_key=idempotency_key,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (WorkspaceAccessDenied, KeyError, ValueError):
            return error_json("ally_unavailable", "Ally unavailable", 404)
        except IdempotencyConflict:
            return error_json("idempotency_conflict", "request conflicts", 409)
        except OnboardingInvalid:
            return error_json("onboarding_invalid", "onboarding attempt invalid", 422)
        status = 201 if result.ally.provisioning_state == "bound" else 202
        return success_json(_response(result.ally), "Ally created", status=status)

    @http_get(
        "/{ally_id}",
        response={200: SuccessResponse[AllyResponse], **error_responses(401, 404, 500)},
    )
    def retrieve(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
    ):
        try:
            session = _session(request)
            ally = retrieve_ally(
                user=session.user, workspace_id=workspace_id, ally_id=ally_id
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except (Ally.DoesNotExist, WorkspaceAccessDenied, ValueError):
            return error_json("ally_unavailable", "Ally unavailable", 404)
        return success_json(_response(ally), "Ally loaded")


@api_controller("/allies", tags=["Allies"])
class RuntimeIntentController(ControllerBase):
    @http_post(
        "/{ally_id}/runtime-intents",
        response={
            200: SuccessResponse[RuntimeIntentResponse],
            202: SuccessResponse[RuntimeIntentResponse],
            **error_responses(401, 404, 409, 422, 429, 503),
        },
    )
    def request(
        self,
        request: HttpRequest,
        ally_id: CanonicalUUID,
        payload: RuntimeIntentRequest,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=36,
                max_length=36,
                description="Stable UUID for repeating one runtime intent.",
            ),
        ],
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            result = request_runtime_intent(
                user=session.user,
                ally_id=ally_id,
                intent=payload.intent,
                occurred_at=payload.occurred_at,
                idempotency_key=idempotency_key,
            )
        except SessionInvalid:
            return error_json("session_invalid", "session invalid", 401)
        except RuntimeIntentInvalid:
            return error_json("validation_error", "request validation failed", 422)
        except (WorkspaceAccessDenied, ValueError):
            return error_json("ally_unavailable", "Ally unavailable", 404)
        except ThrottleExceeded:
            return error_json("rate_limited", "Request temporarily unavailable", 429)
        except ThrottleUnavailable:
            return error_json(
                "throttle_unavailable", "Request temporarily unavailable", 503
            )
        except FoundryGatewayConflict:
            return error_json(
                "runtime_intent_conflict", "Runtime intent unavailable", 409
            )
        except FoundryGatewayNotFound:
            return error_json(
                "runtime_intent_unavailable", "Runtime intent unavailable", 404
            )
        except (
            FoundryGatewayInvalid,
            FoundryGatewayRejected,
            FoundryGatewayRetryable,
            FoundryGatewayUnknownOutcome,
        ):
            return error_json(
                "runtime_intent_unavailable", "Runtime intent unavailable", 503
            )
        response = RuntimeIntentResponse(status=result.status)
        return success_json(
            response,
            "Runtime intent accepted",
            status=202 if result.status == "waking" else 200,
        )
