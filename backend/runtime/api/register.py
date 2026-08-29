import secrets
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja.errors import ValidationError as NinjaValidationError
from ninja.security import HttpBearer
from ninja_extra import NinjaExtraAPI

from runtime.exceptions import (
    RuntimeAuthorizationError,
    RuntimeConflictError,
    RuntimeDomainError,
    RuntimeIdempotencyConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
)
from runtime.services.attempts import complete_attempt, fail_attempt
from runtime.services.claims import claim_next_execution
from runtime.services.events import append_runtime_event
from runtime.services.executions import (
    create_execution_intent,
    reconcile_execution_intent,
)
from runtime.services.leases import acknowledge_stopped, renew_lease
from runtime.services.profiles import (
    ProfileSeed,
    accept_cleanup_receipt,
    accept_materialization_receipt,
    ensure_runtime_profile,
    list_profile_reconciliation,
)
from runtime.services.runtime_auth import authenticate_runtime_token
from runtime.services.sessions import update_session_binding
from runtime.services.workspaces import register_workspace

from .schemas import (
    ClaimRequest,
    CleanupReceiptRequest,
    CompleteRequest,
    EventRequest,
    ExecutionCommand,
    FailRequest,
    MaterializationReceiptRequest,
    ProfileProvisioningRequest,
    SessionBindingRequest,
    StoppedRequest,
)
from .schemas import ProfileProvisioningReceipt as ProfileProvisioningReceiptSchema

_PROFILE_ID_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry-profile-v1")


class CloudServiceAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str):
        configured = getattr(settings, "ALLIES_CLOUD_SERVICE_TOKEN", None)
        if configured and secrets.compare_digest(token.encode(), configured.encode()):
            return token
        return None


