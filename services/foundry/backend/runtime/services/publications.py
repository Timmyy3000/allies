"""Durable, scoped publication intent authority and Cloud transport."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Min, Q
from django.utils import timezone

from runtime.exceptions import (
    RuntimeFencedError,
    RuntimeIdempotencyConflictError,
    RuntimeLeaseConflictError,
    RuntimeNotReadyError,
    RuntimeValidationError,
)
from runtime.models import (
    Attempt,
    Lease,
    LeaseState,
    PublicationIntent,
    PublicationIntentState,
    RuntimeProfile,
    RuntimeProfileLifecycleState,
    Workspace,
)

from .event_delivery import _validated_cloud_url
from .profiles import profile_allows_runtime_write
from .runtime_auth import RuntimeContext
from .validation import digest_lease_token

MAX_PUBLICATION_FILES = 10
MAX_PUBLICATION_FILE_BYTES = 25_000_000
MAX_PUBLICATION_BYTES = 50_000_000
MAX_PUBLICATION_ATTEMPTS = 5
MAX_RECOVERY_BATCH = 20
MAX_CLOUD_RESPONSE_BYTES = 64 * 1024
_SAFE_ERROR = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_BACKOFF_SECONDS = (5, 30, 120, 300)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, slots=True)
class PublicationIntentReceipt:
    publication_id: UUID
    state: str
    manifest_digest: str | None = None
    next_due_at: object | None = None


@dataclass(frozen=True, slots=True)
class PublicationWakePage:
    woken: int
    next_cursor: str | None


def create_publication_intent(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    tool_call_id: str,
    files: Sequence[Mapping[str, object]],
) -> PublicationIntentReceipt:
    """Record intent before a runtime copy may become a durable snapshot."""

    _require_publications_enabled()
    call_id = _tool_call_id(tool_call_id)
    prepared = _prepared_files(files)
    request_digest = _digest({"tool_call_id": call_id, "files": prepared})
    tool_call_digest = _digest({"tool_call_id": call_id})
    with transaction.atomic():
        attempt, workspace, profile = _active_attempt(context, attempt_id, lease_token)
        execution = attempt.execution
        existing = (
            PublicationIntent.objects.select_for_update()
            .filter(execution_id=execution.id, tool_call_digest=tool_call_digest)
            .first()
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise RuntimeIdempotencyConflictError(
                    "publication tool call changed its descriptor set"
                )
            return _receipt(existing)
        try:
            intent = PublicationIntent.objects.create(
                workspace=workspace,
                profile=profile,
                execution=execution,
                source_attempt=attempt,
                cloud_binding_id=execution.cloud_binding_id,
                cloud_message_id=execution.cloud_message_id,
                tool_call_digest=tool_call_digest,
                request_digest=request_digest,
                next_due_at=timezone.now(),
            )
        except IntegrityError as exc:
            raise RuntimeIdempotencyConflictError(
                "publication tool call conflicts with stored state"
            ) from exc
    return _receipt(intent)


def acknowledge_frozen_publication(
    context: RuntimeContext,
    profile_id: UUID,
    publication_id: UUID,
    files: Sequence[Mapping[str, object]],
) -> PublicationIntentReceipt:
    """Persist one exact frozen manifest after its local journal is committed."""

    _require_publications_enabled()
    frozen = _frozen_files(files)
    manifest_digest = _digest({"files": frozen})
    should_register = False
    with transaction.atomic():
        _current_profile(context, profile_id)
        intent = (
            PublicationIntent.objects.select_for_update()
            .filter(
                pk=publication_id,
                profile_id=profile_id,
                workspace_id=context.workspace_id,
            )
            .first()
        )
        if intent is None:
            raise RuntimeLeaseConflictError("publication intent is not in this profile")
        if intent.manifest_digest is not None:
            if intent.manifest_digest != manifest_digest:
                raise RuntimeIdempotencyConflictError("publication manifest changed")
        else:
            if intent.state != PublicationIntentState.PREPARING:
                raise RuntimeLeaseConflictError("publication intent cannot be frozen")
            intent.manifest_digest = manifest_digest
            intent.state = PublicationIntentState.FROZEN
            intent.next_due_at = timezone.now()
            intent.safe_error_code = ""
            intent.save(
                update_fields=[
                    "manifest_digest",
                    "state",
                    "next_due_at",
                    "safe_error_code",
                    "updated_at",
                ]
            )
        should_register = intent.state == PublicationIntentState.FROZEN or (
            intent.state == PublicationIntentState.FAILED
            and intent.attempts < MAX_PUBLICATION_ATTEMPTS
            and intent.next_due_at <= timezone.now()
        )
    receipt = _receipt(intent)
    if should_register:
        _register_frozen_intent(intent.id, frozen)
    return receipt


def wake_due_publications(
    *, limit: int = MAX_RECOVERY_BATCH, cursor: str | None = None
) -> PublicationWakePage:
    """Wake bounded publication recovery without creating an execution."""

    if not getattr(settings, "ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED", False):
        return PublicationWakePage(0, None)
    if isinstance(limit, bool) or not 1 <= limit <= MAX_RECOVERY_BATCH:
        raise RuntimeValidationError("publication wake limit must be from 1 to 20")
    if cursor is not None and (
        not isinstance(cursor, str)
        or not cursor
        or len(cursor) > 512
        or "\r" in cursor
        or "\n" in cursor
    ):
        raise RuntimeValidationError("publication wake cursor is invalid")
    observed = timezone.now()
    workspace_ids = list(
        PublicationIntent.objects.filter(
            state__in=[
                PublicationIntentState.FROZEN,
                PublicationIntentState.REGISTERED,
                PublicationIntentState.FAILED,
            ],
            manifest_digest__isnull=False,
            next_due_at__lte=observed,
            profile__lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
        )
        .filter(
            Q(state=PublicationIntentState.REGISTERED)
            | Q(attempts__lt=MAX_PUBLICATION_ATTEMPTS)
        )
        .values("workspace_id")
        .annotate(next_due_at=Min("next_due_at"))
        .order_by("next_due_at", "workspace_id")
        .values_list("workspace_id", flat=True)[:limit]
    )
    query = urlencode({"limit": limit, **({"cursor": cursor} if cursor else {})})
    try:
        status, payload = cloud_publication_request(
            "GET", f"/file-publication-retries/due-bindings?{query}"
        )
    except RuntimeNotReadyError:
        return PublicationWakePage(_wake_publication_workspaces(workspace_ids), None)
    next_cursor = payload.get("next_cursor") if 200 <= status < 300 else None
    binding_ids = payload.get("binding_ids") if 200 <= status < 300 else []
    if not isinstance(binding_ids, list) or len(binding_ids) > limit:
        binding_ids = []
    bindings: list[UUID] = []
    seen_bindings: set[UUID] = set()
    for binding_id in binding_ids:
        try:
            parsed = UUID(str(binding_id))
        except (TypeError, ValueError):
            continue
        if parsed not in seen_bindings:
            bindings.append(parsed)
            seen_bindings.add(parsed)
    cloud_workspaces: list[UUID] = []
    for binding_id in bindings:
        workspace_id = (
            PublicationIntent.objects.filter(
                cloud_binding_id=binding_id,
                manifest_digest__isnull=False,
                state__in=[
                    PublicationIntentState.FROZEN,
                    PublicationIntentState.REGISTERED,
                    PublicationIntentState.FAILED,
                ],
                profile__lifecycle_state=RuntimeProfileLifecycleState.ACTIVE,
            )
            .order_by("-updated_at", "workspace_id")
            .values_list("workspace_id", flat=True)
            .first()
        )
        if workspace_id is not None:
            cloud_workspaces.append(workspace_id)
    scheduled = list(dict.fromkeys([*workspace_ids, *cloud_workspaces]))[:limit]
    rendered_cursor = next_cursor if isinstance(next_cursor, str) else None
    if any(workspace_id not in scheduled for workspace_id in cloud_workspaces):
        rendered_cursor = cursor
    return PublicationWakePage(_wake_publication_workspaces(scheduled), rendered_cursor)


def _wake_publication_workspaces(workspace_ids: Sequence[UUID]) -> int:
    from .runtime_intents import request_execution_wake_locked

    woken = 0
    for workspace_id in dict.fromkeys(workspace_ids):
        with transaction.atomic():
            workspace = (
                Workspace.objects.select_for_update().filter(pk=workspace_id).first()
            )
            if workspace is None:
                continue
            request_execution_wake_locked(workspace)
            PublicationIntent.objects.filter(
                workspace=workspace,
                state=PublicationIntentState.REGISTERED,
                next_due_at__lte=timezone.now(),
            ).update(next_due_at=timezone.now() + timedelta(seconds=60))
            woken += 1
    return woken


def cloud_publication_request(
    method: str,
    path: str,
    *,
    body: Mapping[str, object] | None = None,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    """Call only the fixed internal Cloud publication boundary."""

    _require_publications_enabled()
    base_url = _validated_cloud_url(getattr(settings, "ALLIES_CLOUD_URL", None))
    token = getattr(settings, "ALLIES_CLOUD_EVENT_SERVICE_TOKEN", None)
    if not base_url or not token:
        raise RuntimeNotReadyError("file publication is not configured")
    payload = data
    request_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if body is not None:
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = Request(
        f"{base_url}/api/v1/internal/v1{path}",
        data=payload,
        headers=request_headers,
        method=method,
    )
    try:
        response = build_opener(_NoRedirect).open(request, timeout=120)
    except HTTPError as exc:
        try:
            content = exc.read(MAX_CLOUD_RESPONSE_BYTES + 1)
        finally:
            exc.close()
        return int(exc.code), _cloud_body(content)
    except (TimeoutError, URLError, OSError) as exc:
        raise RuntimeNotReadyError("file publication transport is unavailable") from exc
    try:
        return int(response.status), _cloud_body(
            response.read(MAX_CLOUD_RESPONSE_BYTES + 1)
        )
    finally:
        response.close()


def register_publication(
    context: RuntimeContext,
    attempt_id: UUID,
    lease_token: str,
    publication_id: UUID,
    files: Sequence[Mapping[str, object]],
) -> tuple[int, dict[str, object]]:
    """Reserve an already-frozen manifest through its original attempt scope."""

    frozen = _frozen_files(files)
    manifest_digest = _digest({"files": frozen})
    with transaction.atomic():
        attempt, _workspace, _profile = _active_attempt(
            context, attempt_id, lease_token
        )
        intent = (
            PublicationIntent.objects.select_for_update()
            .filter(pk=publication_id, execution_id=attempt.execution_id)
            .first()
        )
        if intent is None or intent.manifest_digest != manifest_digest:
            raise RuntimeLeaseConflictError(
                "publication snapshot does not match intent"
            )
        if intent.state == PublicationIntentState.FAILED and (
            intent.attempts >= MAX_PUBLICATION_ATTEMPTS
            or intent.next_due_at > timezone.now()
        ):
            raise RuntimeLeaseConflictError("publication retry is not due")
        if intent.state not in {
            PublicationIntentState.FROZEN,
            PublicationIntentState.REGISTERED,
            PublicationIntentState.READY,
            PublicationIntentState.FAILED,
        }:
            raise RuntimeLeaseConflictError("publication intent is not frozen")
        binding_id = intent.cloud_binding_id
        message_id = intent.cloud_message_id
    status, payload = cloud_publication_request(
        "POST",
        "/file-publications",
        body={
            "publication_id": str(publication_id),
            "binding_id": str(binding_id),
            "message_id": str(message_id),
            "files": frozen,
        },
        headers={"Idempotency-Key": str(publication_id)},
    )
    if 200 <= status < 300:
        _set_registered(publication_id, payload.get("revision"))
    else:
        _set_publication_failure(
            publication_id,
            str(payload.get("error_code") or "publication_unavailable"),
        )
        _project_publication_failure(publication_id)
    return status, payload


def upload_publication_file(
    context: RuntimeContext,
    profile_id: UUID,
    publication_id: UUID,
    file_id: UUID,
    generation: int,
    content: bytes,
    revision: int,
    lease_token: UUID | None = None,
) -> tuple[int, dict[str, object]]:
    """Forward one bounded frozen file with Cloud's revision fences intact."""

    if isinstance(generation, bool) or generation < 1:
        raise RuntimeValidationError("publication generation is invalid")
    if isinstance(revision, bool) or revision < 1:
        raise RuntimeValidationError("publication revision is invalid")
    if (
        not isinstance(content, bytes)
        or not 1 <= len(content) <= MAX_PUBLICATION_FILE_BYTES
    ):
        raise RuntimeValidationError("publication content is invalid")
    with transaction.atomic():
        _current_profile(context, profile_id)
        intent = _locked_intent(context, profile_id, publication_id)
        if (
            intent.state != PublicationIntentState.REGISTERED
            or intent.cloud_revision != revision
        ):
            raise RuntimeLeaseConflictError("publication is not registered")
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(content)),
        "X-Allies-Publication-Revision": str(revision),
    }
    if lease_token is not None:
        headers["X-Allies-Publication-Lease-Token"] = str(lease_token)
    status, payload = cloud_publication_request(
        "PUT",
        f"/file-publications/{publication_id}/files/{file_id}/content?generation={generation}",
        data=content,
        headers=headers,
    )
    if not 200 <= status < 300:
        _set_publication_failure(
            publication_id,
            str(payload.get("error_code") or "publication_unavailable"),
            revision=revision,
        )
        _project_publication_failure(publication_id)
    return status, payload


