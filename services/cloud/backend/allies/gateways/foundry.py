from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import NAMESPACE_URL, UUID, uuid5

from django.conf import settings
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
)

from allies.exceptions import (
    FoundryGatewayConflict,
    FoundryGatewayInvalid,
    FoundryGatewayNotFound,
    FoundryGatewayRejected,
    FoundryGatewayRetryable,
    FoundryGatewayUnknownOutcome,
    ProvisioningRejected,
    ProvisioningRetryable,
)
from allies.services.onboarding import normalize_multiline_field
from common.uuids import canonical_uuid

from .contracts import (
    FINGERPRINT_PATTERN,
    ApprovalDecisionCommand,
    ApprovalDecisionReceipt,
    ExecutionCommand,
    ExecutionReceipt,
    ReconciliationReceipt,
    RoutineApprovalReceipt,
    RoutineCancelWaitReceipt,
    RoutineDispatchReceipt,
    canonical_json_bytes,
)

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
_ROUTINE_COMMAND_MAX_BYTES = 64 * 1024


class ProfileProvisioningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(default=1, ge=1, le=1)
    workspace_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    binding_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    ally_ref: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    operation_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    request_fingerprint: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    name: StrictStr = Field(min_length=1, max_length=80, pattern=r"^[^\x00\r]*$")
    job: StrictStr = Field(min_length=1, max_length=200, pattern=r"^[^\x00\r]*$")
    personality: StrictStr = Field(
        min_length=1, max_length=4000, pattern=r"^[^\x00\r]*$"
    )

    @field_validator("job", mode="before")
    @classmethod
    def _validate_job(cls, value: object) -> str:
        return normalize_multiline_field(value, max_length=200, canonicalize=False)

    @field_validator("personality", mode="before")
    @classmethod
    def _validate_personality(cls, value: object) -> str:
        return normalize_multiline_field(value, max_length=4000, canonicalize=False)


class ProfileProvisioningReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(ge=1, le=1)
    binding_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    operation_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    request_fingerprint: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    status: StrictStr = Field(
        pattern=r"^(pending|active|cleanup_pending|deprovisioned|repair_required)$"
    )
    evidence_digest: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class ProfileDeletionRequest(BaseModel):
    """Versioned, content-free Cloud to Foundry deletion identity."""

    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(default=1, ge=1, le=1)
    workspace_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    ally_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    binding_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    operation_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)


class ProfileDeletionReceipt(BaseModel):
    """Typed cleanup outcome; receipt IDs never contain Ally content."""

    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(ge=1, le=1)
    binding_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    operation_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    state: StrictStr = Field(pattern=r"^(pending|complete|repair_required)$")
    attempt_id: StrictStr | None = Field(
        default=None, min_length=36, max_length=36, pattern=_UUID_PATTERN
    )
    receipt_id: StrictStr | None = Field(
        default=None, min_length=36, max_length=36, pattern=_UUID_PATTERN
    )
    safe_error_code: StrictStr = Field(
        default="", max_length=64, pattern=r"^(?:[a-z][a-z0-9_]*)?$"
    )


class WorkspaceActivationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(ge=1, le=1)
    workspace_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    status: StrictStr = Field(pattern=r"^(pending|active)$")


class RuntimeIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: StrictStr = Field(pattern=r"^(composing_started|ally_creation_started)$")
    received_at: AwareDatetime


class RuntimeIntentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StrictStr = Field(
        pattern=(
            r"^(disabled|already_ready|waking|ready|first_provision_required|"
            r"rate_limited|failed)$"
        )
    )


