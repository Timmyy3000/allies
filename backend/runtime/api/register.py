import json
import secrets
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from django.core.management.base import CommandError
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from ninja.errors import ValidationError as NinjaValidationError
from ninja.security import HttpBearer
from ninja_extra import NinjaExtraAPI

from runtime.exceptions import (
    ActivityWaitSaturated,
    ActivityWaitUnavailable,
    RuntimeAuthorizationError,
    RuntimeConflictError,
    RuntimeDomainError,
    RuntimeIdempotencyConflictError,
    RuntimeNotFoundError,
    RuntimeValidationError,
)
from runtime.management.commands.activate_fly_workspace import (
    ActivationCommandError,
    WorkspaceNotRegisteredError,
)
from runtime.management.commands.activate_fly_workspace import (
    Command as ActivateFlyWorkspaceCommand,
)
from runtime.models import Workspace
from runtime.routine_contracts import (
    MAX_ROUTINE_EVENT_BYTES,
    RoutineApprovalDecision,
    RoutineCancelWait,
    RoutineDispatch,
    parse_routine_message,
    routine_message_bytes,
)
from runtime.services.activity import wait_for_workspace_activity
from runtime.services.approvals import (
    read_runtime_approval,
    record_approval_decision,
)
from runtime.services.attempts import complete_attempt, fail_attempt
from runtime.services.claims import claim_next_execution
from runtime.services.events import append_runtime_event
from runtime.services.executions import (
    create_execution_intent,
    reconcile_execution_intent,
)
from runtime.services.files import open_incoming_file
from runtime.services.leases import acknowledge_stopped, renew_lease
from runtime.services.profile_deletion import coordinate_profile_deletion
from runtime.services.profiles import (
    ProfileSeed,
    accept_cleanup_receipt,
    accept_materialization_receipt,
    ensure_runtime_profile,
    list_profile_reconciliation,
)
from runtime.services.publications import (
    MAX_PUBLICATION_FILE_BYTES,
    acknowledge_frozen_publication,
    claim_publication_retries,
    create_publication_intent,
    get_publication,
    record_publication_retry,
    register_publication,
    upload_publication_file,
)
from runtime.services.routine_tools import call_routine_tool, routine_tool_token
from runtime.services.routines import (
    accept_routine_dispatch,
    append_runtime_routine_result,
    cancel_routine_wait,
    decide_routine_approval,
)
from runtime.services.runtime_auth import authenticate_runtime_token
from runtime.services.runtime_intents import request_runtime_intent
from runtime.services.runtime_readiness import accept_runtime_readiness
from runtime.services.sessions import bind_routine_session, update_session_binding
from runtime.services.workspaces import register_workspace
from runtime.soul import render_default_allies_soul

