"""Narrow provider port and the closed v1 provider catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from auths.config import provider_enabled
from auths.exceptions import ProviderRejected, ProviderUnavailable


class ProviderKey(StrEnum):
    FAKE = "fake"
    GOOGLE = "google"


@dataclass(frozen=True)
class ProviderFlow:
    provider: ProviderKey
    state: str
    nonce: str
    redirect_uri: str
    pkce_verifier: str
    deadline_monotonic: float | None = None


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: str
    subject: str
    issuer: str = ""
    email: str = ""
    display_name: str = ""
    email_verified: bool = False
    email_verification_source: str = ""

    def __post_init__(self):
        if self.provider not in {key.value for key in ProviderKey}:
            raise ProviderRejected("unknown provider")
        if not self.subject or len(self.subject) > 255:
            raise ProviderRejected("provider subject is invalid")
        if self.email_verified and (
            self.provider != ProviderKey.GOOGLE.value
            or not self.email
            or self.email_verification_source not in {"google"}
        ):
            raise ProviderRejected("verified identity email evidence is incomplete")
        if not self.email_verified and self.email_verification_source:
            raise ProviderRejected("unverified identity provenance is invalid")


class OIDCProvider(Protocol):
    key: ProviderKey

    def authorization_url(self, flow: ProviderFlow) -> str: ...

    def verify_callback(self, code: str, flow: ProviderFlow) -> VerifiedIdentity: ...


def get_provider(provider: ProviderKey | str) -> OIDCProvider:
    try:
        key = ProviderKey(str(provider))
    except ValueError as exc:
        raise ProviderUnavailable("provider is not registered") from exc
    if not provider_enabled(key.value):
        raise ProviderUnavailable("provider is disabled")
    if key is ProviderKey.FAKE:
        from .fake import FakeProvider

        return FakeProvider()
    if key is ProviderKey.GOOGLE:
        from .google import GoogleProvider

        return GoogleProvider()
    # Exhaustive enum guard; ChatGPT intentionally has no placeholder adapter.
    raise ProviderUnavailable("provider is not registered")
