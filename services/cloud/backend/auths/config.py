"""Configuration access kept in one small boundary for testability."""

from __future__ import annotations

import os

from django.conf import settings


def setting(name: str, default=None):
    return getattr(settings, name, default)


def jwt_key() -> bytes:
    configured = setting("ALLIES_AUTH_JWT_KEY", "") or os.environ.get(
        "ALLIES_AUTH_JWT_KEY", ""
    )
    if configured:
        return configured.encode()
    # Local-only fallback is deliberately independent from Django SECRET_KEY.
    # Production settings reject missing dedicated keys before startup.
    if setting("DEBUG", True):
        return b"allies-local-auth-jwt-key-not-for-production"
    return b""


def digest_key() -> bytes:
    configured = setting("ALLIES_AUTH_DIGEST_KEY", "") or os.environ.get(
        "ALLIES_AUTH_DIGEST_KEY", ""
    )
    if configured:
        return configured.encode()
    if setting("DEBUG", True):
        return b"allies-local-auth-digest-key-not-for-production"
    return b""


def access_ttl_seconds() -> int:
    return int(setting("ALLIES_AUTH_ACCESS_TTL_SECONDS", 600))


def flow_ttl_seconds() -> int:
    return int(setting("ALLIES_AUTH_FLOW_TTL_SECONDS", 600))


def native_enabled() -> bool:
    return bool(setting("ALLIES_AUTH_NATIVE_ENABLED", False))


def native_transaction_ttl_seconds() -> int:
    return int(setting("ALLIES_AUTH_NATIVE_TRANSACTION_TTL_SECONDS", 600))


def native_exchange_ttl_seconds() -> int:
    return int(setting("ALLIES_AUTH_NATIVE_EXCHANGE_TTL_SECONDS", 60))


def native_provider_timeout_seconds() -> int:
    return int(setting("ALLIES_AUTH_NATIVE_PROVIDER_TIMEOUT_SECONDS", 15))


def native_claim_lease_seconds() -> int:
    return int(setting("ALLIES_AUTH_NATIVE_CLAIM_LEASE_SECONDS", 30))


def native_terminal_retention_seconds() -> int:
    return int(setting("ALLIES_AUTH_NATIVE_TERMINAL_RETENTION_SECONDS", 24 * 60 * 60))


def native_app_redirect_uris() -> tuple[str, ...]:
    configured = setting("ALLIES_AUTH_NATIVE_REDIRECT_URIS", [])
    if isinstance(configured, str):
        configured = configured.split(",")
    return tuple(value.strip() for value in (configured or ()) if value.strip())


def native_google_redirect_uri() -> str:
    return str(setting("ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI", ""))


def native_rate_limit(operation: str) -> int:
    defaults = {
        "sign_in": 10,
        "callback": 10,
        "exchange": 10,
        "refresh": 20,
        "logout": 30,
        "onboarding": 5,
    }
    if operation not in defaults:
        raise ValueError("unknown native rate-limit operation")
    return int(
        setting(
            f"ALLIES_AUTH_NATIVE_{operation.upper()}_LIMIT",
            defaults[operation],
        )
    )


def native_rate_limit_period_seconds() -> int:
    return int(setting("ALLIES_AUTH_NATIVE_RATE_LIMIT_PERIOD_SECONDS", 60))


def native_global_rate_limit() -> int:
    return int(setting("ALLIES_AUTH_NATIVE_GLOBAL_LIMIT", 1000))


def refresh_idle_seconds() -> int:
    return int(setting("ALLIES_AUTH_REFRESH_IDLE_SECONDS", 14 * 24 * 60 * 60))


def refresh_absolute_seconds() -> int:
    return int(setting("ALLIES_AUTH_REFRESH_ABSOLUTE_SECONDS", 30 * 24 * 60 * 60))


def jwt_issuer() -> str:
    return str(setting("ALLIES_AUTH_JWT_ISSUER", "allies-cloud"))


def jwt_audience() -> str:
    return str(setting("ALLIES_AUTH_JWT_AUDIENCE", "allies-interface"))


def cookie_name(kind: str) -> str:
    return str(setting(f"ALLIES_AUTH_{kind.upper()}_COOKIE", f"allies_{kind}"))


def cookie_path(kind: str) -> str:
    return str(setting(f"ALLIES_AUTH_{kind.upper()}_COOKIE_PATH", "/api/"))


def cookie_secure() -> bool:
    return bool(setting("ALLIES_AUTH_COOKIE_SECURE", not setting("DEBUG", True)))


def cookie_samesite() -> str:
    return str(setting("ALLIES_AUTH_COOKIE_SAMESITE", "Lax"))


def provider_enabled(provider: str) -> bool:
    if provider == "fake":
        return bool(setting("ALLIES_AUTH_FAKE_PROVIDER_ENABLED", False))
    if provider == "google":
        return bool(setting("ALLIES_AUTH_GOOGLE_ENABLED", False))
    return False


def beta_invites_required() -> bool:
    return bool(setting("ALLIES_BETA_INVITES_REQUIRED", True))


def signup_email_allowlisted(email: str) -> bool:
    email = email.strip().lower()
    domain = "@" + email.rpartition("@")[2]
    allowed = {
        item.strip().lower() for item in setting("ALLIES_SIGNUP_ALLOWED_EMAILS", [])
    }
    return bool(email) and (email in allowed or domain in allowed)


def invite_claim_limit() -> int:
    return int(setting("ALLIES_AUTH_INVITE_CLAIM_LIMIT", 10))


def invite_claim_global_limit() -> int:
    return int(setting("ALLIES_AUTH_INVITE_CLAIM_GLOBAL_LIMIT", 600))


def invite_claim_rate_limit_period_seconds() -> int:
    return int(setting("ALLIES_AUTH_INVITE_CLAIM_RATE_LIMIT_PERIOD_SECONDS", 60))


def avatar_max_bytes() -> int:
    return int(setting("ALLIES_AVATAR_MAX_BYTES", 5 * 1024 * 1024))


def avatar_max_dimension() -> int:
    return int(setting("ALLIES_AVATAR_MAX_DIMENSION", 4096))


def avatar_max_pixels() -> int:
    return int(setting("ALLIES_AVATAR_MAX_PIXELS", 16_777_216))


def avatar_url_ttl_seconds() -> int:
    return int(setting("ALLIES_AVATAR_URL_TTL_SECONDS", 300))


def avatar_pending_ttl_seconds() -> int:
    return int(setting("ALLIES_AVATAR_PENDING_TTL_SECONDS", 24 * 60 * 60))