def get_publication(
    context: RuntimeContext, profile_id: UUID, publication_id: UUID
) -> tuple[int, dict[str, object]]:
    with transaction.atomic():
        _current_profile(context, profile_id)
        _locked_intent(context, profile_id, publication_id)
    status, payload = cloud_publication_request(
        "GET", f"/file-publications/{publication_id}"
    )
    if 200 <= status < 300 and payload.get("state") in {"ready", "failed"}:
        with transaction.atomic():
            _current_profile(context, profile_id)
            intent = _locked_intent(context, profile_id, publication_id)
            if payload.get("revision") == intent.cloud_revision:
                if payload["state"] == "ready":
                    intent.state = PublicationIntentState.READY
                elif intent.state != PublicationIntentState.READY:
                    intent.state = PublicationIntentState.FAILED
                    intent.attempts = MAX_PUBLICATION_ATTEMPTS
                intent.save(update_fields=["state", "attempts", "updated_at"])
    return status, payload


def claim_publication_retries(
    context: RuntimeContext, profile_id: UUID, limit: int
) -> tuple[dict[str, object], ...]:
    if isinstance(limit, bool) or not 1 <= limit <= MAX_RECOVERY_BATCH:
        raise RuntimeValidationError("publication retry limit must be from 1 to 20")
    with transaction.atomic():
        _current_profile(context, profile_id)
        bindings = list(
            PublicationIntent.objects.filter(
                workspace_id=context.workspace_id,
                profile_id=profile_id,
                state__in=[
                    PublicationIntentState.FROZEN,
                    PublicationIntentState.REGISTERED,
                    PublicationIntentState.FAILED,
                ],
            )
            .order_by("cloud_binding_id")
            .values_list("cloud_binding_id", flat=True)
            .distinct()[:limit]
        )
    items: list[dict[str, object]] = []
    for binding_id in bindings:
        remaining = limit - len(items)
        if remaining <= 0:
            break
        status, payload = cloud_publication_request(
            "POST",
            "/file-publication-retries/claim",
            body={"binding_id": str(binding_id), "limit": remaining},
        )
        if status >= 500:
            continue
        if status < 200 or status >= 300:
            raise RuntimeLeaseConflictError("publication retry claim was rejected")
        claimed = payload.get("items")
        if not isinstance(claimed, list):
            raise RuntimeValidationError("publication retry response was invalid")
        for item in claimed:
            if not isinstance(item, dict):
                continue
            if _admit_cloud_retry(context, profile_id, binding_id, item):
                items.append(item)
    return tuple(items[:limit])


