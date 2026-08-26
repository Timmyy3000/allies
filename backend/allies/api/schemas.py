from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


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
