import os
import subprocess
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings import database_from_url


def test_observability_logging_preserves_existing_audit_loggers():
    from config import settings

    assert settings.LOGGING["disable_existing_loggers"] is False
    for logger_name in ("allies.auth", "allies.waitlist"):
        configured = settings.LOGGING["loggers"][logger_name]
        assert configured["handlers"] == ["allies_console"]
        assert configured["level"] == "INFO"
        assert configured["propagate"] is False
    assert settings.LOGGING["formatters"]["allies"] == {
        "()": "observability.events.AuditEventFormatter"
    }


def test_database_from_url_builds_postgresql_configuration():
    configured = database_from_url(
        "postgresql://allies%20user:secret%2Fvalue@database.internal:5433/allies%20cloud"
    )

    assert configured == {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "allies cloud",
        "USER": "allies user",
        "PASSWORD": "secret/value",
        "HOST": "database.internal",
        "PORT": 5433,
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }


def test_database_from_url_rejects_non_postgresql_scheme():
    with pytest.raises(ImproperlyConfigured, match="must use postgres"):
        database_from_url("sqlite:///tmp/db.sqlite3")


def _settings_subprocess(
    overrides: dict[str, str], code: str = "import config.settings"
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "ALLIES_"))
        and key not in {"CACHE_URL", "DATABASE_URL"}
    }
    if overrides.get("DJANGO_DEBUG") == "false":
        env.update(
            {
                "ALLIES_FOUNDRY_URL": "https://foundry.example.test",
                "ALLIES_FOUNDRY_SERVICE_TOKEN": "f" * 32,
                "ALLIES_WAITLIST_PROVIDER_ENABLED": "true",
                "ALLIES_WAITLIST_PROVIDER": "openai",
                "ALLIES_WAITLIST_OPENAI_API_KEY": "provider-key",
                "ALLIES_WAITLIST_OPENAI_MODEL": "approved-model",
            }
        )
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_activity_sse_is_enabled_by_default():
    result = _settings_subprocess(
        {},
        "import config.settings as s; print(s.ALLIES_ACTIVITY_SSE_ENABLED)",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "True"


def test_production_settings_reject_missing_security_configuration():
    result = _settings_subprocess(
        {"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "x" * 32}
    )

    assert result.returncode != 0
    assert "Unsafe AUTH-001 production configuration" in result.stderr
    assert "ALLIES_TRUSTED_ORIGINS" in result.stderr
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr
    assert "CACHE_URL" in result.stderr
    assert "PostgreSQL DATABASE_URL" in result.stderr


def test_production_settings_require_foundry_service_configuration():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "ALLIES_FOUNDRY_URL": "",
            "ALLIES_FOUNDRY_SERVICE_TOKEN": "",
        }
    )

    assert result.returncode != 0
    assert "HTTPS ALLIES_FOUNDRY_URL" in result.stderr
    assert "ALLIES_FOUNDRY_SERVICE_TOKEN" in result.stderr


def test_production_settings_require_official_greeting_provider():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "ALLIES_WAITLIST_PROVIDER_ENABLED": "false",
            "ALLIES_WAITLIST_PROVIDER": "fake",
            "ALLIES_WAITLIST_OPENAI_API_KEY": "",
            "ALLIES_WAITLIST_OPENAI_MODEL": "",
            "ALLIES_WAITLIST_OPENAI_URL": "http://api.openai.com/v1/responses",
        }
    )

    assert result.returncode != 0
    assert "ALLIES_WAITLIST_PROVIDER_ENABLED=true for onboarding" in result.stderr
    assert "ALLIES_WAITLIST_PROVIDER=openai" in result.stderr
    assert (
        "ALLIES_WAITLIST_OPENAI_URL=https://api.openai.com/v1/responses"
        in result.stderr
    )
    assert "ALLIES_WAITLIST_OPENAI_API_KEY" in result.stderr
    assert "ALLIES_WAITLIST_OPENAI_MODEL" in result.stderr