def _admit_cloud_retry(
    context: RuntimeContext,
    profile_id: UUID,
    binding_id: UUID,
    item: Mapping[str, object],
) -> bool:
    try:
        publication_id = UUID(str(item.get("publication_id")))
    except (TypeError, ValueError):
        return False
    revision = item.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        return False
    with transaction.atomic():
        _current_profile(context, profile_id)
        intent = (
            PublicationIntent.objects.select_for_update()
            .filter(
                pk=publication_id,
                profile_id=profile_id,
                workspace_id=context.workspace_id,
            )
            .first()
        )
        if (
            intent is None
            or intent.manifest_digest is None
            or intent.cloud_binding_id != binding_id
            or intent.state
            not in {
                PublicationIntentState.FROZEN,
                PublicationIntentState.REGISTERED,
                PublicationIntentState.FAILED,
            }
        ):
            return False
        if intent.cloud_revision is not None and revision < intent.cloud_revision:
            return False
        if revision == intent.cloud_revision:
            if intent.state == PublicationIntentState.REGISTERED:
                return True
            if intent.cloud_retry_revision != revision:
                return False
        intent.state = PublicationIntentState.REGISTERED
        intent.cloud_revision = revision
        intent.cloud_retry_revision = revision
        intent.safe_error_code = ""
        intent.save(
            update_fields=[
                "state",
                "cloud_revision",
                "cloud_retry_revision",
                "safe_error_code",
                "updated_at",
            ]
        )
    return True


