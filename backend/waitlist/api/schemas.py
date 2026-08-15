"""Versioned browser contract for the waitlist preview."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import Field


class WaitlistAcknowledgement(Schema):
    operation: str
    result_revision: int
    result_lifecycle: str


class WaitlistConfigurationRequest(Schema):
    revision: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=80)
    appearance_catalog_version: str | None = Field(default=None, max_length=32)
    appearance_key: str | None = Field(default=None, max_length=128)
    job: str | None = Field(default=None, max_length=1200)
    personality: str | None = Field(default=None, max_length=1200)


class WaitlistGreetingRequest(Schema):
    revision: int = Field(gt=0)


class WaitlistReplyRequest(Schema):
    revision: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)


class WaitlistJoinRequest(Schema):
    revision: int = Field(gt=0)
    email: str = Field(min_length=3, max_length=254)
    consent_version: str = Field(min_length=1, max_length=64)


class WaitlistSnapshot(Schema):
    id: str
    revision: int
    lifecycle: str
    configuration: dict[str, str]
    greeting: dict[str, Any] | None = None
    reply: dict[str, Any] | None = None
    join: dict[str, Any] | None = None
    timestamps: dict[str, datetime | None]


class WaitlistJoinConfirmation(Schema):
    operation: str
    result_revision: int
    result_lifecycle: str
    email: str | None = None
