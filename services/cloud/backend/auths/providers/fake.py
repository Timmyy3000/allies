"""Deterministic test provider.

The fake accepts only an explicit fixture code.  It deliberately does not
infer identity from email, and is disabled by default in every environment.
"""

from __future__ import annotations

from urllib.parse import urlencode

from auths.exceptions import ProviderRejected

from .base import OIDCProvider, ProviderFlow, ProviderKey, VerifiedIdentity


class FakeProvider(OIDCProvider):
    key = ProviderKey.FAKE

    def authorization_url(self, flow: ProviderFlow) -> str:
        return "/__fake__/authorize?" + urlencode(
            {
                "state": flow.state,
                "nonce": flow.nonce,
                "redirect_uri": flow.redirect_uri,
                "code_challenge": flow.pkce_verifier,
            }
        )

    def verify_callback(self, code: str, flow: ProviderFlow) -> VerifiedIdentity:
        # Fixture forms accepted by tests: ``subject`` or
        # ``subject|display name|email``.  Prefixing with ``fake:`` makes it
        # impossible to accidentally pass a real provider code here.
        if not isinstance(code, str) or not code.startswith("fake:"):
            raise ProviderRejected("fake callback code is malformed")
        pieces = code[5:].split("|", 2)
        subject = pieces[0].strip()
        if not subject or len(subject) > 255:
            raise ProviderRejected("fake subject is malformed")
        display_name = pieces[1].strip()[:80] if len(pieces) > 1 else ""
        email = pieces[2].strip()[:254] if len(pieces) > 2 else ""
        return VerifiedIdentity(
            provider=self.key.value,
            subject=subject,
            issuer="fake://issuer",
            email=email,
            display_name=display_name,
        )