def record_publication_retry(
    context: RuntimeContext,
    profile_id: UUID,
    publication_id: UUID,
    revision: int,
    lease_token: UUID,
    outcome: str,
    safe_error_code: str | None = None,
) -> tuple[int, dict[str, object]]:
    if outcome not in {"submitted", "failed"}:
        raise RuntimeValidationError("publication retry outcome is invalid")
    if isinstance(revision, bool) or revision < 1:
        raise RuntimeValidationError("publication revision is invalid")
    if safe_error_code is not None and not _SAFE_ERROR.fullmatch(safe_error_code):
        raise RuntimeValidationError("publication error code is invalid")
    with transaction.atomic():
        _current_profile(context, profile_id)
        intent = _locked_intent(context, profile_id, publication_id)
        if intent.cloud_revision != revision:
            raise RuntimeLeaseConflictError("publication retry revision is stale")
    body: dict[str, object] = {
        "revision": revision,
        "lease_token": str(lease_token),
        "outcome": outcome,
    }
    if safe_error_code is not None:
        body["safe_error_code"] = safe_error_code
    status, payload = cloud_publication_request(
        "POST", f"/file-publications/{publication_id}/retry-result", body=body
    )
    if outcome == "failed" and 200 <= status < 300:
        _set_publication_failure(
            publication_id,
            safe_error_code or "publication_unavailable",
            revision=revision,
        )
    return status, payload


