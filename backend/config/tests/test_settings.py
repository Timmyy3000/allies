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
    }


def test_database_from_url_rejects_non_postgresql_scheme():
    with pytest.raises(ImproperlyConfigured, match="must use postgres"):
        database_from_url("sqlite:///tmp/db.sqlite3")


def _settings_subprocess(overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "ALLIES_"))
        and key not in {"CACHE_URL", "DATABASE_URL"}
    }
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
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