def test_production_settings_accept_complete_disabled_integrations():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_FOUNDRY_URL": "https://foundry.example.test",
            "ALLIES_FOUNDRY_SERVICE_TOKEN": "f" * 32,
            "ALLIES_WAITLIST_PROVIDER_ENABLED": "true",
            "ALLIES_WAITLIST_PROVIDER": "openai",
            "ALLIES_WAITLIST_OPENAI_API_KEY": "provider-key",
            "ALLIES_WAITLIST_OPENAI_MODEL": "approved-model",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode == 0, result.stderr


def test_native_auth_is_disabled_by_default():
    result = _settings_subprocess(
        {"DJANGO_DEBUG": "true"},
        "import config.settings as s; assert s.ALLIES_AUTH_NATIVE_ENABLED is False",
    )

    assert result.returncode == 0, result.stderr


def test_production_settings_reject_native_auth_without_explicit_edge_and_redirects():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_AUTH_NATIVE_ENABLED": "true",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode != 0
    assert "ALLIES_RAILWAY_PROXY_MODE for native auth" in result.stderr
    assert (
        "complete native Google callback and app return configuration" in result.stderr
    )


def test_production_settings_reject_nonpositive_native_onboarding_limit():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "ALLIES_AUTH_NATIVE_ENABLED": "true",
            "ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT": "0",
        }
    )

    assert result.returncode != 0
    assert "positive native auth lifetimes and rate limits" in result.stderr


def test_production_settings_accept_native_auth_with_placeholder_contract_values():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_RAILWAY_PROXY_MODE": "true",
            "ALLIES_AUTH_NATIVE_ENABLED": "true",
            "ALLIES_AUTH_GOOGLE_ENABLED": "true",
            "ALLIES_AUTH_GOOGLE_CLIENT_ID": "native-client-id",
            "ALLIES_AUTH_GOOGLE_CLIENT_SECRET": "native-client-secret",
            "ALLIES_AUTH_GOOGLE_REDIRECT_URI": (
                "https://cloud.example.test/api/v1/auths/callback/google"
            ),
            "ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI": (
                "https://cloud.example.test/api/v1/auths/native/callback/google"
            ),
            "ALLIES_AUTH_NATIVE_REDIRECT_URIS": (
                "https://app.example.test/auth/callback"
            ),
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode == 0, result.stderr


def test_native_onboarding_limit_defaults_to_five():
    result = _settings_subprocess(
        {"DJANGO_DEBUG": "true"},
        "import config.settings as s; assert s.ALLIES_AUTH_NATIVE_ONBOARDING_LIMIT == 5",
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("provider_timeout", ["30", "31"])
def test_production_settings_reject_native_provider_timeout_at_or_above_claim_lease(
    provider_timeout,
):
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_RAILWAY_PROXY_MODE": "true",
            "ALLIES_AUTH_NATIVE_ENABLED": "true",
            "ALLIES_AUTH_GOOGLE_ENABLED": "true",
            "ALLIES_AUTH_GOOGLE_CLIENT_ID": "native-client-id",
            "ALLIES_AUTH_GOOGLE_CLIENT_SECRET": "native-client-secret",
            "ALLIES_AUTH_GOOGLE_REDIRECT_URI": (
                "https://cloud.example.test/api/v1/auths/callback/google"
            ),
            "ALLIES_AUTH_GOOGLE_NATIVE_REDIRECT_URI": (
                "https://cloud.example.test/api/v1/auths/native/callback/google"
            ),
            "ALLIES_AUTH_NATIVE_REDIRECT_URIS": (
                "https://app.example.test/auth/callback"
            ),
            "ALLIES_AUTH_NATIVE_PROVIDER_TIMEOUT_SECONDS": provider_timeout,
            "ALLIES_AUTH_NATIVE_CLAIM_LEASE_SECONDS": "30",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode != 0
    assert (
        "native provider timeout must be less than native claim lease" in result.stderr
    )


def test_trusted_origin_wildcards_become_cors_regexes():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "true",
            "ALLIES_TRUSTED_ORIGINS": (
                "https://*.up.railway.app,http://localhost:3000"
            ),
        },
        (
            "import config.settings as s; "
            "assert s.CORS_ALLOWED_ORIGINS == ['http://localhost:3000']; "
            "assert len(s.CORS_ALLOWED_ORIGIN_REGEXES) == 1; "
            "assert __import__('re').match(s.CORS_ALLOWED_ORIGIN_REGEXES[0], "
            "'https://preview.up.railway.app')"
        ),
    )

    assert result.returncode == 0, result.stderr