def _set_registered(publication_id: UUID, revision: object) -> None:
    with transaction.atomic():
        intent = (
            PublicationIntent.objects.select_for_update()
            .filter(pk=publication_id)
            .first()
        )
        if (
            intent is None
            or intent.manifest_digest is None
            or intent.state == PublicationIntentState.READY
        ):
            return
        if (
            isinstance(revision, int)
            and not isinstance(revision, bool)
            and revision > 0
        ):
            intent.cloud_revision = revision
        intent.state = PublicationIntentState.REGISTERED
        intent.safe_error_code = ""
        intent.save(
            update_fields=["state", "safe_error_code", "cloud_revision", "updated_at"]
        )


def _register_frozen_intent(
    publication_id: UUID, files: Sequence[Mapping[str, object]]
) -> None:
    if not getattr(settings, "ALLIES_CLOUD_URL", None) or not getattr(
        settings, "ALLIES_CLOUD_EVENT_SERVICE_TOKEN", None
    ):
        return
    intent = PublicationIntent.objects.filter(pk=publication_id).first()
    if intent is None:
        return
    status, payload = cloud_publication_request(
        "POST",
        "/file-publications",
        body={
            "publication_id": str(intent.id),
            "binding_id": str(intent.cloud_binding_id),
            "message_id": str(intent.cloud_message_id),
            "files": [dict(item) for item in files],
        },
        headers={"Idempotency-Key": str(intent.id)},
    )
    if 200 <= status < 300:
        _set_registered(intent.id, payload.get("revision"))
        return
    _set_publication_failure(
        intent.id, str(payload.get("error_code") or "publication_unavailable")
    )
    _project_publication_failure(intent.id)