class ProfileReadinessHint(BaseModel):
    """Content-free, authenticated readiness signal received from Foundry."""

    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(ge=1, le=1)
    hint_id: UUID
    workspace_id: UUID
    ally_ref: UUID
    runtime_profile_id: UUID
    generation: StrictInt = Field(ge=1)
    receipt_id: UUID
    occurred_at: AwareDatetime


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _foundry_origin() -> tuple[str, str]:
    origin = str(getattr(settings, "ALLIES_FOUNDRY_URL", "")).rstrip("/")
    token = str(getattr(settings, "ALLIES_FOUNDRY_SERVICE_TOKEN", ""))
    try:
        parsed = urlparse(origin)
        # A single-label hostname is a private Docker service name (self-hosted).
        local_http = parsed.scheme == "http" and (
            (
                bool(getattr(settings, "DEBUG", False))
                and parsed.hostname
                in {"localhost", "127.0.0.1", "host.docker.internal"}
            )
            or bool(parsed.hostname and "." not in parsed.hostname)
        )
        safe_origin = (
            (parsed.scheme == "https" or local_http)
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        safe_origin = False
    if not token or not safe_origin:
        raise FoundryGatewayRetryable("foundry unavailable")
    return origin, token


def _read_response(response) -> bytes:
    raw = response.read(65_537)
    if len(raw) > 65_536:
        raise FoundryGatewayInvalid("foundry response too large")
    return raw


def _request(
    *,
    method: str,
    path: str,
    body: bytes | None = None,
    query: Mapping[str, str] | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> bytes:
    origin, token = _foundry_origin()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra_headers:
        if set(extra_headers) - {"Idempotency-Key"}:
            raise FoundryGatewayInvalid("unsupported Foundry request header")
        for name, value in extra_headers.items():
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise FoundryGatewayInvalid("invalid Foundry request header")
            headers[name] = value
    suffix = f"?{urlencode(query)}" if query else ""
    request = Request(
        urljoin(origin + "/", path.lstrip("/")) + suffix,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with build_opener(_NoRedirect).open(
            request,
            timeout=float(getattr(settings, "ALLIES_FOUNDRY_TIMEOUT_SECONDS", 5.0)),
        ) as response:
            return _read_response(response)
    except HTTPError as exc:
        if exc.code in {408, 429} or exc.code >= 500:
            raise FoundryGatewayRetryable("foundry unavailable") from exc
        if exc.code == 401:
            raise FoundryGatewayRejected("foundry rejected request") from exc
        if exc.code == 404:
            raise FoundryGatewayNotFound("foundry resource unavailable") from exc
        if exc.code == 409:
            raise FoundryGatewayConflict("foundry request conflicts") from exc
        if exc.code == 422:
            raise FoundryGatewayInvalid("foundry request is invalid") from exc
        raise FoundryGatewayRejected("foundry rejected request") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise FoundryGatewayUnknownOutcome("foundry outcome unknown") from exc


def _receipt(raw: bytes) -> ExecutionReceipt:
    try:
        return ExecutionReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry response invalid") from exc


def create_execution_intent(
    command: ExecutionCommand, *, raw_body: bytes | None = None
) -> ExecutionReceipt:
    """Submit one exact command; retries may pass the persisted bytes directly."""

    canonical_body = canonical_json_bytes(command.model_dump(mode="json"))
    if raw_body is not None and (
        not isinstance(raw_body, bytes) or raw_body != canonical_body
    ):
        raise FoundryGatewayInvalid("foundry command bytes are not canonical")
    body = raw_body if raw_body is not None else canonical_body
    if len(body) > 64 * 1024:
        raise FoundryGatewayInvalid("foundry command too large")
    return _receipt(
        _request(method="POST", path="api/v1/internal/executions", body=body)
    )


def _routine_command_body(
    command: bytes | Mapping[str, Any] | BaseModel | None,
    *,
    raw_body: bytes | None,
    expected_kind: str,
    operation: str,
) -> bytes:
    not_canonical = f"foundry {operation} bytes are not canonical"
    invalid = f"foundry {operation} command is invalid"
    if raw_body is not None and not isinstance(raw_body, bytes):
        raise FoundryGatewayInvalid(not_canonical)
    if raw_body is not None:
        if isinstance(command, bytes) and command != raw_body:
            raise FoundryGatewayInvalid(not_canonical)
        if command is not None and not isinstance(command, bytes):
            try:
                value = (
                    command.model_dump(mode="json")
                    if isinstance(command, BaseModel)
                    else dict(command)
                )
                expected_body = canonical_json_bytes(value)
            except (TypeError, ValueError) as exc:
                raise FoundryGatewayInvalid(invalid) from exc
            if raw_body != expected_body:
                raise FoundryGatewayInvalid(not_canonical)
        body = raw_body
    elif isinstance(command, bytes):
        body = command
    elif command is None:
        raise FoundryGatewayInvalid(invalid)
    else:
        try:
            value = (
                command.model_dump(mode="json")
                if isinstance(command, BaseModel)
                else dict(command)
            )
            body = canonical_json_bytes(value)
        except (TypeError, ValueError) as exc:
            raise FoundryGatewayInvalid(invalid) from exc

    if len(body) > _ROUTINE_COMMAND_MAX_BYTES:
        raise FoundryGatewayInvalid(f"foundry {operation} command too large")
    try:
        parsed = json.loads(body)
        canonical_body = canonical_json_bytes(parsed)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise FoundryGatewayInvalid(invalid) from exc
    if not isinstance(parsed, dict) or body != canonical_body:
        raise FoundryGatewayInvalid(not_canonical)
    if parsed.get("kind") != expected_kind:
        raise FoundryGatewayInvalid(invalid)
    return body


def accept_routine_dispatch(
    command: bytes | Mapping[str, Any] | BaseModel | None = None,
    *,
    raw_body: bytes | None = None,
) -> RoutineDispatchReceipt:
    """Deliver one persisted rev9 routine.dispatch envelope to Foundry."""

    body = _routine_command_body(
        command,
        raw_body=raw_body,
        expected_kind="routine.dispatch",
        operation="routine dispatch",
    )
    raw = _request(
        method="POST",
        path="api/v1/internal/routines/dispatch",
        body=body,
    )
    try:
        return RoutineDispatchReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry routine dispatch receipt invalid") from exc


def decide_routine_approval(
    command: bytes | Mapping[str, Any] | BaseModel | None = None,
    *,
    raw_body: bytes | None = None,
) -> RoutineApprovalReceipt:
    """Deliver one persisted rev9 routine.approval_decision envelope."""

    body = _routine_command_body(
        command,
        raw_body=raw_body,
        expected_kind="routine.approval_decision",
        operation="routine approval",
    )
    raw = _request(
        method="POST",
        path="api/v1/internal/routines/approval-decision",
        body=body,
    )
    try:
        return RoutineApprovalReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry routine approval receipt invalid") from exc


def cancel_routine_wait(
    command: bytes | Mapping[str, Any] | BaseModel | None = None,
    *,
    raw_body: bytes | None = None,
) -> RoutineCancelWaitReceipt:
    """Deliver one persisted rev9 routine.cancel_wait envelope."""

    body = _routine_command_body(
        command,
        raw_body=raw_body,
        expected_kind="routine.cancel_wait",
        operation="routine cancel-wait",
    )
    raw = _request(
        method="POST",
        path="api/v1/internal/routines/cancel-wait",
        body=body,
    )
    try:
        return RoutineCancelWaitReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid(
            "foundry routine cancel-wait receipt invalid"
        ) from exc


def stop_conversation(conversation_id: UUID) -> int:
    raw = _request(
        method="POST",
        path=f"api/v1/internal/conversations/{conversation_id}/stop",
    )
    try:
        stopped = json.loads(raw)["stopped"]
    except (ValueError, TypeError, KeyError):
        raise FoundryGatewayInvalid("foundry stop receipt invalid") from None
    if type(stopped) is not int or stopped < 0:
        raise FoundryGatewayInvalid("foundry stop receipt invalid")
    return stopped


def submit_approval_decision(
    command: ApprovalDecisionCommand, *, raw_body: bytes | None = None
) -> ApprovalDecisionReceipt:
    """Deliver one immutable Cloud approval choice to its Foundry request."""

    canonical_body = canonical_json_bytes(command.model_dump(mode="json"))
    if raw_body is not None and (
        not isinstance(raw_body, bytes) or raw_body != canonical_body
    ):
        raise FoundryGatewayInvalid("foundry approval bytes are not canonical")
    body = raw_body if raw_body is not None else canonical_body
    if len(body) > 64 * 1024:
        raise FoundryGatewayInvalid("foundry approval command too large")
    raw = _request(
        method="POST",
        path=f"api/v1/internal/approvals/{command.approval_request_id}/decision",
        body=body,
        extra_headers={"Idempotency-Key": str(command.idempotency_key)},
    )
    try:
        return ApprovalDecisionReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry approval receipt invalid") from exc


def reconcile_execution_intent(
    idempotency_key, fingerprint: str
) -> ReconciliationReceipt:
    """Look up an execution without creating work."""

    try:
        key = UUID(str(idempotency_key))
    except (TypeError, ValueError) as exc:
        raise FoundryGatewayInvalid("idempotency identity is invalid") from exc
    if not isinstance(fingerprint, str) or not re.fullmatch(
        FINGERPRINT_PATTERN, fingerprint
    ):
        raise FoundryGatewayInvalid("fingerprint is invalid")
    raw = _request(
        method="GET",
        path="api/v1/internal/executions/reconcile",
        query={"idempotency_key": str(key), "fingerprint": fingerprint},
    )
    try:
        return ReconciliationReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry reconciliation response invalid") from exc


def request_runtime_intent(
    *,
    workspace_id: UUID | str,
    intent: str,
    received_at: datetime,
    idempotency_key: UUID | str,
) -> RuntimeIntentReceipt:
    """Forward one content-free wake hint to Foundry."""

    try:
        parsed_workspace_id = canonical_uuid(workspace_id)
        parsed_key = canonical_uuid(idempotency_key)
    except (TypeError, ValueError) as exc:
        raise FoundryGatewayInvalid("runtime intent identity is invalid") from exc
    payload = RuntimeIntentRequest(intent=intent, received_at=received_at)
    raw = _request(
        method="POST",
        path=f"api/v1/control/workspaces/{parsed_workspace_id}/runtime-intents",
        body=payload.model_dump_json().encode(),
        extra_headers={"Idempotency-Key": str(parsed_key)},
    )
    try:
        return RuntimeIntentReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry runtime intent response invalid") from exc


def provision_profile(
    payload: ProfileProvisioningRequest,
) -> ProfileProvisioningReceipt:
    try:
        origin, token = _foundry_origin()
    except FoundryGatewayRetryable as exc:
        raise ProvisioningRetryable("foundry unavailable") from exc
    request = Request(
        urljoin(origin.rstrip("/") + "/", "api/v1/internal/profile-provisioning"),
        data=payload.model_dump_json().encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with build_opener(_NoRedirect).open(
            request,
            timeout=float(getattr(settings, "ALLIES_FOUNDRY_TIMEOUT_SECONDS", 5.0)),
        ) as response:
            raw = response.read(65_537)
            if len(raw) > 65_536:
                raise ProvisioningRejected("foundry response too large")
    except HTTPError as exc:
        if exc.code in {408, 429} or exc.code >= 500:
            raise ProvisioningRetryable("foundry unavailable") from exc
        raise ProvisioningRejected("foundry rejected request") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise ProvisioningRetryable("foundry outcome unknown") from exc
    try:
        return ProfileProvisioningReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise ProvisioningRejected("foundry response invalid") from exc


def request_profile_deletion(
    payload: ProfileDeletionRequest,
) -> ProfileDeletionReceipt:
    """Ask Foundry to quiesce and purge one exact profile identity."""

    try:
        body = canonical_json_bytes(payload.model_dump(mode="json"))
    except (TypeError, ValueError) as exc:
        raise FoundryGatewayInvalid("foundry deletion request invalid") from exc
    raw = _request(
        method="POST",
        path="api/v1/internal/profile-deletion",
        body=body,
    )
    try:
        return ProfileDeletionReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry deletion receipt invalid") from exc


def resume_profile_deletion(
    *,
    payload: ProfileDeletionRequest,
    expected_attempt_id: UUID,
) -> ProfileDeletionReceipt:
    """Resume one failed Foundry deletion attempt with the same scope."""

    try:
        attempt_id = canonical_uuid(expected_attempt_id)
        body = canonical_json_bytes(
            {
                **payload.model_dump(mode="json"),
                "expected_attempt_id": str(attempt_id),
            }
        )
    except (TypeError, ValueError) as exc:
        raise FoundryGatewayInvalid("foundry deletion resume invalid") from exc
    raw = _request(
        method="POST",
        path="api/v1/internal/profile-deletion/resume",
        body=body,
    )
    try:
        return ProfileDeletionReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise FoundryGatewayInvalid("foundry deletion resume receipt invalid") from exc


def activate_workspace(workspace_id: str) -> WorkspaceActivationReceipt:
    """Ask Foundry to start/resume the workspace Fly lifecycle."""

    try:
        payload = {"version": 1, "workspace_id": workspace_id}
        raw = _request(
            method="POST",
            path=f"api/v1/internal/workspaces/{workspace_id}/activation",
            body=canonical_json_bytes(payload),
        )
    except (FoundryGatewayRetryable, FoundryGatewayUnknownOutcome) as exc:
        raise ProvisioningRetryable("foundry activation unavailable") from exc
    except (FoundryGatewayNotFound, FoundryGatewayConflict) as exc:
        # Rollout skew or a provider-side in-flight conflict is retryable for
        # the durable provisioning operation; never crash the dispatch batch.
        raise ProvisioningRetryable("foundry activation unavailable") from exc
    except (FoundryGatewayInvalid, FoundryGatewayRejected) as exc:
        raise ProvisioningRejected("foundry activation rejected") from exc
    try:
        return WorkspaceActivationReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise ProvisioningRejected("foundry activation response invalid") from exc


_FOUNDRY_PROFILE_NAMESPACE = uuid5(NAMESPACE_URL, "allies-foundry-profile-v1")


def foundry_profile_id(binding_id: UUID | str) -> UUID:
    """Mirror Foundry's profile identity for a provisioned Ally binding."""

    return uuid5(_FOUNDRY_PROFILE_NAMESPACE, str(binding_id))


def set_model_binding(profile_id: UUID, binding: Mapping[str, Any]) -> int:
    raw = _request(
        method="PUT",
        path=f"/api/v1/internal/profiles/{profile_id}/model-binding",
        body=canonical_json_bytes({"profile_id": str(profile_id), **binding}),
    )
    return _binding_generation(raw)


def clear_model_binding(profile_id: UUID) -> int:
    raw = _request(
        method="DELETE",
        path=f"/api/v1/internal/profiles/{profile_id}/model-binding",
    )
    return _binding_generation(raw)


def _binding_generation(raw: bytes) -> int:
    try:
        generation = json.loads(raw)["generation"]
    except (ValueError, TypeError, KeyError):
        raise FoundryGatewayInvalid("foundry binding receipt invalid") from None
    if type(generation) is not int or generation < 1:
        raise FoundryGatewayInvalid("foundry binding receipt invalid")
    return generation
