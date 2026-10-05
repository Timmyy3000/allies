import re
import secrets
from typing import Annotated
from urllib.parse import quote

from django.conf import settings
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from ninja import Header, Query
from ninja_extra import (
    ControllerBase,
    api_controller,
    http_delete,
    http_get,
    http_post,
    http_put,
)

from auths.api.common import (
    _require_origin,
    _session,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse
from auths.exceptions import SessionInvalid, WorkspaceAccessDenied
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit
from chat.api.controllers import _read_error
from chat.exceptions import IdempotencyConflict, QueueFull
from common.uuids import CanonicalUUID
from files.api.schemas import (
    FileCancellationResponse,
    FileDraftDiscardResponse,
    FileDraftResponse,
    FileMessageResponse,
    FileReservationResponse,
    FileRetryRequest,
    PublicationRequest,
    PublicationRetryClaimRequest,
    PublicationRetryRequest,
    PublicationRetryResultRequest,
    PublicationStatusRequest,
    RevisionRequest,
    SendFilesRequest,
    UploadFileResponse,
)
from files.exceptions import (
    FileAdmissionDisabled,
    FileConflict,
    FileScopeUnavailable,
    FileTooLarge,
    FileUnavailable,
    FileValidation,
)
from files.services.access import (
    accepted_file_stream,
    open_file,
    private_file_preview,
    private_file_stream,
)
from files.services.intake import receive_file, reserve_send
from files.services.preparation import (
    arm_file_message,
    cancel_file_message,
    discard_file_draft,
    file_draft,
    remove_inbound_file,
    retry_inbound_file,
)
from files.services.publication import (
    claim_publication_retries,
    create_publication_placeholder,
    due_publication_bindings,
    owner_publication_view,
    publication_retry_result,
    publication_transport_scope,
    publication_view,
    receive_publication_file,
    reserve_publication,
    retry_publication,
)


def _error(exc: Exception, request: HttpRequest):
    if isinstance(exc, SessionInvalid):
        return error_json("session_invalid", "session invalid", 401)
    if isinstance(exc, (WorkspaceAccessDenied, FileScopeUnavailable)):
        return error_json("file_unavailable", "file unavailable", 404)
    if isinstance(exc, FileAdmissionDisabled):
        return error_json("file_admission_disabled", "file admission unavailable", 404)
    if isinstance(exc, FileValidation):
        return error_json("validation_error", "request validation failed", 422)
    if isinstance(exc, FileTooLarge):
        return error_json("file_too_large", "file too large", 413)
    if isinstance(exc, (FileConflict, IdempotencyConflict)):
        return error_json("file_conflict", "request conflicts", 409)
    if isinstance(exc, FileUnavailable):
        return error_json("storage_unavailable", "private storage unavailable", 503)
    if isinstance(exc, QueueFull):
        return error_json("rate_limited", "Request temporarily unavailable", 429)
    return _read_error(exc, request)


def _reservation(result):
    return FileReservationResponse(
        message={
            "id": str(result.message.id),
            "sequence": result.message.sequence,
            "status": result.message.status,
            "preparation": result.message.preparation,
            "revision": result.message.preparation_revision,
        },
        files=[
            {"id": str(file.id), "generation": file.generation, "state": file.state}
            for file in result.files
        ],
        replayed=result.replayed,
    )


def _message(result) -> FileMessageResponse:
    return FileMessageResponse(
        id=str(result.id),
        status=result.status,
        preparation=result.preparation,
        revision=result.preparation_revision,
    )


def _draft(result) -> FileDraftResponse:
    return FileDraftResponse(
        id=str(result.draft.id),
        content=result.draft.content,
        files=[
            {"id": str(file.id), "name": file.original_name, "state": file.state}
            for file in result.files
        ],
    )


_required_query = Query(...)


@api_controller("/workspaces/{workspace_id}", tags=["Files"])
class FileAdmissionController(ControllerBase):
    @http_post(
        "/conversations/{conversation_id}/file-messages",
        response={
            202: SuccessResponse[FileReservationResponse],
            **error_responses(401, 403, 404, 409, 422, 429, 500),
        },
    )
    def reserve(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        payload: SendFilesRequest,
        idempotency_key: Annotated[
            str, Header(alias="Idempotency-Key", min_length=16, max_length=128)
        ],
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            session = _session(request)
            result = reserve_send(
                user=session.user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                content=payload.content,
                files=[item.model_dump(mode="json") for item in payload.files],
                key=idempotency_key,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(_reservation(result), "File message reserved", status=202)

    @http_put(
        "/allies/{ally_id}/files/{file_id}/content",
        response={
            202: SuccessResponse[UploadFileResponse],
            **error_responses(401, 403, 404, 409, 413, 422, 500, 503),
        },
    )
    def upload(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        file_id: CanonicalUUID,
        generation: int = Query(..., ge=1),
        content_length: Annotated[str | None, Header(alias="Content-Length")] = None,
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        if request.content_type != "application/octet-stream":
            return error_json("validation_error", "request validation failed", 422)
        try:
            session = _session(request)
            result = receive_file(
                user=session.user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                file_id=file_id,
                generation=generation,
                content_length=content_length,
                stream=request,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            UploadFileResponse(
                id=str(result.id), state=result.state, generation=result.generation
            ),
            "File accepted for validation",
            status=202,
        )

    @http_post(
        "/allies/{ally_id}/files/{file_id}/retry",
        response={
            200: SuccessResponse[UploadFileResponse],
            **error_responses(401, 403, 404, 409, 422, 500),
        },
    )
    def retry_file(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        file_id: CanonicalUUID,
        payload: FileRetryRequest,
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            result = retry_inbound_file(
                user=_session(request).user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                file_id=file_id,
                generation=payload.generation,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            UploadFileResponse(
                id=str(result.id), state=result.state, generation=result.generation
            ),
            "File retry prepared",
        )

    @http_delete(
        "/conversations/{conversation_id}/messages/{message_id}/files/{file_id}",
        response={
            200: SuccessResponse[FileMessageResponse],
            **error_responses(401, 403, 404, 409, 422, 500),
        },
    )
    def remove_file(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        message_id: CanonicalUUID,
        file_id: CanonicalUUID,
        revision: int = Query(..., ge=0),
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            result = remove_inbound_file(
                user=_session(request).user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=message_id,
                file_id=file_id,
                revision=revision,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(_message(result), "File removed")

    @http_post(
        "/conversations/{conversation_id}/messages/{message_id}/send-files",
        response={
            200: SuccessResponse[FileMessageResponse],
            **error_responses(401, 403, 404, 409, 422, 500),
        },
    )
    def send_files(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        message_id: CanonicalUUID,
        payload: RevisionRequest,
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            result = arm_file_message(
                user=_session(request).user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=message_id,
                revision=payload.revision,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(_message(result), "File message prepared")

    @http_post(
        "/conversations/{conversation_id}/messages/{message_id}/cancel-files",
        response={
            200: SuccessResponse[FileCancellationResponse],
            **error_responses(401, 403, 404, 409, 422, 500),
        },
    )
    def cancel_files(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        message_id: CanonicalUUID,
        payload: RevisionRequest,
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            result = cancel_file_message(
                user=_session(request).user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=message_id,
                revision=payload.revision,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            FileCancellationResponse(
                message=_message(result.draft.message), draft=_draft(result)
            ),
            "File message cancelled",
        )

    @http_get(
        "/conversations/{conversation_id}/messages/{message_id}/file-draft",
        response={
            200: SuccessResponse[FileDraftResponse],
            **error_responses(401, 403, 404, 500),
        },
    )
    def get_draft(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        message_id: CanonicalUUID,
    ):
        try:
            result = file_draft(
                user=_session(request).user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(_draft(result), "File draft read")

    @http_delete(
        "/conversations/{conversation_id}/messages/{message_id}/file-draft",
        response={
            200: SuccessResponse[FileDraftDiscardResponse],
            **error_responses(401, 403, 404, 500),
        },
    )
    def discard_draft(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        conversation_id: CanonicalUUID,
        message_id: CanonicalUUID,
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            discarded = discard_file_draft(
                user=_session(request).user,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            FileDraftDiscardResponse(discarded=discarded), "File draft discarded"
        )


def _foundry_token_valid(request: HttpRequest) -> bool:
    value = request.headers.get("Authorization", "")
    configured = str(getattr(settings, "ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN", ""))
    if not configured or not value.startswith("Bearer "):
        return False
    return secrets.compare_digest(value[7:].encode(), configured.encode())


@api_controller("/internal/v1", tags=["Files"])
class AcceptedFileController(ControllerBase):
    @http_get("/accepted-files/{file_id}/content")
    def content(
        self,
        request: HttpRequest,
        file_id: CanonicalUUID,
        binding_id: CanonicalUUID = _required_query,
        message_id: CanonicalUUID = _required_query,
    ):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        try:
            accepted = accepted_file_stream(
                binding_id=binding_id, message_id=message_id, file_id=file_id
            )
        except FileScopeUnavailable:
            return error_json("file_unavailable", "file unavailable", 404)
        except FileUnavailable:
            return error_json("storage_unavailable", "private storage unavailable", 503)
        response = StreamingHttpResponse(
            accepted.content,
            content_type=accepted.file.media_type,
        )
        response["Content-Length"] = str(accepted.file.actual_size)
        response["X-Content-Type-Options"] = "nosniff"
        return response


@api_controller("/internal/v1", tags=["Files"])
class FilePublicationController(ControllerBase):
    @http_post("/file-publication-status")
    def status(self, request: HttpRequest, payload: PublicationStatusRequest):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        try:
            result = create_publication_placeholder(
                binding_id=payload.binding_id,
                message_id=payload.message_id,
                publication_id=payload.publication_id,
                error_code=payload.error_code,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(result, "Publication status recorded", status=202)

    @http_post("/file-publications")
    def reserve(self, request: HttpRequest, payload: PublicationRequest):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        try:
            result = reserve_publication(
                binding_id=payload.binding_id,
                message_id=payload.message_id,
                publication_id=payload.publication_id,
                files=[item.model_dump(mode="json") for item in payload.files],
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(result, "Publication reserved", status=202)

    @http_get("/file-publications/{publication_id}")
    def detail(self, request: HttpRequest, publication_id: CanonicalUUID):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        try:
            result = publication_view(publication_id=publication_id)
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(result, "Publication read")

    @http_put("/file-publications/{publication_id}/files/{file_id}/content")
    def upload(
        self,
        request: HttpRequest,
        publication_id: CanonicalUUID,
        file_id: CanonicalUUID,
        generation: int = Query(..., ge=1),
        revision: Annotated[
            int, Header(alias="X-Allies-Publication-Revision", ge=1)
        ] = 1,
        lease_token: Annotated[
            str | None, Header(alias="X-Allies-Publication-Lease-Token")
        ] = None,
        content_length: Annotated[str | None, Header(alias="Content-Length")] = None,
    ):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        if request.content_type != "application/octet-stream":
            return error_json("validation_error", "request validation failed", 422)
        try:
            binding_id, message_id = publication_transport_scope(
                publication_id=publication_id
            )
            result = receive_publication_file(
                binding_id=binding_id,
                message_id=message_id,
                publication_id=publication_id,
                file_id=file_id,
                generation=generation,
                revision=revision,
                lease_token=lease_token,
                content_length=content_length,
                stream=request,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            UploadFileResponse(
                id=str(result.id), state=result.state, generation=result.generation
            ),
            "Publication file accepted for validation",
            status=202,
        )

    @http_post("/file-publication-retries/claim")
    def claim(self, request: HttpRequest, payload: PublicationRetryClaimRequest):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        try:
            claims = claim_publication_retries(
                binding_id=payload.binding_id, limit=payload.limit
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            {
                "items": [
                    {
                        "publication_id": str(claim.publication.id),
                        "binding_id": str(claim.publication.binding_id),
                        "revision": claim.publication.revision,
                        "lease_token": str(claim.publication.lease_token),
                        "lease_until": claim.publication.lease_until.isoformat(),
                        "files": [
                            {
                                "id": str(file.id),
                                "source_version_id": str(file.source_version_id),
                                "size": file.expected_size,
                                "sha256": file.sha256,
                                "generation": file.generation,
                                "state": file.state,
                            }
                            for file in claim.files
                        ],
                    }
                    for claim in claims
                ]
            },
            "Publication retries claimed",
        )

    @http_post("/file-publications/{publication_id}/retry-result")
    def retry_result(
        self,
        request: HttpRequest,
        publication_id: CanonicalUUID,
        payload: PublicationRetryResultRequest,
    ):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        try:
            result = publication_retry_result(
                publication_id=publication_id,
                revision=payload.revision,
                lease_token=payload.lease_token,
                outcome=payload.outcome,
                safe_error_code=payload.safe_error_code,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(result, "Publication retry recorded")

    @http_get("/file-publication-retries/due-bindings")
    def due_bindings(
        self,
        request: HttpRequest,
        limit: int = Query(..., ge=1, le=20),
        cursor: str | None = None,
    ):
        if not _foundry_token_valid(request):
            return error_json("service_invalid", "service invalid", 401)
        try:
            binding_ids, next_cursor = due_publication_bindings(
                limit=limit, cursor=cursor
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            {"binding_ids": binding_ids, "next_cursor": next_cursor},
            "Due bindings read",
        )


@api_controller("/workspaces/{workspace_id}", tags=["Files"])
class OwnerPublicationController(ControllerBase):
    @http_get("/allies/{ally_id}/messages/{message_id}/publications/{publication_id}")
    def detail(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        message_id: CanonicalUUID,
        publication_id: CanonicalUUID,
    ):
        try:
            result = owner_publication_view(
                user=_session(request).user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                message_id=message_id,
                publication_id=publication_id,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(result, "Publication read")

    @http_post(
        "/allies/{ally_id}/messages/{message_id}/publications/{publication_id}/retry"
    )
    def retry(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        message_id: CanonicalUUID,
        publication_id: CanonicalUUID,
        payload: PublicationRetryRequest,
    ):
        if rejected := _require_origin(request, allow_native_bearer=True):
            return rejected
        try:
            result = retry_publication(
                user=_session(request).user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                message_id=message_id,
                publication_id=publication_id,
                revision=payload.revision,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(result, "Publication retry prepared", status=202)


def _range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if match is None:
        return None
    first, last = match.groups()
    try:
        if first:
            start = int(first)
            end = int(last) if last else size - 1
        elif last:
            length = int(last)
            if length < 1:
                return None
            start, end = max(0, size - length), size - 1
        else:
            return None
    except ValueError:
        return None
    return (start, end) if 0 <= start <= end < size else None


def _preview_kind(media_type: str) -> str:
    if media_type.startswith("image/"):
        return "image"
    if media_type == "application/pdf":
        return "pdf"
    if media_type.startswith("text/") or media_type in {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/toml",
    }:
        return "text"
    return "none"


@api_controller("/workspaces/{workspace_id}", tags=["Files"])
class PrivateFileController(ControllerBase):
    @http_get("/allies/{ally_id}/files/{file_id}")
    def metadata(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        file_id: CanonicalUUID,
    ):
        try:
            opened = open_file(
                user=_session(request).user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                file_id=file_id,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        return success_json(
            {
                "id": str(opened.file.id),
                "name": opened.file.original_name,
                "type": opened.file.media_type,
                "size": opened.size,
                "preview_kind": _preview_kind(opened.file.media_type),
                "state": opened.file.state,
                "open_path": f"/files/{opened.file.id}",
            },
            "File metadata read",
        )

    @http_get("/allies/{ally_id}/files/{file_id}/download")
    def download(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        file_id: CanonicalUUID,
    ):
        try:
            opened = open_file(
                user=_session(request).user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                file_id=file_id,
            )
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        selected = _range(request.headers.get("Range"), opened.size)
        if selected is None:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{opened.size}"
            return response
        start, end = selected
        try:
            stream = private_file_stream(opened=opened, start=start, end=end)
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        response = StreamingHttpResponse(
            stream,
            status=206 if request.headers.get("Range") else 200,
            content_type="application/octet-stream",
        )
        response["Accept-Ranges"] = "bytes"
        response["Content-Length"] = str(end - start + 1)
        response["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(
            opened.file.original_name
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        if request.headers.get("Range"):
            response["Content-Range"] = f"bytes {start}-{end}/{opened.size}"
        return response

    @http_get("/allies/{ally_id}/files/{file_id}/preview")
    def preview(
        self,
        request: HttpRequest,
        workspace_id: CanonicalUUID,
        ally_id: CanonicalUUID,
        file_id: CanonicalUUID,
    ):
        try:
            opened = open_file(
                user=_session(request).user,
                workspace_id=workspace_id,
                ally_id=ally_id,
                file_id=file_id,
            )
            check_rate_limit(
                scope="file-preview",
                identity=str(opened.file.owner_id),
                limit=20,
                period=60,
            )
            preview = private_file_preview(opened=opened)
        except ThrottleExceeded:
            return error_json("throttled", "try again later", 429)
        except ThrottleUnavailable:
            return error_json("throttle_unavailable", "storage unavailable", 503)
        except Exception as exc:
            if response := _error(exc, request):
                return response
            raise
        if preview.content is None or preview.media_type is None:
            return error_json(
                "preview_unavailable",
                "preview unavailable",
                409,
                details={"code": preview.safe_error_code or "preview_unavailable"},
            )
        response = HttpResponse(preview.content, content_type=preview.media_type)
        response["Cache-Control"] = "private, no-store"
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
        response["X-Content-Type-Options"] = "nosniff"
        return response