def _project_publication_failure(publication_id: UUID) -> None:
    """Create Cloud's safe, non-downgrading failure placeholder."""

    intent = PublicationIntent.objects.filter(pk=publication_id).first()
    if intent is None:
        return
    try:
        cloud_publication_request(
            "POST",
            "/file-publication-status",
            body={
                "publication_id": str(intent.id),
                "binding_id": str(intent.cloud_binding_id),
                "message_id": str(intent.cloud_message_id),
                "state": "failed",
                "error_code": "publication_unavailable",
            },
        )
    except RuntimeNotReadyError:
        return


def _set_publication_failure(
    publication_id: UUID, error_code: str, *, revision: int | None = None
) -> None:
    if not _SAFE_ERROR.fullmatch(error_code):
        error_code = "publication_unavailable"
    with transaction.atomic():
        intent = (
            PublicationIntent.objects.select_for_update()
            .filter(pk=publication_id)
            .first()
        )
        if (
            intent is None
            or intent.manifest_digest is None
            or intent.state == PublicationIntentState.READY
        ):
            return
        if (
            revision is not None
            and intent.state == PublicationIntentState.FAILED
            and intent.cloud_revision == revision
        ):
            return
        if intent.attempts >= MAX_PUBLICATION_ATTEMPTS:
            intent.state = PublicationIntentState.FAILED
            intent.safe_error_code = error_code
            intent.save(update_fields=["state", "safe_error_code", "updated_at"])
            return
        intent.attempts += 1
        intent.state = PublicationIntentState.FAILED
        intent.safe_error_code = error_code
        intent.next_due_at = timezone.now() + timedelta(
            seconds=_BACKOFF_SECONDS[
                min(intent.attempts - 1, len(_BACKOFF_SECONDS) - 1)
            ]
        )
        intent.save(
            update_fields=[
                "attempts",
                "state",
                "safe_error_code",
                "next_due_at",
                "updated_at",
            ]
        )


def _active_attempt(
    context: RuntimeContext, attempt_id: UUID, lease_token: str
) -> tuple[Attempt, Workspace, RuntimeProfile]:
    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    token_digest = digest_lease_token(lease_token)
    attempt = (
        Attempt.objects.select_for_update()
        .select_related("execution__workspace", "execution__profile")
        .filter(pk=attempt_id, execution__workspace_id=context.workspace_id)
        .first()
    )
    if attempt is None:
        raise RuntimeLeaseConflictError("attempt is not in this workspace")
    execution = attempt.execution
    workspace = execution.workspace
    profile = execution.profile
    lease = Lease.objects.select_for_update().filter(attempt_id=attempt.id).first()
    if (
        workspace.machine_generation != context.machine_generation
        or attempt.machine_generation != context.machine_generation
        or lease is None
        or lease.profile_id != profile.id
        or lease.token_digest != token_digest
        or lease.machine_generation != context.machine_generation
        or lease.state != LeaseState.ACTIVE
        or lease.expires_at <= timezone.now()
    ):
        raise RuntimeLeaseConflictError("lease does not authorize publication")
    if not profile_allows_runtime_write(profile):
        raise RuntimeLeaseConflictError("profile lifecycle is not active")
    if (
        execution.source_kind != "conversation_message"
        or execution.cloud_binding_id is None
        or execution.cloud_message_id is None
    ):
        raise RuntimeLeaseConflictError("execution has no publication authority")
    return attempt, workspace, profile


def _current_profile(context: RuntimeContext, profile_id: UUID) -> RuntimeProfile:
    if not isinstance(context, RuntimeContext):
        raise RuntimeValidationError("runtime context is required")
    workspace = (
        Workspace.objects.select_for_update().filter(pk=context.workspace_id).first()
    )
    profile = (
        RuntimeProfile.objects.select_for_update()
        .filter(pk=profile_id, workspace_id=context.workspace_id)
        .first()
    )
    if workspace is None or profile is None:
        raise RuntimeLeaseConflictError("profile is not in this workspace")
    if workspace.machine_generation != context.machine_generation:
        raise RuntimeFencedError("runtime generation is stale")
    if not profile_allows_runtime_write(profile):
        raise RuntimeLeaseConflictError("profile lifecycle is not active")
    return profile


