from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


class FileManifestRequest(Schema):
    model_config = ConfigDict(extra="forbid")
    client_id: UUID
    name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^[^\\/\x00-\x1f\x7f]+$",
    )
    size: int = Field(ge=1, le=25_000_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SendFilesRequest(Schema):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=16_000)
    files: list[FileManifestRequest] = Field(min_length=1, max_length=10)


class ReservedFileResponse(Schema):
    id: str
    generation: int
    state: str


class ReservedMessageResponse(Schema):
    id: str
    sequence: int
    status: str
    preparation: str
    revision: int


class FileReservationResponse(Schema):
    message: ReservedMessageResponse
    files: list[ReservedFileResponse]
    replayed: bool


class UploadFileResponse(Schema):
    id: str
    state: str
    generation: int


class RevisionRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)


class FileRetryRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    generation: int = Field(ge=1)


class FileMessageResponse(Schema):
    id: str
    status: str
    preparation: str
    revision: int


class DraftFileResponse(Schema):
    id: str
    name: str
    state: str


class FileDraftResponse(Schema):
    id: str
    content: str
    files: list[DraftFileResponse]


class FileDraftDiscardResponse(Schema):
    discarded: bool


class FileCancellationResponse(Schema):
    message: FileMessageResponse
    draft: FileDraftResponse


class PublicationFileRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    source_version_id: UUID
    name: str = Field(min_length=1, max_length=255, pattern=r"^[^\\/\x00-\x1f\x7f]+$")
    size: int = Field(ge=1, le=25_000_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PublicationRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    binding_id: UUID
    message_id: UUID
    publication_id: UUID
    files: list[PublicationFileRequest] = Field(min_length=1, max_length=10)


class PublicationStatusRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    binding_id: UUID
    message_id: UUID
    publication_id: UUID
    state: str = Field(pattern=r"^failed$")
    error_code: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class PublicationRetryClaimRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    binding_id: UUID
    limit: int = Field(ge=1, le=20)


class PublicationRetryResultRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    lease_token: UUID
    outcome: str = Field(pattern=r"^(submitted|failed)$")
    safe_error_code: str = Field(default="", pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class PublicationRetryRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
