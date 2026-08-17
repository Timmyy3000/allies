"""Deterministic provider used by unit and contract tests."""

from __future__ import annotations

from .base import GreetingRequest, ProviderUnavailableError, ProviderUnknownError


class FakeGreetingProvider:
    def __init__(self, *, response: str | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests: list[GreetingRequest] = []

    def generate(self, request: GreetingRequest) -> str:
        self.requests.append(request)
        if self.error is not None:
            if isinstance(self.error, (ProviderUnknownError, ProviderUnavailableError)):
                raise self.error
            raise ProviderUnavailableError("fake provider failed") from self.error
        if self.response is not None:
            return self.response
        return f"Hi there, I’m ready to help with {request.job}."