def _locked_intent(
    context: RuntimeContext, profile_id: UUID, publication_id: UUID
) -> PublicationIntent:
    intent = (
        PublicationIntent.objects.select_for_update()
        .filter(
            pk=publication_id,
            profile_id=profile_id,
            workspace_id=context.workspace_id,
        )
        .first()
    )
    if intent is None:
        raise RuntimeLeaseConflictError("publication intent is not in this profile")
    return intent


def _prepared_files(files: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
        raise RuntimeValidationError("publication files are invalid")
    if not 1 <= len(files) <= MAX_PUBLICATION_FILES:
        raise RuntimeValidationError("publication must contain from 1 to 10 files")
    output: list[dict[str, object]] = []
    total = 0
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"name", "size"}:
            raise RuntimeValidationError("publication file descriptor is invalid")
        name = item.get("name")
        size = item.get("size")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 255
            or "\x00" in name
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 1 <= size <= MAX_PUBLICATION_FILE_BYTES
        ):
            raise RuntimeValidationError("publication file descriptor is invalid")
        total += size
        output.append({"name": name, "size": size})
    if total > MAX_PUBLICATION_BYTES:
        raise RuntimeValidationError("publication file set exceeds 50 MB")
    return output


def _frozen_files(files: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
        raise RuntimeValidationError("frozen publication files are invalid")
    if not 1 <= len(files) <= MAX_PUBLICATION_FILES:
        raise RuntimeValidationError("publication must contain from 1 to 10 files")
    output: list[dict[str, object]] = []
    total = 0
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {
            "source_version_id",
            "name",
            "size",
            "sha256",
        }:
            raise RuntimeValidationError(
                "frozen publication file descriptor is invalid"
            )
        try:
            source_version_id = str(UUID(str(item.get("source_version_id"))))
        except (TypeError, ValueError) as exc:
            raise RuntimeValidationError(
                "publication source version is invalid"
            ) from exc
        name = item.get("name")
        size = item.get("size")
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or not 1 <= len(name) <= 255
            or "\x00" in name
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 1 <= size <= MAX_PUBLICATION_FILE_BYTES
            or not isinstance(digest, str)
            or not _SHA256.fullmatch(digest)
        ):
            raise RuntimeValidationError(
                "frozen publication file descriptor is invalid"
            )
        total += size
        output.append(
            {
                "source_version_id": source_version_id,
                "name": name,
                "size": size,
                "sha256": digest,
            }
        )
    if total > MAX_PUBLICATION_BYTES:
        raise RuntimeValidationError("publication file set exceeds 50 MB")
    return output


def _tool_call_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value.encode("utf-8")) <= 255
        or any(character in value for character in "\x00\r\n")
    ):
        raise RuntimeValidationError("publication tool call identity is invalid")
    return value


def _receipt(intent: PublicationIntent) -> PublicationIntentReceipt:
    return PublicationIntentReceipt(
        publication_id=intent.id,
        state=intent.state,
        manifest_digest=intent.manifest_digest,
        next_due_at=intent.next_due_at,
    )


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _cloud_body(content: bytes) -> dict[str, object]:
    if len(content) > MAX_CLOUD_RESPONSE_BYTES:
        return {"error_code": "publication_response_too_large"}
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"error_code": "publication_response_invalid"}
    if not isinstance(value, dict):
        return {"error_code": "publication_response_invalid"}
    data = value.get("data")
    if value.get("status") == "success" and isinstance(data, dict):
        return data
    if value.get("status") == "error" and isinstance(data, dict):
        code = data.get("code")
        return {"error_code": code if isinstance(code, str) else "publication_rejected"}
    return {"error_code": "publication_response_invalid"}


def _require_publications_enabled() -> None:
    if not getattr(settings, "ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED", False):
        raise RuntimeNotReadyError("file publication is disabled")


__all__ = [
    "MAX_PUBLICATION_ATTEMPTS",
    "MAX_RECOVERY_BATCH",
    "PublicationIntentReceipt",
    "PublicationWakePage",
    "acknowledge_frozen_publication",
    "claim_publication_retries",
    "cloud_publication_request",
    "create_publication_intent",
    "get_publication",
    "record_publication_retry",
    "register_publication",
    "upload_publication_file",
    "wake_due_publications",
]
