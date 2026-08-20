import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROBE = """
import config.settings as settings
print(settings.DEBUG)
print(settings.SECRET_KEY == "django-insecure-local-development-only")
print(settings.DATABASES["default"]["ENGINE"])
print(settings.DATABASES["default"].get("OPTIONS"))
print(settings.STATIC_ROOT)
print(settings.SECURE_PROXY_SSL_HEADER)
print(settings.SECURE_SSL_REDIRECT)
print(settings.SECURE_HSTS_SECONDS)
"""


def run_settings_probe(**overrides):
    environment = os.environ.copy()
    for name in (
        "DATABASE_URL",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_DEBUG",
        "DJANGO_SECRET_KEY",
        "DJANGO_TRUST_PROXY_HEADERS",
        "DJANGO_TRUSTED_PROXY_IPS",
    ):
        environment.pop(name, None)
    environment.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_development_mode_keeps_sqlite_fallback():
    result = run_settings_probe(DJANGO_DEBUG="true")

    assert result.returncode == 0, result.stderr
    assert "True" in result.stdout
    assert "False" in result.stdout
    assert "django.db.backends.sqlite3" in result.stdout


def test_production_mode_requires_secret_key():
    result = run_settings_probe(DJANGO_DEBUG="false")

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY is required" in result.stderr


def test_debug_mode_requires_secret_when_database_is_configured():
    result = run_settings_probe(
        DJANGO_DEBUG="true",
        DATABASE_URL="sqlite:///test-development.sqlite3",
    )

    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY is required" in result.stderr


def test_production_mode_requires_database_url():
    result = run_settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        DJANGO_ALLOWED_HOSTS="localhost",
    )

    assert result.returncode != 0
    assert "DATABASE_URL is required" in result.stderr


def test_proxy_header_trust_requires_explicit_proxy_networks():
    result = run_settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        DJANGO_ALLOWED_HOSTS="localhost",
        DATABASE_URL="sqlite:///test-production.sqlite3",
        DJANGO_TRUST_PROXY_HEADERS="true",
    )

    assert result.returncode != 0
    assert "DJANGO_TRUSTED_PROXY_IPS is required" in result.stderr


@pytest.mark.parametrize(
    ("trusted_proxy_ips", "error_message"),
    [
        ("100.64.0.5/10", "invalid IP network"),
        ("0.0.0.0/0", "must not contain a catch-all network"),
        ("::/0", "must not contain a catch-all network"),
    ],
)
def test_proxy_header_trust_rejects_unsafe_networks(trusted_proxy_ips, error_message):
    result = run_settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        DJANGO_ALLOWED_HOSTS="localhost",
        DATABASE_URL="sqlite:///test-production.sqlite3",
        DJANGO_TRUST_PROXY_HEADERS="true",
        DJANGO_TRUSTED_PROXY_IPS=trusted_proxy_ips,
    )

    assert result.returncode != 0
    assert error_message in result.stderr


def test_proxy_networks_are_ignored_when_proxy_trust_is_disabled():
    result = run_settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        DJANGO_ALLOWED_HOSTS="localhost",
        DATABASE_URL="sqlite:///test-production.sqlite3",
        DJANGO_TRUSTED_PROXY_IPS="not-an-ip-network",
    )

    assert result.returncode == 0, result.stderr
    assert "None" in result.stdout


def test_production_mode_requires_allowed_host():
    result = run_settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        DATABASE_URL="sqlite:///test-production.sqlite3",
    )

    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS is required" in result.stderr


@pytest.mark.parametrize(
    ("database_url", "engine"),
    [
        ("sqlite:///test-production.sqlite3", "django.db.backends.sqlite3"),
        ("postgres://user:pass@localhost:5432/foundry", "django.db.backends.postgresql"),
    ],
)
def test_production_mode_accepts_explicit_database(database_url, engine):
    result = run_settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        DJANGO_ALLOWED_HOSTS="localhost",
        DATABASE_URL=database_url,
        DJANGO_TRUST_PROXY_HEADERS="true",
        DJANGO_TRUSTED_PROXY_IPS="127.0.0.1/32",
    )

    assert result.returncode == 0, result.stderr
    assert "False" in result.stdout
    assert engine in result.stdout
    assert "('HTTP_X_FORWARDED_PROTO', 'https')" in result.stdout
    if engine == "django.db.backends.postgresql":
        assert "'connect_timeout': 5" in result.stdout
        assert "statement_timeout" not in result.stdout
        assert "31536000" in result.stdout
    else:
        assert "'transaction_mode': 'IMMEDIATE'" in result.stdout