def test_cors_allows_idempotent_browser_mutations():
    result = _settings_subprocess(
        {"DJANGO_DEBUG": "true"},
        (
            "import config.settings as s; "
            "assert 'idempotency-key' in s.CORS_ALLOW_HEADERS"
        ),
    )

    assert result.returncode == 0, result.stderr


def test_fractional_health_timeout_is_valid_and_separate_from_db_connect_timeout():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_HEALTH_OPERATION_TIMEOUT_SECONDS": "2.5",
            "DATABASE_CONNECT_TIMEOUT_SECONDS": "7",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        },
        (
            "import config.settings as s; "
            "assert s.ALLIES_HEALTH_OPERATION_TIMEOUT_SECONDS == 2.5; "
            "assert s.DATABASES['default']['OPTIONS']['connect_timeout'] == 7; "
            "assert s.DATABASES['health']['OPTIONS']['connect_timeout'] == 2; "
            "assert s.DATABASES['health']['CONN_MAX_AGE'] == 0; "
            "assert abs(s.CACHES['health']['OPTIONS']['socket_timeout'] - 0.625) < 0.000001; "
            "assert s.CACHES['health']['OPTIONS'].get('decode_responses', False) is False"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "ValueError" not in result.stderr


@pytest.mark.parametrize("operation_timeout", ["5", "6"])
def test_health_operation_timeout_must_fit_inside_total_budget(operation_timeout):
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_HEALTH_OPERATION_TIMEOUT_SECONDS": operation_timeout,
            "ALLIES_HEALTH_TOTAL_TIMEOUT_SECONDS": "5",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode != 0
    assert "must be less than" in result.stderr


def test_production_settings_enable_whitenoise_static_files():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode == 0, result.stderr
    static_result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import config.settings as s; "
                "assert 'whitenoise.middleware.WhiteNoiseMiddleware' in s.MIDDLEWARE; "
                "assert s.STORAGES['staticfiles']['BACKEND'].endswith("
                "'CompressedManifestStaticFilesStorage')"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("DJANGO_", "ALLIES_"))
                and key not in {"CACHE_URL", "DATABASE_URL"}
            },
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_FOUNDRY_URL": "https://foundry.example.test",
            "ALLIES_FOUNDRY_SERVICE_TOKEN": "f" * 32,
            "ALLIES_WAITLIST_PROVIDER_ENABLED": "true",
            "ALLIES_WAITLIST_PROVIDER": "openai",
            "ALLIES_WAITLIST_OPENAI_API_KEY": "provider-key",
            "ALLIES_WAITLIST_OPENAI_MODEL": "approved-model",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        },
    )
    assert static_result.returncode == 0, static_result.stderr


