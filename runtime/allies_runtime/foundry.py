"""Outbound Foundry runtime API client and bounded worker.

The runtime deliberately keeps this module independent from Django.  The
client speaks the small ``/api/v1/runtime`` contract using an injected
transport in tests (or a standard-library HTTP transport in production).  A
worker slot owns one claim until a terminal receipt or a stopped receipt is
durably acknowledged.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .errors import (
    HermesDisconnected,
    HermesError,
    HermesHistoryMismatch,
    HermesMalformedResponse,
    HermesTimeout,
)
from .hermes import (
    HermesBootstrap,
    HermesEvent,
    stable_session_identifiers,
    validate_reasoning_effort,
    validate_stream_message,
)
from .observability import (
    build_event,
    emit_runtime_event,
    observe_runtime_operation,
)

MAX_CLAIM_SLOTS = 8
# Sequence 100001 is reserved for the single terminal event emitted when the
# runtime exhausts its ordinary event budget.
MAX_RUNTIME_EVENT_SEQUENCE = 100000
MAX_TERMINAL_SEQUENCE = 100001
MAX_ROUTINE_REFERENCE_COUNT = 32
MAX_ROUTINE_TEXT_BYTES = 16 * 1024
MAX_ROUTINE_EVENT_BYTES = 64 * 1024
# Reserve space for the fixed routine envelope and execution snapshots when
# preflighting the variable text/reference portion in the runtime image.
MAX_ROUTINE_RESULT_FIXED_BYTES = 4 * 1024
LEASE_SECONDS = 60.0
DEFAULT_RENEW_INTERVAL = 20.0
DEFAULT_STOP_SAFETY_MARGIN = 5.0
DEFAULT_PROFILE_RECONCILE_INTERVAL = 5.0
MAX_PROFILE_RECONCILIATION_RETRY_DELAY = 5.0
MIN_IDLE_BACKOFF_SECONDS = 1.0
MAX_IDLE_BACKOFF_SECONDS = 10.0
IDLE_BACKOFF_JITTER_RATIO = 0.25
POST_MATERIALIZATION_FAST_POLLS = 8
APPROVAL_POLL_INTERVAL = 0.5
APPROVAL_ACKNOWLEDGEMENT_SECONDS = 30.0
MAX_APPROVAL_LIFETIME_SECONDS = 300.0
MAX_APPROVAL_LABEL_CHARS = 120
MAX_APPROVAL_PREVIEW_BYTES = 16 * 1024


def _jittered_idle_delay(base: float, minimum: float) -> float:
    bounded = min(MAX_IDLE_BACKOFF_SECONDS, max(minimum, base))
    return max(
        minimum,
        bounded * (1 - random.random() * IDLE_BACKOFF_JITTER_RATIO),
    )


def _approval_request_id(attempt_id: str, run_id: str, hermes_id: str) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            f"allies-foundry:approval:v1:{attempt_id}:{run_id}:{hermes_id}",
        )
    )


def _approval_time(value: Any) -> float:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise HermesMalformedResponse("Hermes approval expiry was invalid") from exc
    else:
        raise HermesMalformedResponse("Hermes approval expiry was invalid")
    if parsed.tzinfo is None:
        raise HermesMalformedResponse("Hermes approval expiry was invalid")
    return parsed.timestamp()


def _routine_references(
    value: Any,
    *,
    text: str | None = None,
) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_ROUTINE_REFERENCE_COUNT:
        raise HermesMalformedResponse("Hermes routine references were malformed")
    references: list[dict[str, str]] = []
    for reference in value:
        if not isinstance(reference, Mapping) or set(reference) != {"label", "url"}:
            raise HermesMalformedResponse("Hermes routine references were malformed")
        label = reference.get("label")
        url = reference.get("url")
        if (
            not isinstance(label, str)
            or not 1 <= len(label.encode("utf-8")) <= 255
            or "\x00" in label
            or not isinstance(url, str)
            or not 1 <= len(url.encode("utf-8")) <= 2048
            or "\x00" in url
            or not url.startswith(("http://", "https://"))
        ):
            raise HermesMalformedResponse("Hermes routine references were malformed")
        references.append({"label": label, "url": url})
    if text is not None:
        if not isinstance(text, str):
            raise HermesMalformedResponse("Hermes routine result text was malformed")
        variable_payload = json.dumps(
            {"references": references, "text": text},
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if (
            len(variable_payload) + MAX_ROUTINE_RESULT_FIXED_BYTES
            > MAX_ROUTINE_EVENT_BYTES
        ):
            raise HermesMalformedResponse(
                "Hermes routine result envelope was too large"
            )
    return references


class _BootstrapResponseLost(HermesError):
    code = "bootstrap_response_lost"


class FoundryTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any] | None = None,
    ) -> Any: ...


class FoundryError(RuntimeError):
    """A bounded, typed Foundry response failure."""

    status = 0
    code = "FOUNDRY_ERROR"
    retryable = False

    def __init__(
        self,
        message: str = "Foundry request failed",
        *,
        status: int = 0,
        code: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        if code:
            self.code = code


class InvalidCredentialError(FoundryError):
    status = 401
    code = "INVALID_CREDENTIAL"


class FencedError(FoundryError):
    status = 409
    code = "FENCED"


class NotReadyError(FoundryError):
    status = 409
    code = "NOT_READY"


class LeaseConflictError(FoundryError):
    status = 409
    code = "LEASE_CONFLICT"


class IdempotencyConflictError(FoundryError):
    status = 409
    code = "IDEMPOTENCY_CONFLICT"


class RepairRequiredError(FoundryError):
    status = 409
    code = "REPAIR_REQUIRED"


class InvalidRequestError(FoundryError):
    status = 422
    code = "INVALID_REQUEST"


class RateLimitedError(FoundryError):
    status = 429
    code = "RATE_LIMITED"
    retryable = True


class ServiceUnavailableError(FoundryError):
    status = 503
    code = "SERVICE_UNAVAILABLE"
    retryable = True


class ResponseLossError(FoundryError):
    """The request may have committed but its response was lost.

    Callers must retry with the same claim/event/terminal identity.  The
    message intentionally contains no URL, token, or provider detail.
    """

    code = "RESPONSE_LOST"
    retryable = True


# Friendly aliases used by integrations that prefer the API terminology.
FoundryInvalidCredential = InvalidCredentialError
FoundryFenced = FencedError
FoundryNotReady = NotReadyError
FoundryLeaseConflict = LeaseConflictError
FoundryIdempotencyConflict = IdempotencyConflictError
FoundryRepairRequired = RepairRequiredError
FoundryInvalidRequest = InvalidRequestError
FoundryRateLimited = RateLimitedError
FoundryUnavailable = ServiceUnavailableError
FoundryResponseLoss = ResponseLossError


@dataclass(frozen=True, slots=True)
class FoundryClaim:
    attempt_id: str
    execution_id: str
    profile_id: str
    hermes_profile_key: str
    model: str
    conversation_id: str | None
    session_id: str | None
    stream_id: str
    lease_id: str
    lease_token: str
    expires_at: datetime | str | None
    payload: Mapping[str, Any]
    claim_id: str
    routine_id: str | None = None
    reasoning_effort: str | None = None
    routine_tool_token: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        return (
            "FoundryClaim("
            f"attempt_id={self.attempt_id!r}, "
            f"profile_id={self.profile_id!r}, lease_token=<redacted>, "
            f"claim_id={self.claim_id!r})"
        )

    @property
    def message(self) -> str:
        value = self.payload.get("message", "")
        return value if isinstance(value, str) else str(value)


@dataclass(frozen=True, slots=True)
class ProfileDesiredState:
    """Sanitized Foundry desired state for one volume profile."""

    machine_generation: int
    profile_id: str
    ally_ref: str
    hermes_profile_key: str
    hermes_profile_key_version: int
    lifecycle_state: str
    lifecycle_epoch: int
    seed_version: int
    seed_fingerprint: str
    materialized_generation: int
    seed: Mapping[str, Any]
    materialization_operation_id: str | None
    materialization_request_digest: str
    materialization_receipt_id: str | None
    materialization_result_code: str
    cleanup_operation_id: str | None
    cleanup_context_digest: str
    cleanup_request_digest: str
    cleanup_receipt_id: str | None
    cleanup_result_code: str
    cleanup_expires_at: datetime | str | None
    active_lease_count: int = 0

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        return (
            "ProfileDesiredState("
            f"profile_id={self.profile_id!r}, "
            f"hermes_profile_key={self.hermes_profile_key!r}, "
            f"lifecycle_state={self.lifecycle_state!r}, "
            f"seed_fingerprint={self.seed_fingerprint!r}, seed=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class RuntimeReconciliationSnapshot:
    """Authenticated current-generation state used for readiness fencing."""

    machine_generation: int
    runtime_start_epoch: int | None
    profiles: tuple[ProfileDesiredState, ...]
    activity_revision: int = 0
    workspace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActivityWaitReceipt:
    revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class ProfileReceipt:
    profile_id: str
    lifecycle_state: str
    lifecycle_epoch: int
    materialized_generation: int
    seed_fingerprint: str
    receipt_id: str | None
    result_code: str
    deleted: bool = False
    active_lease_count: int = 0


@dataclass(frozen=True, slots=True)
class LeaseReceipt:
    lease_id: str
    expires_at: datetime | str | None


@dataclass(frozen=True, slots=True)
class EventReceipt:
    event_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class StoppedReceipt:
    attempt_id: str
    state: str
    requeued: bool


@dataclass(frozen=True, slots=True)
class TerminalReceipt:
    attempt_id: str
    status: str
    receipt_id: str
    requeued: bool = False
    receipt: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SessionReceipt:
    session_id: str


@dataclass(frozen=True, slots=True)
class ApprovalStatus:
    approval_request_id: str
    status: str
    decision: str | None
    decided_at: datetime | str | None
    acknowledgement_deadline_at: datetime | str | None
    expires_at: datetime | str | None


def deterministic_event_id(
    attempt_id: str | UUID, stream_id: str, sequence: int
) -> str:
    """Return the stable UUID used for an Attempt stream event."""

    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not 1 <= sequence <= MAX_TERMINAL_SEQUENCE
    ):
        raise ValueError(
            f"event sequence must be an integer from 1 to {MAX_TERMINAL_SEQUENCE}"
        )
    if not isinstance(stream_id, str) or not stream_id or len(stream_id) > 255:
        raise ValueError("stream_id must be a bounded non-empty string")
    return str(
        uuid5(
            NAMESPACE_URL, f"allies-foundry:event:{attempt_id}:{stream_id}:{sequence}"
        )
    )


class UrllibFoundryTransport:
    """Small async wrapper around ``urllib`` for the runtime image."""

    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        if not isinstance(base_url, str) or not base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("Foundry base URL must be an HTTP origin")
        self.base_url = base_url.rstrip("/")
        if timeout <= 0 or timeout > 60:
            raise ValueError("Foundry timeout must be bounded")
        self.timeout = timeout

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        payload = (
            None
            if body is None
            else json.dumps(body, separators=(",", ":")).encode("utf-8")
        )

        def send() -> Mapping[str, Any]:
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=payload,
                method=method,
                headers={**headers, "Content-Type": "application/json"}
                if payload is not None
                else dict(headers),
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return {"status": response.status, "body": response.read(1_048_577)}
            except urllib.error.HTTPError as exc:
                return {"status": exc.code, "body": exc.read(1_048_577)}

        return await asyncio.to_thread(send)


def _parse_response(raw: Any) -> tuple[int, Mapping[str, Any] | None]:
    """Normalize common fake transport response shapes without leaking data."""

    if raw is None:
        return 204, None
    if isinstance(raw, tuple) and len(raw) == 2:
        status, payload = raw
        return int(status), payload if isinstance(payload, Mapping) else None
    if isinstance(raw, Mapping):
        status_value = raw.get("status", raw.get("status_code"))
        if isinstance(status_value, int):
            payload = raw.get("body", raw.get("payload"))
            if isinstance(payload, bytes):
                try:
                    payload = json.loads(payload.decode("utf-8")) if payload else None
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise InvalidRequestError(
                        "Foundry returned malformed JSON", status=int(status_value)
                    ) from exc
            return int(status_value), payload if isinstance(payload, Mapping) else None
        return 200, raw
    status = getattr(raw, "status", getattr(raw, "status_code", 200))
    payload = getattr(raw, "payload", None)
    if payload is None:
        payload = getattr(raw, "body", None)
    if payload is None and callable(getattr(raw, "json", None)):
        payload = raw.json()
    if isinstance(payload, bytes):
        try:
            payload = json.loads(payload.decode("utf-8")) if payload else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidRequestError(
                "Foundry returned malformed JSON", status=int(status)
            ) from exc
    return int(status), payload if isinstance(payload, Mapping) else None


def _parse_datetime(value: Any) -> datetime | str | None:
    if not isinstance(value, str):
        return value if isinstance(value, datetime) else None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def _profile_desired_state(value: Any, machine_generation: int) -> ProfileDesiredState:
    if not isinstance(value, Mapping):
        raise FoundryError(
            "Foundry profile reconciliation response was malformed",
            status=200,
            code="MALFORMED_RESPONSE",
        )
    required = (
        "profile_id",
        "ally_ref",
        "hermes_profile_key",
        "lifecycle_state",
        "lifecycle_epoch",
        "seed_version",
        "seed_fingerprint",
        "materialized_generation",
        "seed",
    )
    if any(key not in value for key in required) or not isinstance(
        value.get("seed"), Mapping
    ):
        raise FoundryError(
            "Foundry profile reconciliation response was malformed",
            status=200,
            code="MALFORMED_RESPONSE",
        )
    try:
        return ProfileDesiredState(
            machine_generation=machine_generation,
            profile_id=str(value["profile_id"]),
            ally_ref=str(value["ally_ref"]),
            hermes_profile_key=str(value["hermes_profile_key"]),
            hermes_profile_key_version=int(value.get("hermes_profile_key_version", 1)),
            lifecycle_state=str(value["lifecycle_state"]),
            lifecycle_epoch=int(value["lifecycle_epoch"]),
            seed_version=int(value["seed_version"]),
            seed_fingerprint=str(value["seed_fingerprint"]),
            materialized_generation=int(value["materialized_generation"]),
            seed=dict(value["seed"]),
            materialization_operation_id=_optional_text(
                value.get("materialization_operation_id")
            ),
            materialization_request_digest=str(
                value.get("materialization_request_digest", "")
            ),
            materialization_receipt_id=_optional_text(
                value.get("materialization_receipt_id")
            ),
            materialization_result_code=str(
                value.get("materialization_result_code", "")
            ),
            cleanup_operation_id=_optional_text(value.get("cleanup_operation_id")),
            cleanup_context_digest=str(value.get("cleanup_context_digest", "")),
            cleanup_request_digest=str(value.get("cleanup_request_digest", "")),
            cleanup_receipt_id=_optional_text(value.get("cleanup_receipt_id")),
            cleanup_result_code=str(value.get("cleanup_result_code", "")),
            cleanup_expires_at=_parse_datetime(value.get("cleanup_expires_at")),
            active_lease_count=int(value.get("active_lease_count", 0)),
        )
    except (TypeError, ValueError):
        raise FoundryError(
            "Foundry profile reconciliation response was malformed",
            status=200,
            code="MALFORMED_RESPONSE",
        ) from None


def _profile_receipt(value: Mapping[str, Any] | None) -> ProfileReceipt:
    if not value or any(
        key not in value
        for key in (
            "profile_id",
            "lifecycle_state",
            "lifecycle_epoch",
            "materialized_generation",
            "seed_fingerprint",
            "result_code",
        )
    ):
        raise FoundryError(
            "Foundry profile receipt response was malformed",
            status=200,
            code="MALFORMED_RESPONSE",
        )
    try:
        return ProfileReceipt(
            profile_id=str(value["profile_id"]),
            lifecycle_state=str(value["lifecycle_state"]),
            lifecycle_epoch=int(value["lifecycle_epoch"]),
            materialized_generation=int(value["materialized_generation"]),
            seed_fingerprint=str(value["seed_fingerprint"]),
            receipt_id=_optional_text(value.get("receipt_id")),
            result_code=str(value["result_code"]),
            deleted=bool(value.get("deleted", False)),
            active_lease_count=int(value.get("active_lease_count", 0)),
        )
    except (TypeError, ValueError):
        raise FoundryError(
            "Foundry profile receipt response was malformed",
            status=200,
            code="MALFORMED_RESPONSE",
        ) from None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("optional value must be a non-empty string")
    return value


def _error_for(status: int, payload: Mapping[str, Any] | None) -> FoundryError:
    code = str(payload.get("code", "")) if payload else ""
    message = "Foundry rejected the runtime request"
    if status == 401:
        return InvalidCredentialError(message, status=status, code="INVALID_CREDENTIAL")
    if status == 422:
        return InvalidRequestError(message, status=status, code="INVALID_REQUEST")
    if status == 429:
        return RateLimitedError(message, status=status, code=code or "RATE_LIMITED")
    if status == 503 or status >= 500:
        return ServiceUnavailableError(
            message, status=status, code=code or "SERVICE_UNAVAILABLE"
        )
    if status == 409:
        classes = {
            "FENCED": FencedError,
            "NOT_READY": NotReadyError,
            "LEASE_CONFLICT": LeaseConflictError,
            "IDEMPOTENCY_CONFLICT": IdempotencyConflictError,
            "REPAIR_REQUIRED": RepairRequiredError,
        }
        cls = classes.get(code, FoundryError)
        return cls(
            message, status=status, code=code or getattr(cls, "code", "CONFLICT")
        )
    return FoundryError(message, status=status, code=code or "FOUNDRY_ERROR")


class FoundryClient:
    """Bearer-authenticated client for the internal Foundry runtime API."""

    def __init__(
        self,
        base_url: str | None = None,
        runtime_token: str | None = None,
        *,
        token: str | None = None,
        transport: FoundryTransport | Callable[..., Any] | None = None,
        timeout: float = 10.0,
    ):
        runtime_token = runtime_token if runtime_token is not None else token
        if (
            not isinstance(runtime_token, str)
            or not runtime_token
            or "\r" in runtime_token
            or "\n" in runtime_token
        ):
            raise ValueError("runtime token must be a bounded header value")
        self._runtime_token = runtime_token
        self._transport = transport or UrllibFoundryTransport(
            base_url or "http://127.0.0.1:8000", timeout=timeout
        )
        self.last_reconciliation_snapshot: RuntimeReconciliationSnapshot | None = None

    def __repr__(self) -> str:  # pragma: no cover - defensive redaction
        return "FoundryClient(<redacted-token>)"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        lease_token: str | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._runtime_token}",
        }
        if lease_token is not None:
            if (
                not isinstance(lease_token, str)
                or not lease_token
                or "\r" in lease_token
                or "\n" in lease_token
            ):
                raise ValueError("lease token must be a bounded header value")
            headers["X-Foundry-Lease-Token"] = lease_token
        try:
            request = getattr(self._transport, "request", self._transport)
            try:
                raw = request(method, path, headers=headers, body=body)
            except TypeError:
                # A few tiny test fakes use ``json`` or ``payload`` as the
                # keyword name.  Supporting both keeps the transport seam
                # intentionally dependency-free.
                try:
                    raw = request(method, path, headers=headers, json=body)
                except TypeError:
                    raw = request(method, path, headers, body)
            if inspect.isawaitable(raw):
                raw = await raw
            status, payload = _parse_response(raw)
        except FoundryError:
            raise
        except (TimeoutError, ConnectionError, OSError, urllib.error.URLError) as exc:
            raise ResponseLossError("Foundry response was lost") from exc
        if status == 204:
            return None
        if status < 200 or status >= 300:
            raise _error_for(status, payload)
        return payload or {}

    async def claim(
        self, available_slots: int, *, claim_id: str | UUID | None = None
    ) -> FoundryClaim | None:
        if (
            isinstance(available_slots, bool)
            or not isinstance(available_slots, int)
            or not 1 <= available_slots <= MAX_CLAIM_SLOTS
        ):
            raise ValueError("available_slots must be an integer from 1 to 8")
        claim_id = str(claim_id or uuid4())
        payload = await self._request(
            "POST",
            "/api/v1/runtime/claims",
            body={"claim_id": claim_id, "available_slots": available_slots},
        )
        if payload is None:
            return None
        required = (
            "attempt_id",
            "execution_id",
            "profile_id",
            "hermes_profile_key",
            "model",
            "stream_id",
            "lease_id",
            "lease_token",
            "claim_id",
        )
        if any(key not in payload for key in required):
            raise FoundryError(
                "Foundry claim response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        if "reasoning_effort" in payload:
            try:
                raw_reasoning_effort = payload["reasoning_effort"]
                reasoning_effort = validate_reasoning_effort(raw_reasoning_effort)
                if reasoning_effort is None:
                    raise ValueError("reasoning effort cannot be null")
            except ValueError as exc:
                raise FoundryError(
                    "Foundry claim response contained an invalid reasoning effort",
                    status=200,
                    code="MALFORMED_RESPONSE",
                ) from exc
        else:
            reasoning_effort = None
        return FoundryClaim(
            attempt_id=str(payload["attempt_id"]),
            execution_id=str(payload["execution_id"]),
            profile_id=str(payload["profile_id"]),
            hermes_profile_key=str(payload["hermes_profile_key"]),
            model=str(payload["model"]),
            conversation_id=payload.get("conversation_id"),
            session_id=payload.get("session_id"),
            stream_id=str(payload["stream_id"]),
            lease_id=str(payload["lease_id"]),
            lease_token=str(payload["lease_token"]),
            expires_at=_parse_datetime(payload.get("expires_at")),
            payload=payload.get("payload")
            if isinstance(payload.get("payload"), Mapping)
            else {},
            claim_id=str(payload["claim_id"]),
            routine_id=(
                str(payload["routine_id"])
                if payload.get("routine_id") is not None
                else None
            ),
            reasoning_effort=reasoning_effort,
            routine_tool_token=payload.get("routine_tool_token"),
        )

    async def reconciliation_snapshot(self) -> RuntimeReconciliationSnapshot:
        """Read profile state plus the current server-owned start epoch."""

        payload = await self._request("GET", "/api/v1/runtime/profiles/reconciliation")
        if not payload or payload.get("version") != 1:
            raise FoundryError(
                "Foundry profile reconciliation response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        rows = payload.get("profiles")
        generation = payload.get("machine_generation")
        runtime_start_epoch = payload.get("runtime_start_epoch")
        activity_revision = payload.get("activity_revision", 0)
        workspace_id = payload.get("workspace_id")
        if not isinstance(workspace_id, str) or not workspace_id:
            workspace_id = None
        if (
            not isinstance(rows, list)
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation <= 0
        ):
            raise FoundryError(
                "Foundry profile reconciliation response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        if runtime_start_epoch is not None and (
            isinstance(runtime_start_epoch, bool)
            or not isinstance(runtime_start_epoch, int)
            or runtime_start_epoch < 0
        ):
            raise FoundryError(
                "Foundry profile reconciliation response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        if (
            isinstance(activity_revision, bool)
            or not isinstance(activity_revision, int)
            or activity_revision < 0
        ):
            raise FoundryError(
                "Foundry profile reconciliation response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        snapshot = RuntimeReconciliationSnapshot(
            machine_generation=generation,
            runtime_start_epoch=runtime_start_epoch,
            profiles=tuple(_profile_desired_state(row, generation) for row in rows),
            activity_revision=activity_revision,
            workspace_id=workspace_id,
        )
        self.last_reconciliation_snapshot = snapshot
        return snapshot

    async def reconcile_profiles(self) -> tuple[ProfileDesiredState, ...]:
        """Read the current-generation, workspace-scoped profile desired state."""

        return (await self.reconciliation_snapshot()).profiles

    async def wait_for_activity(
        self,
        after_revision: int,
        wait_seconds: float,
    ) -> ActivityWaitReceipt:
        if (
            isinstance(after_revision, bool)
            or not isinstance(after_revision, int)
            or after_revision < 0
        ):
            raise ValueError("after_revision must be a non-negative integer")
        if isinstance(wait_seconds, bool):
            raise TypeError("wait_seconds must be a positive number")
        try:
            wait_seconds = float(wait_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("wait_seconds must be a positive number") from exc
        if not 0 < wait_seconds <= 5:
            raise ValueError("wait_seconds must be greater than 0 and at most 5")
        payload = await self._request(
            "POST",
            "/api/v1/runtime/activity-waits",
            body={
                "after_revision": after_revision,
                "wait_seconds": wait_seconds,
            },
        )
        if not payload:
            raise FoundryError(
                "Foundry activity wait response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        revision = payload.get("revision")
        reason = payload.get("reason")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
            or reason not in {"changed", "timeout"}
        ):
            raise FoundryError(
                "Foundry activity wait response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return ActivityWaitReceipt(revision=revision, reason=reason)

    async def report_readiness(
        self,
        *,
        boot_id: str | UUID,
        reconciled_generation: int,
        runtime_start_epoch: int,
    ) -> Mapping[str, Any]:
        try:
            boot_uuid = boot_id if isinstance(boot_id, UUID) else UUID(str(boot_id))
        except (TypeError, ValueError) as error:
            raise ValueError("boot_id must be a UUID") from error
        if (
            isinstance(reconciled_generation, bool)
            or not isinstance(reconciled_generation, int)
            or reconciled_generation <= 0
        ):
            raise ValueError("reconciled_generation must be positive")
        if (
            isinstance(runtime_start_epoch, bool)
            or not isinstance(runtime_start_epoch, int)
            or runtime_start_epoch < 0
        ):
            raise ValueError("runtime_start_epoch must be nonnegative")
        payload = await self._request(
            "POST",
            "/api/v1/runtime/readiness",
            body={
                "boot_id": str(boot_uuid),
                "reconciled_generation": reconciled_generation,
                "runtime_start_epoch": runtime_start_epoch,
            },
        )
        if not payload or payload.get("status") != "ready":
            raise FoundryError(
                "Foundry readiness response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        if (
            payload.get("generation") != reconciled_generation
            or payload.get("runtime_start_epoch") != runtime_start_epoch
            or not isinstance(payload.get("accepted_at"), str)
        ):
            raise FoundryError(
                "Foundry readiness response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return payload

    async def materialization_receipt(
        self,
        profile_id: str | UUID,
        *,
        operation_id: str | UUID,
        lifecycle_epoch: int,
        materialized_generation: int,
        seed_fingerprint: str,
        result_code: str,
    ) -> ProfileReceipt:
        result = await self._request(
            "POST",
            f"/api/v1/runtime/profiles/{profile_id}/materialization-receipt",
            body={
                "profile_id": str(profile_id),
                "operation_id": str(operation_id),
                "lifecycle_epoch": lifecycle_epoch,
                "materialized_generation": materialized_generation,
                "seed_fingerprint": seed_fingerprint,
                "result_code": result_code,
            },
        )
        return _profile_receipt(result)

    async def cleanup_receipt(
        self,
        profile_id: str | UUID,
        *,
        operation_id: str | UUID,
        lifecycle_epoch: int,
        request_digest: str,
        result_code: str,
        deleted: bool,
        active_lease_count: int,
    ) -> ProfileReceipt:
        result = await self._request(
            "POST",
            f"/api/v1/runtime/profiles/{profile_id}/cleanup-receipt",
            body={
                "profile_id": str(profile_id),
                "operation_id": str(operation_id),
                "lifecycle_epoch": lifecycle_epoch,
                "request_digest": request_digest,
                "result_code": result_code,
                "deleted": deleted,
                "active_lease_count": active_lease_count,
            },
        )
        return _profile_receipt(result)

    async def renew(self, attempt_id: str | UUID, lease_token: str) -> LeaseReceipt:
        payload = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/lease/renew",
            lease_token=lease_token,
        )
        if not payload or "lease_id" not in payload:
            raise FoundryError(
                "Foundry renewal response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return LeaseReceipt(
            str(payload["lease_id"]), _parse_datetime(payload.get("expires_at"))
        )

    async def approval_status(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        approval_request_id: str | UUID,
    ) -> ApprovalStatus:
        """Read one lease-bound approval and lazily reconcile its deadlines."""

        try:
            request_uuid = UUID(str(approval_request_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("approval_request_id must be a UUID") from exc
        payload = await self._request(
            "GET",
            f"/api/v1/runtime/attempts/{attempt_id}/approval-requests/{request_uuid}",
            lease_token=lease_token,
        )
        if not payload:
            raise FoundryError(
                "Foundry approval response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        status = payload.get("status")
        decision = payload.get("decision")
        if status not in {
            "pending",
            "decision_recorded",
            "applied",
            "expired",
            "cancelled",
            "outcome_unknown",
        } or (decision is not None and decision not in {"approve", "reject"}):
            raise FoundryError(
                "Foundry approval response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        if "approval_request_id" not in payload or str(
            payload["approval_request_id"]
        ) != str(request_uuid):
            raise FoundryError(
                "Foundry approval identity was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return ApprovalStatus(
            approval_request_id=str(request_uuid),
            status=status,
            decision=decision,
            decided_at=_parse_datetime(payload.get("decided_at")),
            acknowledgement_deadline_at=_parse_datetime(
                payload.get("acknowledgement_deadline_at")
            ),
            expires_at=_parse_datetime(payload.get("expires_at")),
        )

    poll_approval = approval_status

    async def event(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        stream_id: str,
        sequence: int,
        event_type: str,
        payload: Mapping[str, Any],
        event_id: str | UUID | None = None,
    ) -> EventReceipt:
        _validate_sequence(sequence, MAX_RUNTIME_EVENT_SEQUENCE, "event")
        event_id = str(
            event_id or deterministic_event_id(attempt_id, stream_id, sequence)
        )
        body = {
            "event_id": event_id,
            "stream_id": stream_id,
            "sequence": sequence,
            "type": event_type,
            "payload": dict(payload),
        }
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/events",
            lease_token=lease_token,
            body=body,
        )
        if not result or "event_id" not in result:
            raise FoundryError(
                "Foundry event response was malformed",
                status=202,
                code="MALFORMED_RESPONSE",
            )
        return EventReceipt(
            str(result["event_id"]), int(result.get("sequence", sequence))
        )

    append_event = event

    async def bind(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        cloud_conversation_ref: str,
        expected_session_id: str | None,
        effective_session_id: str,
    ) -> SessionReceipt:
        body = {
            "cloud_conversation_ref": cloud_conversation_ref,
            "expected_session_id": expected_session_id,
            "effective_session_id": effective_session_id,
        }
        result = await self._request(
            "PUT",
            f"/api/v1/runtime/attempts/{attempt_id}/session-binding",
            lease_token=lease_token,
            body=body,
        )
        if not result or "session_id" not in result:
            raise FoundryError(
                "Foundry session response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return SessionReceipt(str(result["session_id"]))

    async def bind_routine(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        expected_session_id: str | None,
        effective_session_id: str,
    ) -> SessionReceipt:
        result = await self._request(
            "PUT",
            f"/api/v1/runtime/attempts/{attempt_id}/routine-session-binding",
            lease_token=lease_token,
            body={
                "expected_session_id": expected_session_id,
                "effective_session_id": effective_session_id,
            },
        )
        if not result or "session_id" not in result:
            raise FoundryError(
                "Foundry routine session response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return SessionReceipt(str(result["session_id"]))

    update_session_binding = bind

    async def stopped(
        self, attempt_id: str | UUID, lease_token: str, *, reason: str
    ) -> StoppedReceipt:
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/stopped",
            lease_token=lease_token,
            body={"reason": reason},
        )
        if not result or "attempt_id" not in result:
            raise FoundryError(
                "Foundry stop response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        return StoppedReceipt(
            str(result["attempt_id"]),
            str(result.get("state", "released")),
            bool(result.get("requeued", False)),
        )

    acknowledge_stopped = stopped

    async def complete(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        stream_id: str,
        sequence: int,
        payload: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> TerminalReceipt:
        _validate_sequence(sequence, MAX_TERMINAL_SEQUENCE, "terminal event")
        event_id = deterministic_event_id(attempt_id, stream_id, sequence)
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/complete",
            lease_token=lease_token,
            body={
                "event_id": event_id,
                "stream_id": stream_id,
                "sequence": sequence,
                "payload": dict(payload),
                "receipt": dict(receipt),
            },
        )
        return self._terminal(result)

    complete_attempt = complete

    async def routine_result(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        event_id: str | UUID,
        sequence: int,
        outcome: str,
        text: str,
        references: list[Mapping[str, str]],
        delayed: bool,
    ) -> TerminalReceipt:
        _validate_sequence(sequence, MAX_TERMINAL_SEQUENCE, "routine result")
        if outcome not in {"changed", "unchanged", "failed"}:
            raise ValueError("routine result outcome is invalid")
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/routine-result",
            lease_token=lease_token,
            body={
                "event_id": str(event_id),
                "sequence": sequence,
                "outcome": outcome,
                "text": text,
                "references": [dict(reference) for reference in references],
                "delayed": delayed,
            },
        )
        return self._terminal(result)

    async def fail(
        self,
        attempt_id: str | UUID,
        lease_token: str,
        *,
        stream_id: str,
        sequence: int,
        payload: Mapping[str, Any],
        code: str,
        retryable: bool,
        receipt: Mapping[str, Any] | None = None,
    ) -> TerminalReceipt:
        _validate_sequence(sequence, MAX_TERMINAL_SEQUENCE, "terminal event")
        body = {
            "event_id": deterministic_event_id(attempt_id, stream_id, sequence),
            "stream_id": stream_id,
            "sequence": sequence,
            "payload": dict(payload),
            "code": code,
            "retryable": retryable,
            "receipt": dict(receipt) if receipt is not None else None,
        }
        result = await self._request(
            "POST",
            f"/api/v1/runtime/attempts/{attempt_id}/fail",
            lease_token=lease_token,
            body=body,
        )
        return self._terminal(result)

    fail_attempt = fail

    @staticmethod
    def _terminal(result: Mapping[str, Any] | None) -> TerminalReceipt:
        if not result or any(
            key not in result for key in ("attempt_id", "status", "receipt_id")
        ):
            raise FoundryError(
                "Foundry terminal response was malformed",
                status=200,
                code="MALFORMED_RESPONSE",
            )
        value = result.get("receipt")
        return TerminalReceipt(
            str(result["attempt_id"]),
            str(result["status"]),
            str(result["receipt_id"]),
            bool(result.get("requeued", False)),
            value if isinstance(value, Mapping) else None,
        )


async def _close_stream(stream: Any) -> None:
    for name in ("aclose", "close", "cancel"):
        method = getattr(stream, name, None)
        if callable(method):
            result = method()
            if inspect.isawaitable(result):
                await result
            return


def _validate_sequence(sequence: int, maximum: int, label: str) -> None:
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not 1 <= sequence <= maximum
    ):
        raise ValueError(f"{label} sequence must be an integer from 1 to {maximum}")


async def _retry_response_loss(operation: Callable[[], Any]) -> Any:
    """Replay one idempotent operation once after a lost response.

    Event IDs and terminal request digests are deterministic, so a retry is
    safe even when the first request committed before its response vanished.
    A second loss remains ambiguous and is deliberately surfaced to the
    worker's stopped/requeue path.
    """

    try:
        result = operation()
        if inspect.isawaitable(result):
            return await result
        return result
    except ResponseLossError:
        result = operation()
        if inspect.isawaitable(result):
            return await result
        return result


async def _stream_events(
    hermes: Any,
    profile_id: str,
    session_id: str,
    message: str,
    *,
    session_key: str,
    reasoning_effort: str | None = None,
    routine_result: bool = False,
    routine_tool_token: str | None = None,
) -> Any:
    stream_kwargs: dict[str, Any] = {"session_key": session_key}
    if reasoning_effort is not None:
        stream_kwargs["reasoning_effort"] = reasoning_effort
    if routine_result:
        stream_kwargs["routine_result"] = True
    elif routine_tool_token:
        stream_kwargs["routine_tool_token"] = routine_tool_token
    method = getattr(hermes, "stream_profile_incremental", None)
    if callable(method):
        result = method(profile_id, session_id, message, **stream_kwargs)
    else:
        result = hermes.stream_profile(profile_id, session_id, message, **stream_kwargs)
    if inspect.isawaitable(result):
        result = await result
    if hasattr(result, "__aiter__"):
        return result
    events = getattr(result, "events", ())

    async def replay() -> AsyncIterator[HermesEvent]:
        for event in events:
            yield event

    return replay()


def _first_turn_bootstrap(value: Any) -> HermesBootstrap | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "kind",
        "message_id",
        "text",
    }:
        raise InvalidRequestError("Execution bootstrap was invalid")
    if value.get("kind") != "assistant_message":
        raise InvalidRequestError("Execution bootstrap was invalid")
    try:
        message_id = str(UUID(str(value.get("message_id"))))
        text = validate_stream_message(value.get("text"))
    except (TypeError, ValueError):
        raise InvalidRequestError("Execution bootstrap was invalid") from None
    return HermesBootstrap(message_id=message_id, text=text)


class FoundryWorker:
    """Bounded claim/stream supervisor for one runtime process."""

    def __init__(
        self,
        foundry: FoundryClient,
        hermes: Any,
        *,
        slots: int = 2,
        renew_interval: float = DEFAULT_RENEW_INTERVAL,
        lease_seconds: float = LEASE_SECONDS,
        stop_safety_margin: float = DEFAULT_STOP_SAFETY_MARGIN,
        clock: Callable[[], float] = time.monotonic,
        profile_reconciler: Any | None = None,
        profile_reconcile_interval: float = DEFAULT_PROFILE_RECONCILE_INTERVAL,
        readiness_heartbeat_interval: float = 15.0,
        boot_id: str | UUID | None = None,
        activity_wait_enabled: bool = False,
        activity_wait_seconds: float = 5.0,
        approval_poll_interval: float = APPROVAL_POLL_INTERVAL,
    ):
        if (
            isinstance(slots, bool)
            or not isinstance(slots, int)
            or not 2 <= slots <= MAX_CLAIM_SLOTS
        ):
            raise ValueError("worker slots must be between 2 and 8")
        if not 0 < renew_interval < lease_seconds - stop_safety_margin:
            raise ValueError("renew interval must leave a stop safety margin")
        if profile_reconcile_interval <= 0:
            raise ValueError("profile reconcile interval must be positive")
        if readiness_heartbeat_interval <= 0:
            raise ValueError("readiness heartbeat interval must be positive")
        if not isinstance(activity_wait_enabled, bool):
            raise TypeError("activity wait enabled must be a boolean")
        if (
            isinstance(activity_wait_seconds, bool)
            or not 0 < float(activity_wait_seconds) <= 5
        ):
            raise ValueError("activity wait seconds must be between 0 and 5")
        if (
            isinstance(approval_poll_interval, bool)
            or not 0 < float(approval_poll_interval) <= 5
        ):
            raise ValueError("approval poll interval must be between 0 and 5")
        self.foundry = foundry
        self.hermes = hermes
        self.slots = slots
        self.renew_interval = renew_interval
        self.lease_seconds = lease_seconds
        self.stop_safety_margin = stop_safety_margin
        self._clock = clock
        self.profile_reconciler = profile_reconciler
        self._profiles_reconciled = profile_reconciler is None
        self._profile_reconcile_interval = profile_reconcile_interval
        self._last_profile_reconciliation: float | None = None
        self._profile_reconciliation_retry_attempts = 0
        self._readiness_heartbeat_interval = readiness_heartbeat_interval
        self.boot_id = str(boot_id or uuid4())
        self._last_readiness_report: float | None = None
        self._activity_wait_enabled = activity_wait_enabled
        self._activity_wait_seconds = float(activity_wait_seconds)
        self._approval_poll_interval = float(approval_poll_interval)
        self._activity_revision = 0
        self._active: set[asyncio.Task[Any]] = set()
        self._ambiguous_claims: dict[str, float] = {}
        self._fast_polls_remaining = 0
        self._stopping = False

    @property
    def active_count(self) -> int:
        return len(self._active) + len(self._ambiguous_claims)

    @property
    def ambiguous_claim_ids(self) -> tuple[str, ...]:
        return tuple(self._ambiguous_claims)

    def _observability_context(self) -> dict[str, object]:
        fields: dict[str, object] = {"correlation_id": self.boot_id}
        snapshot = getattr(self.foundry, "last_reconciliation_snapshot", None)
        if snapshot is None:
            return fields
        workspace_id = getattr(snapshot, "workspace_id", None)
        if workspace_id is not None:
            fields["workspace_id"] = workspace_id
        generation = getattr(snapshot, "machine_generation", None)
        if generation is not None:
            fields["generation"] = generation
        runtime_start_epoch = getattr(snapshot, "runtime_start_epoch", None)
        if runtime_start_epoch is not None:
            fields["runtime_start_epoch"] = runtime_start_epoch
        return fields

    async def stop(self) -> None:
        self._stopping = True
        self._fast_polls_remaining = 0
        tasks = tuple(self._active)
        if tasks:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._active.difference_update(tasks)

    async def run_claim(self, claim: FoundryClaim) -> Any:
        return await self._run_claim(claim)

    async def _bootstrap_first_turn(self, claim: FoundryClaim, session_id: str) -> None:
        """Seed Hermes before the first durable Foundry checkpoint."""

        bootstrap = _first_turn_bootstrap(claim.payload.get("bootstrap"))
        if bootstrap is None:
            return
        if claim.session_id is not None:
            raise InvalidRequestError("Execution bootstrap arrived after binding")
        ensure_session = getattr(self.hermes, "ensure_profile_session", None)
        bootstrap_session = getattr(self.hermes, "bootstrap_session", None)
        if not callable(ensure_session) or not callable(bootstrap_session):
            raise HermesError("Hermes session bootstrap was unavailable")
        try:
            ensured = ensure_session(
                claim.hermes_profile_key,
                session_id,
                model=claim.model,
            )
            if inspect.isawaitable(ensured):
                await ensured
        except (HermesTimeout, HermesDisconnected):
            raise _BootstrapResponseLost() from None

        def send_bootstrap() -> Any:
            result = bootstrap_session(
                claim.hermes_profile_key,
                session_id,
                bootstrap,
            )
            return result

        try:
            result = send_bootstrap()
            if inspect.isawaitable(result):
                result = await result
        except (HermesTimeout, HermesDisconnected):
            try:
                result = send_bootstrap()
                if inspect.isawaitable(result):
                    result = await result
            except (HermesTimeout, HermesDisconnected):
                raise _BootstrapResponseLost()
        status = (
            result.get("status")
            if isinstance(result, Mapping)
            else getattr(result, "status", None)
        )
        if status not in {"created", "duplicate"}:
            raise HermesMalformedResponse("Hermes bootstrap response was malformed")

    async def _renew_loop(
        self, claim: FoundryClaim, stream: Any, lost: asyncio.Event
    ) -> None:
        while not lost.is_set():
            await asyncio.sleep(self.renew_interval)
            try:
                await self.foundry.renew(claim.attempt_id, claim.lease_token)
            except (FoundryError, TimeoutError, OSError, ConnectionError):
                lost.set()
                await _close_stream(stream)
                return

    async def _wait_for_approval(
        self,
        claim: FoundryClaim,
        approval_request_id: str,
        expires_at: Any,
        lost: asyncio.Event,
    ) -> tuple[str, str | None, Any]:
        """Poll Foundry while the existing lease renewer keeps the turn alive."""

        expiry = _approval_time(expires_at)
        poll = getattr(self.foundry, "approval_status", None)
        if not callable(poll):
            poll = getattr(self.foundry, "poll_approval", None)
        if not callable(poll):
            raise FoundryError(
                "Foundry approval polling was unavailable",
                code="APPROVAL_UNAVAILABLE",
            )
        if not inspect.iscoroutinefunction(poll):
            # Approval polling is async by contract; never invoke an unbounded sync adapter.
            raise FoundryError(
                "Foundry approval polling must be asynchronous",
                code="APPROVAL_UNAVAILABLE",
            )
        while not lost.is_set():
            remaining = expiry - time.time()
            if remaining <= 0:
                return "expired", None, None
            try:
                status = await asyncio.wait_for(
                    poll(
                        claim.attempt_id,
                        claim.lease_token,
                        approval_request_id,
                    ),
                    remaining,
                )
            except TimeoutError:
                return "expired", None, None
            except (ResponseLossError, RateLimitedError, ServiceUnavailableError):
                # The status read is idempotent; keep the bounded wait alive.
                remaining = expiry - time.time()
                if remaining <= 0:
                    return "expired", None, None
                await asyncio.sleep(min(self._approval_poll_interval, remaining))
                continue
            reported_request_id = getattr(status, "approval_request_id", None)
            state = getattr(status, "status", None)
            decision = getattr(status, "decision", None)
            if isinstance(status, Mapping):
                reported_request_id = status.get("approval_request_id")
                state = status.get("status")
                decision = status.get("decision")
            if (
                reported_request_id is None
                or str(reported_request_id) != approval_request_id
            ):
                raise FoundryError(
                    "Foundry approval identity was malformed",
                    code="MALFORMED_RESPONSE",
                )
            if state == "decision_recorded":
                if decision not in {"approve", "reject"}:
                    raise FoundryError(
                        "Foundry approval decision was malformed",
                        code="MALFORMED_RESPONSE",
                    )
                acknowledgement_deadline = getattr(
                    status, "acknowledgement_deadline_at", None
                )
                if isinstance(status, Mapping):
                    acknowledgement_deadline = status.get("acknowledgement_deadline_at")
                if acknowledgement_deadline is None:
                    raise FoundryError(
                        "Foundry approval acknowledgement deadline was malformed",
                        code="MALFORMED_RESPONSE",
                    )
                return "decision", decision, acknowledgement_deadline
            if state == "expired":
                return "expired", None, None
            if state in {"cancelled", "outcome_unknown"}:
                return state, None, None
            remaining = expiry - time.time()
            if remaining <= 0:
                return "expired", None, None
            await asyncio.sleep(min(self._approval_poll_interval, remaining))
        return "cancelled", None, None

    async def _reconcile_hermes_approval(
        self,
        profile_id: str,
        session_id: str,
        run_id: str,
        hermes_approval_id: str,
        decision: str,
        session_key: str,
        acknowledgement_deadline: Any,
        pending_approval: dict[str, str],
    ) -> None:
        """Reconcile one lost Hermes decision response without resending it."""

        status_reader = getattr(self.hermes, "approval_status", None)
        if not callable(status_reader):
            raise HermesTimeout("Hermes approval acknowledgement was lost")
        try:
            deadline = _approval_time(acknowledgement_deadline)
        except HermesMalformedResponse:
            raise FoundryError(
                "Foundry approval acknowledgement deadline was malformed",
                code="MALFORMED_RESPONSE",
            ) from None
        expected = "approved" if decision == "approve" else "rejected"
        while not pending_approval.get("acknowledged"):
            remaining = deadline - time.time()
            if remaining <= 0:
                raise HermesTimeout("Hermes approval acknowledgement timed out")
            try:
                status_result = status_reader(
                    profile_id,
                    session_id,
                    run_id,
                    hermes_approval_id,
                    session_key=session_key,
                )
                if inspect.isawaitable(status_result):
                    status = await asyncio.wait_for(status_result, remaining)
                else:
                    status = status_result
            except TimeoutError:
                raise HermesTimeout("Hermes approval status timed out") from None
            except (HermesTimeout, HermesDisconnected):
                await asyncio.sleep(min(self._approval_poll_interval, remaining))
                continue
            state = getattr(status, "status", None)
            outcome = getattr(status, "outcome", None)
            if isinstance(status, Mapping):
                state = status.get("status")
                outcome = status.get("outcome")
            if state == "resolved":
                if outcome != expected:
                    raise HermesMalformedResponse(
                        "Hermes approval acknowledgement conflicted with decision"
                    )
                pending_approval["acknowledged"] = "1"
                return
            if state in {"expired", "cancelled"}:
                if outcome != state:
                    raise HermesError("Hermes approval terminal receipt was malformed")
                pending_approval["wait_outcome"] = state
                return
            await asyncio.sleep(min(self._approval_poll_interval, remaining))

    async def _report_routine_failure(
        self,
        claim: FoundryClaim,
        *,
        sequence: int,
    ) -> TerminalReceipt:
        routine_result = getattr(self.foundry, "routine_result", None)
        if not callable(routine_result):
            raise HermesError("Foundry routine result endpoint was unavailable")
        return await _retry_response_loss(
            lambda: routine_result(
                claim.attempt_id,
                claim.lease_token,
                event_id=deterministic_event_id(
                    claim.attempt_id, claim.stream_id, sequence
                ),
                sequence=sequence,
                outcome="failed",
                text="Routine failed before completion.",
                references=[],
                delayed=bool(claim.payload.get("delayed", False)),
            )
        )

    async def _run_claim(self, claim: FoundryClaim) -> Any:
        stream = None
        lost = asyncio.Event()
        renewal: asyncio.Task[Any] | None = None
        sequence = 0
        result_text: list[str] = []
        result_text_bytes = 0
        try:
            try:
                message = validate_stream_message(
                    claim.payload.get(
                        "execution_prompt"
                        if claim.routine_id is not None
                        else "message"
                    )
                )
            except ValueError:
                raise InvalidRequestError("Execution message was invalid")
            input_conversation = claim.payload.get(
                "run_conversation_id"
                if claim.routine_id is not None
                else "cloud_conversation_ref"
            )
            if claim.conversation_id is None:
                if (
                    not isinstance(input_conversation, str)
                    or not input_conversation
                    or len(input_conversation) > 255
                    or claim.session_id is not None
                ):
                    raise InvalidRequestError("Execution conversation was invalid")
                conversation_id = input_conversation
            else:
                conversation_id = claim.conversation_id
                if (
                    not conversation_id
                    or len(conversation_id) > 255
                    or (
                        input_conversation is not None
                        and input_conversation != conversation_id
                    )
                ):
                    raise InvalidRequestError("Execution conversation was invalid")

            identifiers = stable_session_identifiers(claim.profile_id, conversation_id)
            session_id = claim.session_id or identifiers.candidate_id
            approval = claim.payload.get("routine_approval")
            if claim.routine_id is not None and isinstance(approval, Mapping):
                routine_result = getattr(self.foundry, "routine_result", None)
                if not callable(routine_result):
                    raise HermesError(
                        "Foundry routine continuation result endpoint was unavailable"
                    )
                return await _retry_response_loss(
                    lambda: routine_result(
                        claim.attempt_id,
                        claim.lease_token,
                        event_id=deterministic_event_id(
                            claim.attempt_id,
                            claim.stream_id,
                            MAX_TERMINAL_SEQUENCE,
                        ),
                        sequence=MAX_TERMINAL_SEQUENCE,
                        outcome="failed",
                        text=(
                            "Approved action continuation is unavailable; "
                            "no action was executed."
                        ),
                        references=[],
                        delayed=bool(claim.payload.get("delayed", False)),
                    )
                )
            bootstrap = _first_turn_bootstrap(claim.payload.get("bootstrap"))
            if bootstrap is not None and claim.session_id is not None:
                raise InvalidRequestError("Execution bootstrap arrived after binding")
            history_verified = False
            expected_history_marker = claim.payload.get("proof_expected_history_marker")
            if expected_history_marker is not None:
                forbidden_history_marker = claim.payload.get(
                    "proof_forbidden_history_marker"
                )
                if not isinstance(expected_history_marker, str) or not isinstance(
                    forbidden_history_marker, str
                ):
                    raise InvalidRequestError("Execution history proof was invalid")
                inspect_history = getattr(
                    self.hermes, "profile_session_matches_markers", None
                )
                if not callable(inspect_history) or claim.session_id is None:
                    raise HermesError("Hermes session history was unavailable")
                history_verified = inspect_history(
                    claim.hermes_profile_key,
                    session_id,
                    expected_history_marker,
                    forbidden_history_marker,
                )
                if inspect.isawaitable(history_verified):
                    history_verified = await history_verified
                if history_verified is not True:
                    raise HermesHistoryMismatch()

            if bootstrap is not None:
                await self._bootstrap_first_turn(claim, session_id)

            sequence = 1
            dispatch_payload = {"status": "dispatched"}
            try:
                await _retry_response_loss(
                    lambda: self.foundry.event(
                        claim.attempt_id,
                        claim.lease_token,
                        stream_id=claim.stream_id,
                        sequence=sequence,
                        event_type="execution.dispatched",
                        payload=dispatch_payload,
                        event_id=deterministic_event_id(
                            claim.attempt_id, claim.stream_id, sequence
                        ),
                    )
                )
            except ResponseLossError:
                return await self.foundry.stopped(
                    claim.attempt_id,
                    claim.lease_token,
                    reason="dispatch_response_lost",
                )
            if claim.session_id is None and bootstrap is None:
                ensure_session = getattr(self.hermes, "ensure_profile_session", None)
                if not callable(ensure_session):
                    raise HermesError("Hermes session operations were unavailable")
                ensured = ensure_session(
                    claim.hermes_profile_key,
                    session_id,
                    model=claim.model,
                )
                if inspect.isawaitable(ensured):
                    await ensured

            stream = await _stream_events(
                self.hermes,
                claim.hermes_profile_key,
                session_id,
                message,
                session_key=identifiers.session_key,
                reasoning_effort=claim.reasoning_effort,
                routine_result=claim.routine_id is not None,
                routine_tool_token=claim.routine_tool_token,
            )
            renewal = asyncio.create_task(self._renew_loop(claim, stream, lost))
            terminal: HermesEvent | None = None
            pending_approval: dict[str, str] | None = None
            proof_hold = claim.payload.get("proof_hold_after_first_safe_event") is True
            held_after_safe_event = False
            async for event in stream:
                if lost.is_set():
                    break
                if not isinstance(event, HermesEvent):
                    raise HermesError("Hermes returned a malformed event")
                if event.profile_id != claim.hermes_profile_key:
                    raise HermesError("Hermes event identity did not match claim")
                if terminal is not None:
                    raise HermesError("Hermes returned an event after completion")
                if event.name == "execution.completed":
                    if pending_approval is not None:
                        raise HermesMalformedResponse(
                            "Hermes completed while approval was pending"
                        )
                    terminal = event
                    continue
                if event.session_id != session_id or event.name not in {
                    "message.delta",
                    "activity.started",
                    "activity.completed",
                    "approval.request",
                    "approval.responded",
                }:
                    raise HermesError("Hermes event identity did not match claim")
                if event.name == "message.delta":
                    delta_text = event.payload.get("text")
                    if claim.routine_id is not None and isinstance(delta_text, str):
                        delta_text_bytes = len(delta_text.encode("utf-8"))
                        if (
                            result_text_bytes + delta_text_bytes
                            > MAX_ROUTINE_TEXT_BYTES
                        ):
                            raise HermesMalformedResponse(
                                "Hermes routine result text was too large"
                            )
                        result_text.append(delta_text)
                        result_text_bytes += delta_text_bytes
                if lost.is_set():
                    break
                if sequence >= MAX_RUNTIME_EVENT_SEQUENCE:
                    # Close the producer before publishing the one reserved
                    # terminal event.  The deterministic terminal identity
                    # makes the bounded response-loss replay safe.
                    await _close_stream(stream)
                    stream = None
                    failure_payload = {
                        "code": "event_budget_exhausted",
                        "retryable": False,
                    }
                    try:
                        if claim.routine_id is not None:
                            return await self._report_routine_failure(
                                claim,
                                sequence=MAX_TERMINAL_SEQUENCE,
                            )
                        return await _retry_response_loss(
                            lambda payload=failure_payload: self.foundry.fail(
                                claim.attempt_id,
                                claim.lease_token,
                                stream_id=claim.stream_id,
                                sequence=MAX_TERMINAL_SEQUENCE,
                                payload=payload,
                                code="event_budget_exhausted",
                                retryable=False,
                                receipt={"code": "event_budget_exhausted"},
                            )
                        )
                    except ResponseLossError:
                        # Leave terminal reconciliation to the durable lease expiry path.
                        if claim.routine_id is not None:
                            try:
                                return await self.foundry.stopped(
                                    claim.attempt_id,
                                    claim.lease_token,
                                    reason="routine_result_response_lost",
                                )
                            except FoundryError:
                                return None
                        return None
                    except FoundryError:
                        return None
                if event.name == "approval.request":
                    if pending_approval is not None:
                        raise HermesMalformedResponse(
                            "Hermes returned a second pending approval"
                        )
                    if set(event.payload) != {
                        "hermes_approval_id",
                        "action_kind",
                        "action_label",
                        "action_preview",
                        "expires_at",
                    }:
                        raise HermesMalformedResponse(
                            "Hermes approval request was malformed"
                        )
                    hermes_approval_id = event.payload.get("hermes_approval_id")
                    action_kind = event.payload.get("action_kind")
                    action_label = event.payload.get("action_label")
                    action_preview = event.payload.get("action_preview")
                    expires_at = event.payload.get("expires_at")
                    if (
                        not isinstance(hermes_approval_id, str)
                        or not hermes_approval_id
                        or action_kind
                        not in {"terminal", "execute_code", "plugin_tool"}
                        or not isinstance(action_label, str)
                        or not 1 <= len(action_label) <= MAX_APPROVAL_LABEL_CHARS
                        or "\x00" in action_label
                        or not isinstance(action_preview, str)
                        or not action_preview
                        or "\x00" in action_preview
                        or len(action_preview.encode("utf-8"))
                        > MAX_APPROVAL_PREVIEW_BYTES
                        or not isinstance(expires_at, str)
                    ):
                        raise HermesMalformedResponse(
                            "Hermes approval request was malformed"
                        )
                    expiry = _approval_time(expires_at)
                    now = time.time()
                    if expiry <= now or expiry > now + MAX_APPROVAL_LIFETIME_SECONDS:
                        raise HermesMalformedResponse(
                            "Hermes approval expiry was outside the bounded window"
                        )
                    approval_request_id = _approval_request_id(
                        claim.attempt_id, event.run_id, hermes_approval_id
                    )
                    awaiting_payload = {
                        "approval_request_id": approval_request_id,
                        "action_kind": action_kind,
                        "action_label": action_label,
                        "action_preview": action_preview,
                        "expires_at": expires_at,
                    }
                    sequence += 1
                    try:
                        await _retry_response_loss(
                            lambda current_sequence=sequence, current_payload=awaiting_payload: (
                                self.foundry.event(
                                    claim.attempt_id,
                                    claim.lease_token,
                                    stream_id=claim.stream_id,
                                    sequence=current_sequence,
                                    event_type="execution.awaiting_action",
                                    payload=current_payload,
                                    event_id=deterministic_event_id(
                                        claim.attempt_id,
                                        claim.stream_id,
                                        current_sequence,
                                    ),
                                )
                            )
                        )
                    except ResponseLossError:
                        lost.set()
                        await _close_stream(stream)
                        try:
                            return await self.foundry.stopped(
                                claim.attempt_id,
                                claim.lease_token,
                                reason="event_response_lost",
                            )
                        except FoundryError:
                            return None
                    pending_approval = {
                        "request_id": approval_request_id,
                        "hermes_id": hermes_approval_id,
                        "run_id": event.run_id,
                        "expires_at": expires_at,
                        "decision": "",
                    }
                    (
                        wait_outcome,
                        decision,
                        acknowledgement_deadline,
                    ) = await self._wait_for_approval(
                        claim,
                        approval_request_id,
                        expires_at,
                        lost,
                    )
                    if lost.is_set():
                        break
                    if wait_outcome == "outcome_unknown":
                        raise HermesError(
                            "Foundry approval acknowledgement was not confirmed"
                        )
                    if wait_outcome == "expired" or time.time() >= expiry:
                        pending_approval["decision"] = ""
                        pending_approval["wait_outcome"] = "expired"
                        continue
                    if decision is not None:
                        try:
                            acknowledgement_epoch = _approval_time(
                                acknowledgement_deadline
                            )
                        except HermesMalformedResponse:
                            raise FoundryError(
                                "Foundry approval acknowledgement deadline was malformed",
                                code="MALFORMED_RESPONSE",
                            ) from None
                        if min(expiry, acknowledgement_epoch) <= time.time():
                            raise HermesError(
                                "Foundry approval acknowledgement was not confirmed"
                            )
                    resolver_deadline: Any = expires_at
                    if decision is not None and acknowledgement_epoch < expiry:
                        resolver_deadline = acknowledgement_deadline
                    resolver = getattr(self.hermes, "resolve_approval", None)
                    if not callable(resolver):
                        raise HermesError("Hermes approval resolution was unavailable")
                    # Expiry/cancellation is resolved as a one-time reject so
                    # the blocked guard cannot execute.  The durable Foundry
                    # outcome remains the state returned by its poll.
                    hermes_decision = decision or "reject"
                    resolve_remaining = expiry - time.time()
                    if decision is not None:
                        resolve_remaining = min(
                            resolve_remaining,
                            acknowledgement_epoch - time.time(),
                        )
                    if resolve_remaining <= 0:
                        raise HermesError(
                            "Foundry approval acknowledgement was not confirmed"
                        )
                    try:
                        resolved = resolver(
                            claim.hermes_profile_key,
                            session_id,
                            event.run_id,
                            hermes_approval_id,
                            hermes_decision,
                            session_key=identifiers.session_key,
                            deadline_at=resolver_deadline,
                        )
                        if inspect.isawaitable(resolved):
                            resolved = await asyncio.wait_for(
                                resolved, resolve_remaining
                            )
                        if isinstance(resolved, Mapping) and resolved.get("status") in {
                            "expired",
                            "cancelled",
                        }:
                            pending_approval["wait_outcome"] = resolved["status"]
                    except TimeoutError as exc:
                        raise HermesTimeout(
                            "Hermes approval resolution timed out"
                        ) from exc
                    except (HermesTimeout, HermesDisconnected):
                        if decision is None:
                            raise
                        await self._reconcile_hermes_approval(
                            claim.hermes_profile_key,
                            session_id,
                            event.run_id,
                            hermes_approval_id,
                            decision,
                            identifiers.session_key,
                            acknowledgement_deadline,
                            pending_approval,
                        )
                    pending_approval["decision"] = decision or ""
                    pending_approval.setdefault("wait_outcome", wait_outcome)
                    continue
                if event.name == "approval.responded":
                    if pending_approval is None:
                        raise HermesMalformedResponse(
                            "Hermes approval response had no pending request"
                        )
                    if set(event.payload) != {"hermes_approval_id", "outcome"}:
                        raise HermesMalformedResponse(
                            "Hermes approval response was malformed"
                        )
                    if (
                        event.payload.get("hermes_approval_id")
                        != pending_approval["hermes_id"]
                    ):
                        raise HermesMalformedResponse(
                            "Hermes approval response identity changed"
                        )
                    outcome = event.payload.get("outcome")
                    if outcome not in {"approved", "rejected", "expired", "cancelled"}:
                        raise HermesMalformedResponse(
                            "Hermes approval response outcome was invalid"
                        )
                    decision = pending_approval.get("decision")
                    wait_outcome = pending_approval.get("wait_outcome")
                    if wait_outcome in {"expired", "cancelled"}:
                        if outcome != wait_outcome:
                            raise HermesMalformedResponse(
                                "Hermes approval response conflicted with terminal receipt"
                            )
                    elif decision and outcome != (
                        "approved" if decision == "approve" else "rejected"
                    ):
                        raise HermesMalformedResponse(
                            "Hermes approval response conflicted with decision"
                        )
                    resolution_payload = {
                        "approval_request_id": pending_approval["request_id"],
                        "outcome": outcome,
                    }
                    sequence += 1
                    try:
                        await _retry_response_loss(
                            lambda current_sequence=sequence, current_payload=resolution_payload: (
                                self.foundry.event(
                                    claim.attempt_id,
                                    claim.lease_token,
                                    stream_id=claim.stream_id,
                                    sequence=current_sequence,
                                    event_type="execution.approval_resolved",
                                    payload=current_payload,
                                    event_id=deterministic_event_id(
                                        claim.attempt_id,
                                        claim.stream_id,
                                        current_sequence,
                                    ),
                                )
                            )
                        )
                    except ResponseLossError:
                        lost.set()
                        await _close_stream(stream)
                        try:
                            return await self.foundry.stopped(
                                claim.attempt_id,
                                claim.lease_token,
                                reason="event_response_lost",
                            )
                        except FoundryError:
                            return None
                    pending_approval = None
                    continue
                sequence += 1
                try:
                    await _retry_response_loss(
                        lambda current_event=event, current_sequence=sequence: (
                            self.foundry.event(
                                claim.attempt_id,
                                claim.lease_token,
                                stream_id=claim.stream_id,
                                sequence=current_sequence,
                                event_type=current_event.name,
                                payload=current_event.payload,
                                event_id=deterministic_event_id(
                                    claim.attempt_id, claim.stream_id, current_sequence
                                ),
                            )
                        )
                    )
                except ResponseLossError:
                    lost.set()
                    await _close_stream(stream)
                    try:
                        return await self.foundry.stopped(
                            claim.attempt_id,
                            claim.lease_token,
                            reason="event_response_lost",
                        )
                    except FoundryError:
                        return None
                if proof_hold and not held_after_safe_event:
                    held_after_safe_event = True
                    while not lost.is_set():
                        await asyncio.sleep(min(self.renew_interval, 0.25))
                    break
            if lost.is_set():
                return await self.foundry.stopped(
                    claim.attempt_id, claim.lease_token, reason="lease_lost"
                )
            if terminal is None:
                raise HermesMalformedResponse(
                    "Hermes stream had no valid terminal event"
                )
            await _close_stream(stream)
            stream = None
            try:
                if claim.routine_id is not None:
                    bind_routine = getattr(self.foundry, "bind_routine", None)
                    if not callable(bind_routine):
                        raise HermesError(
                            "Foundry routine session binding was unavailable"
                        )
                    await _retry_response_loss(
                        lambda: bind_routine(
                            claim.attempt_id,
                            claim.lease_token,
                            expected_session_id=claim.session_id,
                            effective_session_id=terminal.session_id,
                        )
                    )
                else:
                    await _retry_response_loss(
                        lambda: self.foundry.bind(
                            claim.attempt_id,
                            claim.lease_token,
                            cloud_conversation_ref=conversation_id,
                            expected_session_id=claim.session_id,
                            effective_session_id=terminal.session_id,
                        )
                    )
            except ResponseLossError:
                return await self.foundry.stopped(
                    claim.attempt_id,
                    claim.lease_token,
                    reason="session_response_lost",
                )
            sequence += 1
            if claim.routine_id is not None:
                routine_result = getattr(self.foundry, "routine_result", None)
                if not callable(routine_result):
                    raise HermesError("Foundry routine result endpoint was unavailable")
                if not isinstance(terminal.payload, Mapping):
                    raise HermesMalformedResponse("Hermes routine result was malformed")
                outcome = terminal.payload.get("outcome")
                if outcome not in {"changed", "unchanged", "failed"}:
                    raise HermesMalformedResponse(
                        "Hermes routine result outcome was invalid"
                    )
                typed_text = terminal.payload.get("result_text")
                if (
                    not isinstance(typed_text, str)
                    or not typed_text
                    or "references" not in terminal.payload
                ):
                    raise HermesMalformedResponse(
                        "Hermes routine result was missing its typed report"
                    )
                routine_text = typed_text
                if len(routine_text.encode("utf-8")) > MAX_ROUTINE_TEXT_BYTES:
                    raise HermesMalformedResponse(
                        "Hermes routine result text was too large"
                    )
                references = _routine_references(
                    terminal.payload.get("references", []),
                    text=routine_text,
                )
                return await _retry_response_loss(
                    lambda: routine_result(
                        claim.attempt_id,
                        claim.lease_token,
                        event_id=deterministic_event_id(
                            claim.attempt_id, claim.stream_id, sequence
                        ),
                        sequence=sequence,
                        outcome=outcome,
                        text=routine_text,
                        references=references,
                        delayed=bool(claim.payload.get("delayed", False)),
                    )
                )
            try:
                return await _retry_response_loss(
                    lambda: self.foundry.complete(
                        claim.attempt_id,
                        claim.lease_token,
                        stream_id=claim.stream_id,
                        sequence=sequence,
                        payload=terminal.payload,
                        receipt={
                            "code": "ok",
                            **(
                                {"history_verified": True}
                                if expected_history_marker is not None
                                else {}
                            ),
                        },
                    )
                )
            except ResponseLossError:
                # Completion may already be durable; only stopped is safe to
                # attempt after the bounded replay also loses its response.
                lost.set()
                await _close_stream(stream)
                try:
                    return await self.foundry.stopped(
                        claim.attempt_id,
                        claim.lease_token,
                        reason="complete_response_lost",
                    )
                except FoundryError:
                    return None
        except asyncio.CancelledError:
            await _close_stream(stream)
            try:
                return await self.foundry.stopped(
                    claim.attempt_id, claim.lease_token, reason="cancelled"
                )
            except FoundryError:
                return None
        except _BootstrapResponseLost:
            try:
                return await self.foundry.stopped(
                    claim.attempt_id,
                    claim.lease_token,
                    reason="bootstrap_response_lost",
                )
            except FoundryError:
                return None
        except (FoundryError, HermesError) as exc:
            if lost.is_set() or isinstance(exc, (FencedError, LeaseConflictError)):
                try:
                    return await self.foundry.stopped(
                        claim.attempt_id, claim.lease_token, reason="lease_lost"
                    )
                except FoundryError:
                    return None
            if claim.routine_id is not None and isinstance(exc, ResponseLossError):
                try:
                    return await self.foundry.stopped(
                        claim.attempt_id,
                        claim.lease_token,
                        reason="routine_result_response_lost",
                    )
                except FoundryError:
                    return None
            failure_code = getattr(exc, "code", "runtime_error")
            # A retryable failure is only safe after the Hermes producer has
            # stopped.  Close it before issuing the durable fail/requeue.
            if stream is not None:
                await _close_stream(stream)
                stream = None
            # Keep fallback failure inside the reserved terminal slot.  A
            # failed completion at the boundary must not manufacture an
            # invalid sequence or bypass lease-expiry reconciliation.
            sequence = min(max(sequence + 1, 1), MAX_TERMINAL_SEQUENCE)
            if claim.routine_id is not None:
                try:
                    return await self._report_routine_failure(
                        claim,
                        sequence=sequence,
                    )
                except ResponseLossError:
                    lost.set()
                    try:
                        return await self.foundry.stopped(
                            claim.attempt_id,
                            claim.lease_token,
                            reason="routine_result_response_lost",
                        )
                    except FoundryError:
                        return None
                except FoundryError:
                    return None
            failure_payload = {
                "code": failure_code,
                "retryable": False,
            }
            try:
                return await _retry_response_loss(
                    lambda: self.foundry.fail(
                        claim.attempt_id,
                        claim.lease_token,
                        stream_id=claim.stream_id,
                        sequence=sequence,
                        payload=failure_payload,
                        code=failure_code,
                        retryable=False,
                        receipt={"code": failure_code},
                    )
                )
            except ResponseLossError:
                lost.set()
                await _close_stream(stream)
                try:
                    return await self.foundry.stopped(
                        claim.attempt_id,
                        claim.lease_token,
                        reason="fail_response_lost",
                    )
                except FoundryError:
                    return None
            except FoundryError:
                return None
        finally:
            if renewal is not None:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)
            if stream is not None:
                await _close_stream(stream)

    async def run(
        self,
        *,
        max_turns: int | None = None,
        idle_cycles: int | None = 1,
        idle_delay: float = 0.0,
    ) -> tuple[Any, ...]:
        """Run the worker loop and emit only low-cardinality lifecycle events."""

        started_at = time.monotonic()
        emit_runtime_event(
            build_event(
                "worker.started",
                operation="worker_loop",
                outcome="started",
                **self._observability_context(),
            )
        )
        try:
            results = await self._run_loop(
                max_turns=max_turns,
                idle_cycles=idle_cycles,
                idle_delay=idle_delay,
            )
        except BaseException as error:
            emit_runtime_event(
                build_event(
                    "worker.failed",
                    operation="worker_loop",
                    duration_ms=(time.monotonic() - started_at) * 1000,
                    outcome="error",
                    error_type=type(error).__name__,
                    error_code=getattr(error, "code", None),
                    **self._observability_context(),
                )
            )
            raise
        emit_runtime_event(
            build_event(
                "worker.idle",
                operation="worker_loop",
                duration_ms=(time.monotonic() - started_at) * 1000,
                outcome="success",
                **self._observability_context(),
            )
        )
        return results

    async def _run_loop(
        self,
        *,
        max_turns: int | None = None,
        idle_cycles: int | None = 1,
        idle_delay: float = 0.0,
    ) -> tuple[Any, ...]:
        """Poll until the requested number of turns has completed.

        ``max_turns`` is intentionally bounded for tests and one-shot jobs.
        Without it, ``idle_cycles`` controls how many empty polls end the run.
        """
        if max_turns is not None and (isinstance(max_turns, bool) or max_turns < 1):
            raise ValueError("max_turns must be positive")
        if idle_cycles is not None and idle_cycles < 1:
            raise ValueError("idle_cycles must be positive")
        results: list[Any] = []
        empty = 0
        # Keep the argument as a narrow test/compatibility seam; production
        # uses the fixed bounded backoff by leaving it at zero.
        initial_idle_delay = (
            min(MAX_IDLE_BACKOFF_SECONDS, max(idle_delay, 0.01))
            if idle_delay
            else MIN_IDLE_BACKOFF_SECONDS
        )
        idle_backoff = initial_idle_delay
        poll_delay = initial_idle_delay
        retry_pending = False
        initialized = False
        with observe_runtime_operation(
            "worker.initialization",
            **self._observability_context(),
        ) as initialization:
            while not self._stopping:
                if await self._reconcile_profiles_or_wait(
                    force=True, retry_delay=poll_delay
                ):
                    initialization.update(**self._observability_context())
                    initialized = True
                    break
            if not initialized:
                initialization.update(
                    outcome="error",
                    error_type="WorkerStopped",
                    error_code="worker_stopped",
                    reason_code="stopped",
                )
        while not self._stopping and (max_turns is None or len(results) < max_turns):
            if not await self._reconcile_profiles_or_wait(retry_delay=poll_delay):
                continue
            now = self._clock()
            expired = [
                claim_id
                for claim_id, started_at in self._ambiguous_claims.items()
                if now - started_at >= self.lease_seconds
            ]
            for claim_id in expired:
                self._ambiguous_claims.pop(claim_id, None)
            while (
                not self._stopping
                and len(self._active) + len(self._ambiguous_claims) < self.slots
                and (max_turns is None or len(results) + len(self._active) < max_turns)
            ):
                claim_id = next(iter(self._ambiguous_claims), None) or str(uuid4())
                retryable_claim_error = False
                try:
                    available_slots = max(
                        1, self.slots - len(self._active) - len(self._ambiguous_claims)
                    )
                    claim = await self.foundry.claim(available_slots, claim_id=claim_id)
                except ResponseLossError:
                    self._ambiguous_claims.setdefault(claim_id, self._clock())
                    retryable_claim_error = True
                except (FencedError, InvalidCredentialError):
                    self._stopping = True
                    break
                except NotReadyError:
                    self._profiles_reconciled = False
                    retryable_claim_error = True
                except (RateLimitedError, ServiceUnavailableError):
                    retryable_claim_error = True
                if retryable_claim_error:
                    poll_delay = _jittered_idle_delay(idle_backoff, initial_idle_delay)
                    idle_backoff = min(MAX_IDLE_BACKOFF_SECONDS, idle_backoff * 2)
                    retry_pending = True
                    break
                if claim_id in self._ambiguous_claims:
                    self._ambiguous_claims.pop(claim_id, None)
                if retry_pending:
                    idle_backoff = initial_idle_delay
                    retry_pending = False
                if claim is None:
                    empty += 1
                    if self._fast_polls_remaining:
                        self._fast_polls_remaining -= 1
                        idle_backoff = initial_idle_delay
                        poll_delay = initial_idle_delay
                    else:
                        poll_delay = _jittered_idle_delay(
                            idle_backoff, initial_idle_delay
                        )
                        idle_backoff = min(MAX_IDLE_BACKOFF_SECONDS, idle_backoff * 2)
                    break
                self._fast_polls_remaining = 0
                idle_backoff = initial_idle_delay
                poll_delay = initial_idle_delay
                task = asyncio.create_task(self._run_claim(claim))
                self._active.add(task)
                task.add_done_callback(self._active.discard)
            if self._active:
                done, _ = await asyncio.wait(
                    self._active,
                    timeout=poll_delay,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    continue
                for task in done:
                    try:
                        results.append(task.result())
                    except asyncio.CancelledError:
                        results.append(None)
                    except Exception:  # noqa: BLE001 - one failed slot must not stop peers
                        results.append(None)
                self._active.difference_update(done)
                empty = 0
                idle_backoff = initial_idle_delay
                poll_delay = initial_idle_delay
                continue
            if self._ambiguous_claims:
                await asyncio.sleep(poll_delay)
                continue
            if (idle_cycles is not None and empty >= idle_cycles) or self._stopping:
                break
            if self._activity_wait_enabled and not retry_pending and poll_delay > 1.0:
                try:
                    waited = await self._wait_for_activity()
                except (FencedError, InvalidCredentialError):
                    self._stopping = True
                    break
                except NotReadyError:
                    self._profiles_reconciled = False
                    poll_delay = _jittered_idle_delay(idle_backoff, initial_idle_delay)
                    idle_backoff = min(MAX_IDLE_BACKOFF_SECONDS, idle_backoff * 2)
                    await asyncio.sleep(poll_delay)
                    continue
                except (ResponseLossError, RateLimitedError, ServiceUnavailableError):
                    poll_delay = _jittered_idle_delay(idle_backoff, initial_idle_delay)
                    idle_backoff = min(MAX_IDLE_BACKOFF_SECONDS, idle_backoff * 2)
                    await asyncio.sleep(poll_delay)
                    continue
                if waited is not None:
                    self._activity_revision = max(
                        self._activity_revision, waited.revision
                    )
                    if waited.reason == "changed":
                        self._profiles_reconciled = False
                        empty = 0
                        idle_backoff = initial_idle_delay
                        poll_delay = initial_idle_delay
                        continue
                    await asyncio.sleep(random.uniform(0.1, 0.25))
                    continue
            await asyncio.sleep(poll_delay)
        if self._active:
            done, _ = await asyncio.wait(self._active)
            for task in done:
                results.append(task.result() if not task.cancelled() else None)
        return tuple(results)

    async def _reconcile_profiles_or_wait(
        self, *, force: bool = False, retry_delay: float
    ) -> bool:
        try:
            await self._reconcile_profiles(force=force)
        except (
            NotReadyError,
            ResponseLossError,
            RateLimitedError,
            ServiceUnavailableError,
        ) as error:
            self._profiles_reconciled = False
            self._profile_reconciliation_retry_attempts += 1
            base_delay = max(retry_delay, 0.01)
            exponent = min(self._profile_reconciliation_retry_attempts - 1, 8)
            bounded_delay = min(
                MAX_PROFILE_RECONCILIATION_RETRY_DELAY,
                base_delay * (2**exponent),
            )
            emit_runtime_event(
                build_event(
                    "runtime.operation.retried",
                    operation="profile_reconciliation",
                    outcome="retry",
                    retry_count=self._profile_reconciliation_retry_attempts,
                    error_type=type(error).__name__,
                    error_code=getattr(error, "code", None),
                    **self._observability_context(),
                )
            )
            with observe_runtime_operation(
                "profile.reconciliation_retry_wait",
                retry_count=self._profile_reconciliation_retry_attempts,
                **self._observability_context(),
            ):
                await asyncio.sleep(bounded_delay)
            return False
        self._profile_reconciliation_retry_attempts = 0
        return True

    async def _wait_for_activity(self) -> ActivityWaitReceipt | None:
        method = getattr(self.foundry, "wait_for_activity", None)
        if not callable(method):
            return None
        try:
            result = method(self._activity_revision, self._activity_wait_seconds)
            if inspect.isawaitable(result):
                result = await result
        except FoundryError as error:
            if error.status == 422:
                # Independently deployed servers may allow a shorter wait.
                # Optional acceleration must never stop the runtime worker.
                self._activity_wait_enabled = False
                return None
            # Older Foundry servers do not know this optional endpoint.  A
            # malformed optional response has the same safe fallback: keep
            # the established bounded polling loop alive.
            if error.status == 404 or error.code == "MALFORMED_RESPONSE":
                raise ServiceUnavailableError(
                    "Foundry activity wait is unavailable",
                    status=503,
                    code="ACTIVITY_WAIT_UNAVAILABLE",
                ) from error
            raise
        if result is None:
            return None
        if isinstance(result, ActivityWaitReceipt):
            return result
        if isinstance(result, Mapping):
            revision = result.get("revision")
            reason = result.get("reason")
        else:
            revision = getattr(result, "revision", None)
            reason = getattr(result, "reason", None)
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 0
            or reason not in {"changed", "timeout"}
        ):
            raise ServiceUnavailableError(
                "Foundry activity wait response was malformed",
                status=503,
                code="MALFORMED_RESPONSE",
            )
        return ActivityWaitReceipt(revision=revision, reason=reason)

    async def _reconcile_profiles(self, *, force: bool = False) -> None:
        if self.profile_reconciler is None:
            return
        now = self._clock()
        if (
            not force
            and self._profiles_reconciled
            and self._last_profile_reconciliation is not None
            and now - self._last_profile_reconciliation
            < self._profile_reconcile_interval
        ):
            return
        report = await self.profile_reconciler.reconcile()
        if getattr(report, "materialized", ()):
            self._fast_polls_remaining = POST_MATERIALIZATION_FAST_POLLS
        self._profiles_reconciled = True
        self._last_profile_reconciliation = self._clock()
        snapshot = getattr(self.foundry, "last_reconciliation_snapshot", None)
        if snapshot is not None:
            activity_revision = getattr(snapshot, "activity_revision", 0)
            if isinstance(activity_revision, int) and not isinstance(
                activity_revision, bool
            ):
                self._activity_revision = max(
                    self._activity_revision, activity_revision
                )
        if (
            snapshot is not None
            and snapshot.runtime_start_epoch is not None
            and (
                force
                or self._last_readiness_report is None
                or now - self._last_readiness_report
                >= self._readiness_heartbeat_interval
            )
        ):
            try:
                with observe_runtime_operation(
                    "readiness.hermes_health",
                    **self._observability_context(),
                ) as health_operation:
                    hermes_ready = await self._hermes_ready()
                    if not hermes_ready:
                        health_operation.update(
                            outcome="error",
                            error_type="HermesNotReady",
                            error_code="hermes_not_ready",
                            reason_code="not_ready",
                        )
                        raise ServiceUnavailableError(
                            "Hermes is not ready for a runtime receipt",
                            status=503,
                            code="HERMES_NOT_READY",
                        )
            except HermesError as error:
                raise ServiceUnavailableError(
                    "Hermes is not ready for a runtime receipt",
                    status=503,
                    code="HERMES_NOT_READY",
                ) from error
            try:
                with observe_runtime_operation(
                    "readiness.publication",
                    **self._observability_context(),
                ):
                    await self.foundry.report_readiness(
                        boot_id=self.boot_id,
                        reconciled_generation=snapshot.machine_generation,
                        runtime_start_epoch=snapshot.runtime_start_epoch,
                    )
            except FencedError as error:
                self._profiles_reconciled = False
                raise NotReadyError(
                    "runtime readiness receipt was fenced",
                    status=error.status,
                    code="NOT_READY",
                ) from error
            self._last_readiness_report = self._clock()

    async def _hermes_ready(self) -> bool:
        health_method = getattr(self.hermes, "health_detailed", None)
        if not callable(health_method):
            health_method = getattr(self.hermes, "health", None)
        if not callable(health_method):
            return True
        health = health_method()
        if inspect.isawaitable(health):
            health = await health
        status = getattr(health, "status", None)
        if isinstance(status, str) and status.lower() in {"ok", "ready", "healthy"}:
            return True
        if not isinstance(status, str) or status.lower() != "degraded":
            return False
        readiness = getattr(health, "readiness", None)
        checks = readiness.get("checks") if isinstance(readiness, Mapping) else None
        gateway = checks.get("gateway") if isinstance(checks, Mapping) else None
        return bool(
            isinstance(gateway, Mapping)
            and gateway.get("status") == "ok"
            and gateway.get("state") == "running"
        )


RuntimeWorker = FoundryWorker
FoundrySupervisor = FoundryWorker


__all__ = [
    "MAX_APPROVAL_LABEL_CHARS",
    "MAX_APPROVAL_LIFETIME_SECONDS",
    "MAX_APPROVAL_PREVIEW_BYTES",
    "MAX_CLAIM_SLOTS",
    "MAX_RUNTIME_EVENT_SEQUENCE",
    "MAX_TERMINAL_SEQUENCE",
    "ActivityWaitReceipt",
    "ApprovalStatus",
    "EventReceipt",
    "FencedError",
    "FoundryClaim",
    "FoundryClient",
    "FoundryError",
    "FoundryFenced",
    "FoundryIdempotencyConflict",
    "FoundryInvalidCredential",
    "FoundryInvalidRequest",
    "FoundryLeaseConflict",
    "FoundryNotReady",
    "FoundryRateLimited",
    "FoundryRepairRequired",
    "FoundryResponseLoss",
    "FoundrySupervisor",
    "FoundryTransport",
    "FoundryUnavailable",
    "FoundryWorker",
    "IdempotencyConflictError",
    "InvalidCredentialError",
    "InvalidRequestError",
    "LeaseConflictError",
    "LeaseReceipt",
    "NotReadyError",
    "ProfileDesiredState",
    "ProfileReceipt",
    "RateLimitedError",
    "RepairRequiredError",
    "ResponseLossError",
    "RuntimeReconciliationSnapshot",
    "RuntimeWorker",
    "ServiceUnavailableError",
    "SessionReceipt",
    "StoppedReceipt",
    "TerminalReceipt",
    "UrllibFoundryTransport",
    "deterministic_event_id",
]