_cloud_service_auth = CloudServiceAuth()


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

    @api.get("/runtime/profiles/reconciliation", auth=None)
    def profile_reconciliation(request: HttpRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            profiles = list_profile_reconciliation(context)
            return JsonResponse(
                {
                    "version": 1,
                    "workspace_id": str(context.workspace_id),
                    "machine_generation": context.machine_generation,
                    "profiles": [_profile_json(profile) for profile in profiles],
                },
                status=200,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/profiles/{profile_id}/materialization-receipt", auth=None)
    def materialization_receipt(
        request: HttpRequest,
        profile_id: UUID,
        payload: MaterializationReceiptRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            if payload.profile_id != profile_id:
                raise RuntimeValidationError(
                    "profile receipt identity does not match path"
                )
            receipt = accept_materialization_receipt(
                context,
                profile_id,
                payload.operation_id,
                payload.lifecycle_epoch,
                payload.materialized_generation,
                payload.seed_fingerprint,
                payload.result_code,
            )
            return JsonResponse(_profile_receipt_json(receipt), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/profiles/{profile_id}/cleanup-receipt", auth=None)
    def cleanup_receipt(
        request: HttpRequest,
        profile_id: UUID,
        payload: CleanupReceiptRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            if payload.profile_id != profile_id:
                raise RuntimeValidationError(
                    "profile receipt identity does not match path"
                )
            receipt = accept_cleanup_receipt(
                context,
                profile_id,
                payload.operation_id,
                payload.lifecycle_epoch,
                payload.request_digest,
                result_code=payload.result_code,
                deleted=payload.deleted,
                active_lease_count=payload.active_lease_count,
            )
            return JsonResponse(_profile_receipt_json(receipt), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/internal/profile-provisioning", auth=None)
    def profile_provisioning(
        request: HttpRequest,
        payload: ProfileProvisioningRequest,
    ):
        try:
            _authenticate_cloud_service(request)
            workspace = register_workspace(payload.workspace_id)
            profile = ensure_runtime_profile(
                workspace.id,
                _profile_id_for_binding(payload.binding_id),
                payload.ally_ref,
                ProfileSeed(
                    personality=payload.personality,
                    provider=settings.PROFILE_PROVISIONING_PROVIDER,
                    model=settings.PROFILE_PROVISIONING_MODEL,
                    base_url=settings.PROFILE_PROVISIONING_BASE_URL,
                    first_chat_instruction=_first_chat_instruction(
                        payload.name, payload.job
                    ),
                    credential_refs=settings.PROFILE_PROVISIONING_CREDENTIAL_REFS,
                ),
            )
            receipt = ProfileProvisioningReceiptSchema(
                version=payload.version,
                binding_id=payload.binding_id,
                operation_id=payload.operation_id,
                request_fingerprint=payload.request_fingerprint,
                status=profile.state,
                evidence_digest=profile.seed_fingerprint,
            )
            return JsonResponse(receipt.model_dump(), status=200)
        except RuntimeDomainError as exc:
            return _profile_provisioning_error(exc)

    @api.post("/internal/executions", auth=_cloud_service_auth)
    def execution_create(request: HttpRequest, payload: ExecutionCommand):
        try:
            receipt = create_execution_intent(payload)
            return JsonResponse(receipt.model_dump(mode="json"), status=200)
        except RuntimeDomainError as exc:
            return _execution_error(exc)

    @api.get("/internal/executions/reconcile", auth=_cloud_service_auth)
    def execution_reconcile(request: HttpRequest):
        try:
            receipt = reconcile_execution_intent(
                request.GET.get("idempotency_key", ""),
                request.GET.get("fingerprint", ""),
            )
            return JsonResponse(
                receipt.model_dump(mode="json", exclude_none=True),
                status=200,
            )
        except RuntimeDomainError as exc:
            return _execution_error(exc)

    @api.post("/runtime/attempts/{attempt_id}/lease/renew", auth=None)
    def renew(request: HttpRequest, attempt_id):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = renew_lease(context, attempt_id, _lease_token(request))
            return JsonResponse(
                {
                    "lease_id": str(receipt.lease_id),
                    "expires_at": _timestamp(receipt.expires_at),
                },
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
                context,
                attempt_id,
                _lease_token(request),
                payload.receipt,
                terminal_event={
                    "event_id": payload.event_id,
                    "stream_id": payload.stream_id,
                    "sequence": payload.sequence,
                    "payload": payload.payload,
                },
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
                terminal_event={
                    "event_id": payload.event_id,
                    "stream_id": payload.stream_id,
                    "sequence": payload.sequence,
                    "payload": payload.payload,
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


def _authenticate_cloud_service(request: HttpRequest) -> None:
    token = _bearer(request)
    configured = getattr(settings, "ALLIES_CLOUD_SERVICE_TOKEN", None)
    if not configured or not secrets.compare_digest(
        token.encode(), configured.encode()
    ):
        raise RuntimeAuthorizationError("invalid service credential")


def _profile_id_for_binding(binding_id: str) -> UUID:
    return uuid5(_PROFILE_ID_NAMESPACE, binding_id)


def _first_chat_instruction(name: str, job: str) -> str:
    identity = (
        f"Your name is {name}. When asked your name, answer with {name}. "
        "Do not identify yourself as Hermes; Hermes is only your private runtime. "
        if name
        else ""
    )
    return (
        identity
        + "Start the first chat by asking one useful question that helps with the "
        f"user's job. Job: {job}"
    )


def _profile_provisioning_error(exc: RuntimeDomainError) -> JsonResponse:
    if isinstance(exc, RuntimeAuthorizationError):
        return JsonResponse(
            {
                "code": "INVALID_CREDENTIAL",
                "message": "request is not authorized",
            },
            status=401,
        )
    if isinstance(exc, RuntimeValidationError):
        return JsonResponse(
            {"code": "INVALID_REQUEST", "message": "request is invalid"},
            status=422,
        )
    if isinstance(exc, RuntimeIdempotencyConflictError):
        code = "IDEMPOTENCY_CONFLICT"
    elif isinstance(exc, RuntimeConflictError):
        code = "CONFLICT"
    else:
        code = "PROFILE_UNAVAILABLE"
    return JsonResponse(
        {"code": code, "message": "profile provisioning conflicts with existing state"},
        status=409,
    )


def _execution_error(exc: RuntimeDomainError) -> JsonResponse:
    if isinstance(exc, RuntimeAuthorizationError):
        return JsonResponse(
            {"code": "INVALID_CREDENTIAL", "message": "request is not authorized"},
            status=401,
        )
    if isinstance(exc, RuntimeNotFoundError):
        return JsonResponse(
            {"code": "NOT_FOUND", "message": "execution binding is unavailable"},
            status=404,
        )
    if isinstance(exc, RuntimeValidationError):
        return JsonResponse(
            {"code": "INVALID_REQUEST", "message": "request is invalid"},
            status=422,
        )
    return JsonResponse(
        {
            "code": "CONFLICT",
            "message": "execution request conflicts with existing state",
        },
        status=409,
    )


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
        "model": claim.model,
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


def _profile_json(profile):
    return {
        "profile_id": str(profile.profile_id),
        "ally_ref": profile.ally_ref,
        "hermes_profile_key": profile.hermes_profile_key,
        "hermes_profile_key_version": profile.hermes_profile_key_version,
        "lifecycle_state": profile.lifecycle_state,
        "lifecycle_epoch": profile.lifecycle_epoch,
        "seed_version": profile.seed_version,
        "seed_fingerprint": profile.seed_fingerprint,
        "materialized_generation": profile.materialized_generation,
        "active_lease_count": profile.active_lease_count,
        "seed": profile.seed_payload,
        "materialization_operation_id": (
            str(profile.materialization_operation_id)
            if profile.materialization_operation_id
            else None
        ),
        "materialization_request_digest": profile.materialization_request_digest,
        "materialization_receipt_id": (
            str(profile.materialization_receipt_id)
            if profile.materialization_receipt_id
            else None
        ),
        "materialization_result_code": profile.materialization_result_code,
        "cleanup_operation_id": (
            str(profile.cleanup_operation_id) if profile.cleanup_operation_id else None
        ),
        "cleanup_context_digest": profile.cleanup_context_digest,
        "cleanup_request_digest": profile.cleanup_request_digest,
        "cleanup_receipt_id": (
            str(profile.cleanup_receipt_id) if profile.cleanup_receipt_id else None
        ),
        "cleanup_result_code": profile.cleanup_result_code,
        "cleanup_expires_at": (
            _timestamp(profile.cleanup_expires_at)
            if profile.cleanup_expires_at
            else None
        ),
    }


def _profile_receipt_json(receipt):
    return {
        "profile_id": str(receipt.profile_id),
        "lifecycle_state": receipt.lifecycle_state,
        "lifecycle_epoch": receipt.lifecycle_epoch,
        "materialized_generation": receipt.materialized_generation,
        "seed_fingerprint": receipt.seed_fingerprint,
        "receipt_id": str(receipt.receipt_id) if receipt.receipt_id else None,
        "result_code": receipt.result_code,
        "deleted": receipt.deleted,
        "active_lease_count": receipt.active_lease_count,
    }