def test_celery_settings_keep_cleanup_on_the_cloud_queue():
    from config import settings

    assert settings.CELERY_ACCEPT_CONTENT == ["json"]
    assert settings.CELERY_TASK_DEFAULT_QUEUE == "cloud"
    assert settings.CELERY_BROKER_URL.endswith("/1")
    assert settings.CELERY_WORKER_PREFETCH_MULTIPLIER == 1
    assert settings.CELERY_WORKER_MAX_TASKS_PER_CHILD == 50
    assert settings.CELERY_BEAT_SCHEDULE["cleanup-auth-artifacts"] == {
        "task": "auths.cleanup_auth_artifacts",
        "schedule": 900.0,
        "options": {"queue": "cloud"},
    }
    assert settings.CELERY_BEAT_SCHEDULE["cleanup-expired-onboarding-attempts"] == {
        "task": "allies.cleanup_expired_onboarding_attempts",
        "schedule": 900.0,
        "options": {"queue": "cloud"},
    }
    assert "cleanup-waitlist-entries" not in settings.CELERY_BEAT_SCHEDULE


def test_cache_and_celery_broker_use_separate_redis_databases():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        },
        (
            "import config.settings as s; "
            "assert s.CELERY_BROKER_URL == 'redis://cache.internal:6379/1'"
        ),
    )

    assert result.returncode == 0, result.stderr


def test_only_health_path_is_exempt_from_https_redirect():
    from config import settings

    assert settings.SECURE_REDIRECT_EXEMPT == []


def test_debug_settings_use_http_compatible_same_site_cookies():
    result = _settings_subprocess(
        {"DJANGO_DEBUG": "true"},
        (
            "import config.settings as s; "
            "assert s.SESSION_COOKIE_SECURE is False; "
            "assert s.CSRF_COOKIE_SECURE is False; "
            "assert s.ALLIES_AUTH_COOKIE_SECURE is False; "
            "assert s.SESSION_COOKIE_SAMESITE == 'Lax'; "
            "assert s.CSRF_COOKIE_SAMESITE == 'Lax'; "
            "assert s.ALLIES_AUTH_COOKIE_SAMESITE == 'Lax'"
        ),
    )

    assert result.returncode == 0, result.stderr


def test_railway_mode_lets_the_managed_edge_enforce_https():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_RAILWAY_PROXY_MODE": "true",
            "ALLIES_TRUST_FORWARDED_PROTO": "false",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        },
        (
            "import config.settings as s; "
            "assert s.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https'); "
            "assert s.SECURE_SSL_REDIRECT is True; "
            "assert s.SECURE_REDIRECT_EXEMPT == [r'^/?api/v1/health$']; "
            "assert s.SESSION_COOKIE_SAMESITE == 'None'; "
            "assert s.CSRF_COOKIE_SAMESITE == 'None'; "
            "assert s.ALLIES_AUTH_COOKIE_SAMESITE == 'None'; "
            "assert s.MIDDLEWARE[:2] == ['config.middleware.TrustedProxyHeadersMiddleware', "
            "'observability.middleware.WideEventMiddleware']"
        ),
    )

    assert result.returncode == 0, result.stderr


def test_production_settings_accept_railway_proxy_mode_without_static_ip_list():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_RAILWAY_PROXY_MODE": "true",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode == 0, result.stderr


def test_production_settings_reject_fake_provider():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "false",
            "DJANGO_SECRET_KEY": "d" * 32,
            "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
            "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
            "ALLIES_AUTH_JWT_KEY": "j" * 32,
            "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
            "ALLIES_AUTH_FAKE_PROVIDER_ENABLED": "true",
            "CACHE_URL": "redis://cache.internal:6379/0",
            "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        }
    )

    assert result.returncode != 0
    assert "ALLIES_AUTH_FAKE_PROVIDER_ENABLED must be false" in result.stderr


