from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

from allies.services.labels import normalize_label
from allies.services.onboarding import normalize_multiline_field


class AppearanceInput(Schema):
    model_config = ConfigDict(extra="forbid")

    catalog_version: str = Field(min_length=1, max_length=32)
    key: str = Field(min_length=1, max_length=128)


class AllySeedInput(Schema):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    job: str = Field(min_length=1, max_length=200)
    personality: str = Field(min_length=1, max_length=4000)
    appearance: AppearanceInput

    @field_validator("job", mode="before")
    @classmethod
    def _normalize_job(cls, value: object) -> str:
        return normalize_multiline_field(value, max_length=200)

    @field_validator("personality", mode="before")
    @classmethod
    def _normalize_personality(cls, value: object) -> str:
        return normalize_multiline_field(value, max_length=4000)


class OnboardingAttemptRequest(AllySeedInput):
    pass


class OnboardingAttemptResponse(Schema):
    attempt_token: str
    greeting: str


class CreateAllyRequest(AllySeedInput):
    onboarding_attempt: str = Field(min_length=32, max_length=256)
    reply: str = Field(min_length=1, max_length=4000)


class AllyResponse(Schema):
    id: UUID
    binding_id: UUID
    operation_id: UUID
    name: str
    job: str
    personality: str
    appearance: AppearanceInput
    provisioning_state: str
    retryable: bool
    label: str = ""
    show_label: bool = False
    settings_revision: int = 0
    deletion_state: Literal["active", "pending", "repair_required"] = "active"
    recent_activity: bool = False


class AllyListResponse(Schema):
    allies: list[AllyResponse]


class AllySettingsRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    label: StrictStr = Field(max_length=80)
    show_label: StrictBool
    settings_revision: StrictInt = Field(ge=0)
    appearance: AppearanceInput | None = None

    @field_validator("label", mode="before")
    @classmethod
    def _normalize_label(cls, value: str) -> str:
        return normalize_label(value)


class AllyDeletionRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    confirmation: StrictStr = Field(min_length=1, max_length=128)

    @field_validator("confirmation")
    @classmethod
    def _validate_confirmation(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("confirmation is invalid")
        return value


class AllyDeletionResponse(Schema):
    ally_id: UUID
    operation_id: UUID | None = None
    state: Literal["pending", "complete", "repair_required"]
    retryable: StrictBool
    safe_error_code: StrictStr = Field(
        default="", max_length=64, pattern=r"^(?:[a-z][a-z0-9_]*)?$"
    )


class RuntimeIntentRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["composing_started"]
    occurred_at: AwareDatetime


class WorkspaceRuntimeIntentRequest(Schema):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, le=1)
    intent: Literal["ally_creation_started"]
    occurred_at: AwareDatetime


class RuntimeIntentResponse(Schema):
    status: Literal[
        "disabled",
        "already_ready",
        "waking",
        "ready",
        "first_provision_required",
        "rate_limited",
        "failed",
    ]
