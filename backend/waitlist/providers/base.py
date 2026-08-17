"""Narrow synchronous greeting provider contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderUnknownError(Exception):
    """The provider may have accepted the request but Cloud lacks a result."""


class ProviderUnavailableError(Exception):
    """The provider definitively did not produce a result."""


class ProviderBilledError(ProviderUnavailableError):
    """A provider response was received, so its budget reservation is retained."""


@dataclass(frozen=True)
class GreetingRequest:
    job: str
    personality: str


class GreetingProvider(Protocol):
    def generate(self, request: GreetingRequest) -> str: ...
