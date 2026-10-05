from ninja import Schema
from pydantic import Field


class WaitlistEntryRequest(Schema):
    attempt_id: str = Field(min_length=16, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    appearance_catalog_version: str = Field(min_length=1, max_length=32)
    appearance_key: str = Field(min_length=1, max_length=128)
    job: str = Field(min_length=1, max_length=1200)
    personality: str = Field(default="", max_length=1200)


class WaitlistEntryResponse(Schema):
    attempt_token: str
    greeting: str


class WaitlistEntryCompletionRequest(Schema):
    attempt_token: str = Field(min_length=32, max_length=256)
    reply: str = Field(min_length=1, max_length=4000)
    email: str = Field(min_length=3, max_length=254)
    consent_version: str = Field(min_length=1, max_length=64)


class WaitlistEntryCompletionResponse(Schema):
    email: str
