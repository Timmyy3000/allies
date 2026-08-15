"""Google OpenID Connect adapter.

The adapter owns provider-specific network and claim handling.  Callers only
receive the normalized :class:`VerifiedIdentity` and never raw tokens/claims.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from auths.config import setting
from auths.exceptions import ProviderRejected

from .base import OIDCProvider, ProviderFlow, ProviderKey, VerifiedIdentity

GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleProvider(OIDCProvider):
    key = ProviderKey.GOOGLE
    discovery_url = "https://accounts.google.com/.well-known/openid-configuration"

    @staticmethod
    def _https_url(value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ProviderRejected("google endpoint must use https")
        return value

    def authorization_url(self, flow: ProviderFlow) -> str:
        client_id = str(setting("ALLIES_AUTH_GOOGLE_CLIENT_ID", ""))
        redirect_uri = str(
            setting("ALLIES_AUTH_GOOGLE_REDIRECT_URI", flow.redirect_uri)
        )
        if not client_id or not redirect_uri:
            raise ProviderRejected("google provider is incomplete")
        endpoint = self._https_url(
            str(
                setting(
                    "ALLIES_AUTH_GOOGLE_AUTHORIZATION_ENDPOINT",
                    "https://accounts.google.com/o/oauth2/v2/auth",
                )
            )
        )
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(flow.pkce_verifier.encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        return (
            endpoint
            + "?"
            + urlencode(
                {
                    "client_id": client_id,
                    "response_type": "code",
                    "scope": "openid profile email",
                    "redirect_uri": redirect_uri,
                    "state": flow.state,
                    "nonce": flow.nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    def _fetch_json(self, url: str, *, data: bytes | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(url, data=data, headers=headers)
        try:
            with urlopen(request, timeout=5) as response:
                body = response.read(1_000_001)
                if len(body) > 1_000_000:
                    raise ProviderRejected("google provider response too large")
                payload = json.loads(body)
        except (
            Exception
        ) as exc:  # provider outage and malformed JSON are same safe outcome
            raise ProviderRejected("google provider unavailable") from exc
        if not isinstance(payload, dict):
            raise ProviderRejected("google provider response malformed")
        return payload

    def _discovery(self) -> dict:
        configured = self._https_url(
            str(setting("ALLIES_AUTH_GOOGLE_DISCOVERY_URL", self.discovery_url))
        )
        payload = self._fetch_json(configured)
        if payload.get("issuer") not in GOOGLE_ISSUERS:
            raise ProviderRejected("google issuer mismatch")
        return payload

    def _decode_id_token(self, token: str, discovery: dict) -> dict:
        try:
            import jwt

            jwks_client = jwt.PyJWKClient(
                self._https_url(str(discovery["jwks_uri"])), timeout=5
            )
            signing_key = jwks_client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=str(setting("ALLIES_AUTH_GOOGLE_CLIENT_ID", "")),
                issuer=GOOGLE_ISSUERS,
                options={"require": ["iss", "aud", "sub", "exp", "iat"]},
                leeway=60,
            )
        except Exception as exc:
            raise ProviderRejected("google id token invalid") from exc

    def verify_callback(self, code: str, flow: ProviderFlow) -> VerifiedIdentity:
        if not isinstance(code, str) or not code or len(code) > 4096:
            raise ProviderRejected("authorization code malformed")
        discovery = self._discovery()
        token_endpoint = self._https_url(
            str(
                setting(
                    "ALLIES_AUTH_GOOGLE_TOKEN_ENDPOINT",
                    discovery.get("token_endpoint", ""),
                )
            )
        )
        client_id = str(setting("ALLIES_AUTH_GOOGLE_CLIENT_ID", ""))
        client_secret = str(setting("ALLIES_AUTH_GOOGLE_CLIENT_SECRET", ""))
        redirect_uri = str(
            setting("ALLIES_AUTH_GOOGLE_REDIRECT_URI", flow.redirect_uri)
        )
        if not token_endpoint or not client_id or not client_secret:
            raise ProviderRejected("google provider is incomplete")
        form = urlencode(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": flow.pkce_verifier,
            }
        ).encode()
        payload = self._fetch_json(token_endpoint, data=form)
        id_token = payload.get("id_token")
        if not isinstance(id_token, str):
            raise ProviderRejected("google callback has no id token")
        claims = self._decode_id_token(id_token, discovery)
        issuer = claims.get("iss")
        if issuer not in GOOGLE_ISSUERS:
            raise ProviderRejected("google issuer mismatch")
        audience = claims.get("aud")
        authorized_party = claims.get("azp")
        if isinstance(audience, str):
            audience_matches = audience == client_id
            multiple_audiences = False
        elif isinstance(audience, list) and all(
            isinstance(item, str) for item in audience
        ):
            audience_matches = client_id in audience
            multiple_audiences = len(audience) > 1
        else:
            audience_matches = False
            multiple_audiences = False
        if (
            not audience_matches
            or (multiple_audiences and authorized_party != client_id)
            or (authorized_party is not None and authorized_party != client_id)
        ):
            raise ProviderRejected("google audience mismatch")
        # ``nonce`` is compared before any provider snapshot is returned.
        if claims.get("nonce") != flow.nonce:
            raise ProviderRejected("google nonce mismatch")
        issued_at = claims.get("iat")
        if (
            not isinstance(issued_at, (int, float))
            or abs(time.time() - issued_at) > 600
        ):
            raise ProviderRejected("google issued-at outside skew")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise ProviderRejected("google subject malformed")
        email = claims.get("email", "")
        email_verified = claims.get("email_verified") is True and isinstance(email, str)
        if not email_verified:
            email = ""
        display_name = claims.get("name", "")
        if not isinstance(display_name, str):
            display_name = ""
        return VerifiedIdentity(
            provider=self.key.value,
            subject=subject.strip(),
            issuer=str(issuer),
            email=email[:254],
            display_name=display_name[:80],
            email_verified=email_verified,
            email_verification_source="google" if email_verified else "",
        )
