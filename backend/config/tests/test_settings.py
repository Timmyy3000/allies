import os
import subprocess
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings import database_from_url


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
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


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


def test_production_settings_accept_complete_disabled_integrations():
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
            "assert abs(s.CACHES['health']['OPTIONS']['socket_timeout'] - 0.625) < 0.000001"
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
            "assert s.MIDDLEWARE[:2] == ['config.middleware.TrustedProxyHeadersMiddleware', "
            "'django.middleware.security.SecurityMiddleware']"
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