from .schemas import (
    ApprovalDecisionCommand,
    ClaimRequest,
    CleanupReceiptRequest,
    CompleteRequest,
    EventRequest,
    ExecutionCommand,
    FailRequest,
    MaterializationReceiptRequest,
    ProfileDeletionRequest,
    ProfileDeletionResumeRequest,
    ProfileProvisioningRequest,
    PublicationFrozenRequest,
    PublicationIntentRequest,
    PublicationRegisterRequest,
    PublicationRetryClaimRequest,
    PublicationRetryResultRequest,
    RoutineSessionBindingRequest,
    RuntimeActivityWaitReceipt,
    RuntimeActivityWaitRequest,
    RuntimeIntentReceipt,
    RuntimeIntentRequest,
    RuntimeReadinessReceipt,
    RuntimeReadinessRequest,
    SessionBindingRequest,
    StoppedRequest,
    WorkspaceActivationReceipt,
    WorkspaceActivationRequest,
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

    @api.post("/runtime/routines/tool", auth=None)
    def routine_tool(request: HttpRequest):
        try:
            if len(request.body) > 64 * 1024:
                raise RuntimeValidationError("routine request too large")
            try:
                body = json.loads(request.body)
                if (
                    not isinstance(body, dict)
                    or set(body) != {"call_id", "arguments"}
                    or not isinstance(body["arguments"], dict)
                ):
                    raise ValueError("invalid fields")
                call_id = UUID(body["call_id"])
            except (ValueError, TypeError, KeyError) as exc:
                raise RuntimeValidationError("invalid routine request") from exc
            status, result = call_routine_tool(
                _bearer(request), call_id=call_id, arguments=body["arguments"]
            )
            return JsonResponse(result, status=status)
        except RuntimeDomainError as exc:
            return _error(exc)

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

    @api.post("/control/workspaces/{workspace_id}/runtime-intents", auth=None)
    def runtime_intent(
        request: HttpRequest,
        workspace_id: UUID,
        payload: RuntimeIntentRequest,
    ):
        try:
            _authenticate_cloud_service(request)
            idempotency_key = request.headers.get("Idempotency-Key", "")
            if not idempotency_key:
                raise RuntimeValidationError("Idempotency-Key is required")
            try:
                UUID(idempotency_key)
            except ValueError as exc:
                raise RuntimeValidationError("Idempotency-Key must be a UUID") from exc
            workspace = Workspace.objects.filter(tenant_ref=str(workspace_id)).first()
            if workspace is None:
                return JsonResponse({"status": "first_provision_required"}, status=200)
            receipt = request_runtime_intent(
                workspace.id,
                payload.intent,
                idempotency_key,
                payload.received_at,
            )
            response = RuntimeIntentReceipt(status=receipt.status)
            return JsonResponse(
                response.model_dump(mode="json"),
                status=202 if receipt.status == "waking" else 200,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/readiness", auth=None)
    def readiness(request: HttpRequest, payload: RuntimeReadinessRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = accept_runtime_readiness(
                context,
                payload.boot_id,
                payload.reconciled_generation,
                payload.runtime_start_epoch,
            )
            response = RuntimeReadinessReceipt(
                status=receipt.status,
                generation=receipt.generation,
                runtime_start_epoch=receipt.runtime_start_epoch,
                accepted_at=receipt.accepted_at,
            )
            return JsonResponse(response.model_dump(mode="json"), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.get("/runtime/profiles/reconciliation", auth=None)
    def profile_reconciliation(request: HttpRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            workspace = Workspace.objects.get(pk=context.workspace_id)
            profiles = list_profile_reconciliation(context)
            return JsonResponse(
                {
                    "version": 1,
                    "workspace_id": str(context.workspace_id),
                    "machine_generation": context.machine_generation,
                    "runtime_start_epoch": workspace.runtime_start_epoch,
                    "activity_revision": workspace.activity_revision,
                    "profiles": [_profile_json(profile) for profile in profiles],
                },
                status=200,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.get("/runtime/attempts/{attempt_id}/files/{file_id}/content", auth=None)
    def incoming_file_content(
        request: HttpRequest,
        attempt_id: UUID,
        file_id: UUID,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            content = open_incoming_file(
                context,
                attempt_id,
                _lease_token(request),
                file_id,
            )
            response = StreamingHttpResponse(
                content.chunks,
                content_type=content.content_type,
            )
            response["Content-Length"] = str(content.content_length)
            response["Cache-Control"] = "no-store"
            return response
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/file-publication-intents", auth=None)
    def publication_intent(
        request: HttpRequest,
        attempt_id: UUID,
        payload: PublicationIntentRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = create_publication_intent(
                context,
                attempt_id,
                _lease_token(request),
                payload.tool_call_id,
                [item.model_dump(mode="json") for item in payload.files],
            )
            return JsonResponse(
                {"publication_id": str(receipt.publication_id), "state": receipt.state},
                status=200,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post(
        "/runtime/profiles/{profile_id}/file-publication-intents/{publication_id}/frozen",
        auth=None,
    )
    def frozen_publication_intent(
        request: HttpRequest,
        profile_id: UUID,
        publication_id: UUID,
        payload: PublicationFrozenRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = acknowledge_frozen_publication(
                context,
                profile_id,
                publication_id,
                [item.model_dump(mode="json") for item in payload.files],
            )
            return JsonResponse(
                {"publication_id": str(receipt.publication_id), "state": receipt.state},
                status=200,
            )
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/file-publications", auth=None)
    def register_file_publication(
        request: HttpRequest,
        attempt_id: UUID,
        payload: PublicationRegisterRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            status, body = register_publication(
                context,
                attempt_id,
                _lease_token(request),
                payload.publication_id,
                [item.model_dump(mode="json") for item in payload.files],
            )
            return JsonResponse(body, status=status)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.put(
        "/runtime/profiles/{profile_id}/file-publications/{publication_id}/files/{file_id}/content",
        auth=None,
    )
    def upload_file_publication(
        request: HttpRequest,
        profile_id: UUID,
        publication_id: UUID,
        file_id: UUID,
        generation: int,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            revision = request.headers.get("X-Allies-Publication-Revision", "")
            try:
                revision_value = int(revision)
            except ValueError as exc:
                raise RuntimeValidationError("publication revision is invalid") from exc
            lease_value = request.headers.get("X-Allies-Publication-Lease-Token")
            lease_token = UUID(lease_value) if lease_value else None
            status, body = upload_publication_file(
                context,
                profile_id,
                publication_id,
                file_id,
                generation,
                request.read(MAX_PUBLICATION_FILE_BYTES + 1),
                revision_value,
                lease_token,
            )
            return JsonResponse(body, status=status)
        except (RuntimeDomainError, ValueError) as exc:
            return _error(
                exc
                if isinstance(exc, RuntimeDomainError)
                else RuntimeValidationError("publication lease token is invalid")
            )

    @api.get(
        "/runtime/profiles/{profile_id}/file-publications/{publication_id}", auth=None
    )
    def file_publication(request: HttpRequest, profile_id: UUID, publication_id: UUID):
        try:
            context = authenticate_runtime_token(_bearer(request))
            status, body = get_publication(context, profile_id, publication_id)
            return JsonResponse(body, status=status)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post(
        "/runtime/profiles/{profile_id}/file-publication-retries/claim", auth=None
    )
    def claim_file_publication_retries(
        request: HttpRequest, profile_id: UUID, payload: PublicationRetryClaimRequest
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            items = claim_publication_retries(context, profile_id, payload.limit)
            return JsonResponse({"items": list(items)}, status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post(
        "/runtime/profiles/{profile_id}/file-publications/{publication_id}/retry-result",
        auth=None,
    )
    def file_publication_retry_result(
        request: HttpRequest,
        profile_id: UUID,
        publication_id: UUID,
        payload: PublicationRetryResultRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            status, body = record_publication_retry(
                context,
                profile_id,
                publication_id,
                payload.revision,
                payload.lease_token,
                payload.outcome,
                payload.safe_error_code,
            )
            return JsonResponse(body, status=status)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/activity-waits", auth=None)
    def activity_wait(request: HttpRequest, payload: RuntimeActivityWaitRequest):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = wait_for_workspace_activity(
                context,
                payload.after_revision,
                payload.wait_seconds,
            )
            response = RuntimeActivityWaitReceipt(
                revision=receipt.revision,
                reason=receipt.reason,
            )
            return JsonResponse(response.model_dump(mode="json"), status=200)
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
                attempt_id=payload.attempt_id,
                machine_generation=payload.machine_generation,
                runtime_start_epoch=payload.runtime_start_epoch,
                runtime_boot_id=payload.runtime_boot_id,
                hermes_instance_id=payload.hermes_instance_id,
                quiescence=payload.quiescence.model_dump()
                if payload.quiescence
                else None,
            )
            return JsonResponse(_profile_receipt_json(receipt), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/internal/profile-deletion", auth=None)
    def profile_deletion(request: HttpRequest, payload: ProfileDeletionRequest):
        try:
            _authenticate_cloud_service(request)
            receipt = coordinate_profile_deletion(
                **payload.model_dump(exclude={"version"})
            )
            return JsonResponse(receipt, status=200)
        except RuntimeDomainError as exc:
            return _profile_provisioning_error(exc)

    @api.post("/internal/profile-deletion/resume", auth=None)
    def profile_deletion_resume(
        request: HttpRequest, payload: ProfileDeletionResumeRequest
    ):
        try:
            _authenticate_cloud_service(request)
            receipt = coordinate_profile_deletion(
                **payload.model_dump(exclude={"version"})
            )
            return JsonResponse(receipt, status=200)
        except RuntimeDomainError as exc:
            return _profile_provisioning_error(exc)

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
                    personality=render_default_allies_soul(
                        name=payload.name,
                        job=payload.job,
                        personality=payload.personality,
                    ),
                    provider=settings.PROFILE_PROVISIONING_PROVIDER,
                    model=settings.PROFILE_PROVISIONING_MODEL,
                    base_url=settings.PROFILE_PROVISIONING_BASE_URL,
                    first_chat_instruction=_first_chat_instruction(),
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

    @api.post("/internal/workspaces/{workspace_id}/activation", auth=None)
    def workspace_activation(
        request: HttpRequest,
        workspace_id: UUID,
        payload: WorkspaceActivationRequest,
    ):
        try:
            _authenticate_cloud_service(request)
            if payload.workspace_id != workspace_id:
                raise RuntimeValidationError("workspace identity does not match path")
            ActivateFlyWorkspaceCommand().handle(workspace_id=str(workspace_id))
        except RuntimeDomainError as exc:
            return _profile_provisioning_error(exc)
        except ActivationCommandError as exc:
            # A provider timeout may happen after a remote side effect. The
            # lifecycle command is resumable, so Cloud retries this workspace.
            if exc.retryable:
                return JsonResponse(
                    {
                        "version": 1,
                        "workspace_id": str(workspace_id),
                        "status": "pending",
                    },
                    status=202,
                )
            if exc.terminal:
                return JsonResponse(
                    {
                        "code": "ACTIVATION_FAILED",
                        "message": "workspace activation failed",
                    },
                    status=422,
                )
            return JsonResponse(
                {
                    "code": "ACTIVATION_UNAVAILABLE",
                    "message": "workspace activation unavailable",
                },
                status=503,
            )
        except WorkspaceNotRegisteredError:
            return JsonResponse(
                {"code": "WORKSPACE_NOT_FOUND", "message": "workspace is unavailable"},
                status=404,
            )
        except CommandError:
            return JsonResponse(
                {
                    "code": "ACTIVATION_UNAVAILABLE",
                    "message": "workspace activation unavailable",
                },
                status=503,
            )
        return JsonResponse(
            WorkspaceActivationReceipt(
                version=1,
                workspace_id=workspace_id,
                status="active",
            ).model_dump(mode="json"),
            status=200,
        )

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

    @api.post("/internal/routines/dispatch", auth=_cloud_service_auth)
    def routine_dispatch(request: HttpRequest):
        try:
            command = _routine_command(request, RoutineDispatch)
            receipt = accept_routine_dispatch(command)
            return JsonResponse(receipt.model_dump(mode="json"), status=200)
        except RuntimeDomainError as exc:
            return _routine_error(exc)

    @api.post("/internal/routines/approval-decision", auth=_cloud_service_auth)
    def routine_approval_decision(request: HttpRequest):
        try:
            command = _routine_command(request, RoutineApprovalDecision)
            receipt = decide_routine_approval(command)
            return JsonResponse(receipt.model_dump(mode="json"), status=200)
        except RuntimeDomainError as exc:
            return _routine_error(exc)

    @api.post("/internal/routines/cancel-wait", auth=_cloud_service_auth)
    def routine_cancel_wait(request: HttpRequest):
        try:
            command = _routine_command(request, RoutineCancelWait)
            receipt = cancel_routine_wait(command)
            return JsonResponse(
                {
                    "code": receipt.code,
                    "routine_execution_id": str(receipt.routine_execution_id),
                    "fence": receipt.fence,
                    "status": receipt.status,
                    "replayed": receipt.replayed,
                },
                status=200,
            )
        except RuntimeDomainError as exc:
            return _routine_error(exc)

    @api.post(
        "/internal/approvals/{approval_request_id}/decision", auth=_cloud_service_auth
    )
    def approval_decision(
        request: HttpRequest,
        approval_request_id: UUID,
        payload: ApprovalDecisionCommand,
    ):
        try:
            if payload.approval_request_id != approval_request_id:
                raise RuntimeValidationError("approval identity does not match path")
            receipt = record_approval_decision(payload)
            return JsonResponse(receipt.model_dump(mode="json"), status=200)
        except RuntimeDomainError as exc:
            return _execution_error(exc)

    @api.get(
        "/runtime/attempts/{attempt_id}/approval-requests/{approval_request_id}",
        auth=None,
    )
    def approval_status(
        request: HttpRequest,
        attempt_id: UUID,
        approval_request_id: UUID,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            status = read_runtime_approval(
                context,
                attempt_id,
                _lease_token(request),
                approval_request_id,
            )
            return JsonResponse(_approval_status_json(status), status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

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

    @api.put("/runtime/attempts/{attempt_id}/routine-session-binding", auth=None)
    def routine_session_binding(
        request: HttpRequest,
        attempt_id,
        payload: RoutineSessionBindingRequest,
    ):
        try:
            context = authenticate_runtime_token(_bearer(request))
            receipt = bind_routine_session(
                context,
                attempt_id,
                _lease_token(request),
                payload.expected_session_id,
                payload.effective_session_id,
            )
            return JsonResponse({"session_id": receipt.session_id}, status=200)
        except RuntimeDomainError as exc:
            return _error(exc)

    @api.post("/runtime/attempts/{attempt_id}/routine-result", auth=None)
    def routine_result(request: HttpRequest, attempt_id):
        try:
            context = authenticate_runtime_token(_bearer(request))
            body = _json_body(request)
            result = append_runtime_routine_result(
                context,
                attempt_id,
                _lease_token(request),
                event_id=body.get("event_id"),
                sequence=body.get("sequence"),
                outcome=body.get("outcome"),
                text=body.get("text"),
                references=body.get("references", []),
                delayed=body.get("delayed"),
            )
            return JsonResponse(result, status=200)
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


def _json_body(request: HttpRequest) -> dict:
    try:
        value = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeValidationError("request body must be JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeValidationError("request body must be an object")
    return value


def _routine_command(request: HttpRequest, expected_type):
    if len(request.body) > MAX_ROUTINE_EVENT_BYTES:
        raise RuntimeValidationError("routine message envelope is too large")
    command = parse_routine_message(_json_body(request))
    if not isinstance(command, expected_type):
        raise RuntimeValidationError("routine command kind is invalid")
    routine_message_bytes(command)
    return command


def _authenticate_cloud_service(request: HttpRequest) -> None:
    token = _bearer(request)
    configured = getattr(settings, "ALLIES_CLOUD_SERVICE_TOKEN", None)
    if not configured or not secrets.compare_digest(
        token.encode(), configured.encode()
    ):
        raise RuntimeAuthorizationError("invalid service credential")


def _profile_id_for_binding(binding_id: str) -> UUID:
    return uuid5(_PROFILE_ID_NAMESPACE, binding_id)


def _first_chat_instruction() -> str:
    return (
        "Treat the first conversation as the start of a working relationship. "
        "Respond naturally to the user's message. Do not repeat profile fields, "
        "explain your capabilities, present a menu, or force a metaphor or joke. "
        "Ask at most one natural question when it helps the conversation move."
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


def _routine_error(exc: RuntimeDomainError) -> JsonResponse:
    if isinstance(exc, RuntimeAuthorizationError):
        return JsonResponse(
            {"code": "INVALID_CREDENTIAL", "message": "request is not authorized"},
            status=401,
        )
    if isinstance(exc, RuntimeNotFoundError):
        return JsonResponse(
            {"code": "NOT_FOUND", "message": "routine binding is unavailable"},
            status=404,
        )
    if isinstance(exc, RuntimeValidationError):
        return JsonResponse(
            {"code": "INVALID_REQUEST", "message": "request is invalid"},
            status=422,
        )
    return JsonResponse(
        {
            "code": getattr(exc, "code", "CONFLICT"),
            "message": "routine request conflicts with existing state",
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
    elif isinstance(exc, RuntimeNotFoundError):
        status = 404
    elif isinstance(exc, RuntimeValidationError):
        status = 422
    elif isinstance(exc, ActivityWaitSaturated):
        status = 429
    elif isinstance(exc, ActivityWaitUnavailable):
        status = 503
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
        "command_id": str(claim.command_id) if claim.command_id is not None else None,
        "profile_id": str(claim.profile_id),
        "hermes_profile_key": claim.hermes_profile_key,
        "model": claim.model,
        "reasoning_effort": claim.reasoning_effort,
        "conversation_id": claim.conversation_id,
        "session_id": claim.session_id,
        "stream_id": claim.stream_id,
        "lease_id": str(claim.lease_id),
        "lease_token": claim.lease_token,
        "expires_at": _timestamp(claim.expires_at),
        "payload": claim.payload,
        "claim_id": str(claim.claim_id),
        "routine_id": str(claim.routine_id) if claim.routine_id is not None else None,
        "routine_tool_token": routine_tool_token(claim),
    }


def _terminal_json(receipt):
    return {
        "attempt_id": str(receipt.attempt_id),
        "status": receipt.status,
        "receipt_id": str(receipt.receipt_id),
        "requeued": receipt.requeued,
        "receipt": receipt.receipt,
    }


def _approval_status_json(status):
    return {
        "approval_request_id": str(status.approval_request_id),
        "status": status.status,
        "decision": status.decision,
        "decided_at": _timestamp(status.decided_at) if status.decided_at else None,
        "acknowledgement_deadline_at": (
            _timestamp(status.acknowledgement_deadline_at)
            if status.acknowledgement_deadline_at
            else None
        ),
        "expires_at": _timestamp(status.expires_at),
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
        "cleanup_requires_quiescence": profile.cleanup_requires_quiescence,
        "cleanup_attempt_id": str(profile.cleanup_attempt_id)
        if profile.cleanup_attempt_id
        else None,
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