def _waitlist_production_settings() -> dict[str, str]:
    return {
        "DJANGO_DEBUG": "false",
        "DJANGO_SECRET_KEY": "d" * 32,
        "DJANGO_ALLOWED_HOSTS": "cloud.example.test",
        "ALLIES_TRUSTED_ORIGINS": "https://app.example.test",
        "ALLIES_AUTH_JWT_KEY": "j" * 32,
        "ALLIES_AUTH_DIGEST_KEY": "h" * 32,
        "CACHE_URL": "redis://cache.internal:6379/0",
        "DATABASE_URL": "postgresql://allies:secret@database.internal/allies",
        "ALLIES_WAITLIST_ENABLED": "true",
        "ALLIES_WAITLIST_TOKEN_KEY": "w" * 32,
        "ALLIES_WAITLIST_CONSENT_VERSION": "consent-v1",
        "ALLIES_WAITLIST_JOINED_RETENTION_SECONDS": "2592000",
        "ALLIES_WAITLIST_PROVIDER_ENABLED": "true",
        "ALLIES_WAITLIST_PROVIDER": "openai",
        "ALLIES_WAITLIST_OPENAI_API_KEY": "provider-key",
        "ALLIES_WAITLIST_OPENAI_MODEL": "approved-model",
    }


def test_production_settings_accept_complete_waitlist_configuration():
    result = _settings_subprocess(
        _waitlist_production_settings(),
        (
            "import config.settings as s; "
            "assert s.ALLIES_WAITLIST_GENERATION_ATTEMPT_BUDGET_PER_MINUTE == 5; "
            "assert s.CELERY_BEAT_SCHEDULE['cleanup-waitlist-entries']['task'] "
            "== 'waitlist.cleanup_waitlist_entries'"
        ),
    )

    assert result.returncode == 0, result.stderr


def test_debug_waitlist_requires_explicit_token_key():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "true",
            "DJANGO_SECRET_KEY": "d" * 32,
            "ALLIES_WAITLIST_ENABLED": "true",
            "ALLIES_WAITLIST_TOKEN_KEY": "",
        }
    )

    assert result.returncode != 0
    assert "ALLIES_WAITLIST_TOKEN_KEY" in result.stderr


def test_debug_waitlist_requires_distributed_cache_url():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "true",
            "DJANGO_SECRET_KEY": "d" * 32,
            "ALLIES_WAITLIST_ENABLED": "true",
            "ALLIES_WAITLIST_TOKEN_KEY": "w" * 32,
        }
    )

    assert result.returncode != 0
    assert "CACHE_URL" in result.stderr


def test_debug_waitlist_rejects_unsafe_openai_provider_url():
    result = _settings_subprocess(
        {
            "DJANGO_DEBUG": "true",
            "DJANGO_SECRET_KEY": "d" * 32,
            "ALLIES_WAITLIST_ENABLED": "true",
            "ALLIES_WAITLIST_TOKEN_KEY": "w" * 32,
            "ALLIES_WAITLIST_PROVIDER_ENABLED": "true",
            "ALLIES_WAITLIST_PROVIDER": "openai",
            "ALLIES_WAITLIST_OPENAI_API_KEY": "provider-key",
            "ALLIES_WAITLIST_OPENAI_MODEL": "approved-model",
            "ALLIES_WAITLIST_OPENAI_URL": "http://attacker.example/responses",
        }
    )

    assert result.returncode != 0
    assert (
        "ALLIES_WAITLIST_OPENAI_URL=https://api.openai.com/v1/responses"
        in result.stderr
    )


def test_production_settings_reject_unsafe_waitlist_configuration():
    configured = _waitlist_production_settings()
    configured.update(
        {
            "ALLIES_WAITLIST_TOKEN_KEY": "short",
            "ALLIES_WAITLIST_PROVIDER": "fake",
            "ALLIES_WAITLIST_OPENAI_API_KEY": "",
            "ALLIES_WAITLIST_OPENAI_MODEL": "",
            "ALLIES_WAITLIST_OPENAI_URL": "http://api.openai.com/v1/responses",
        }
    )
    result = _settings_subprocess(configured)

    assert result.returncode != 0
    assert "Unsafe CLD-008 production configuration" in result.stderr
    assert "ALLIES_WAITLIST_TOKEN_KEY" in result.stderr
