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
print(settings.PROFILE_PROVISIONING_PROVIDER)
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
        "ALLIES_CLOUD_SERVICE_TOKEN",
        "ALLIES_CLOUD_EVENT_DELIVERY_ENABLED",
        "ALLIES_CLOUD_URL",
        "ALLIES_CLOUD_EVENT_SERVICE_TOKEN",
        "ALLIES_FLY_API_BASE_URL",
        "ALLIES_RUNTIME_IDLE_STOP_ENABLED",
        "ALLIES_RUNTIME_POWER_PROOF_ENABLED",
        "ALLIES_RUNTIME_KEEP_WARM_SECONDS",
        "ALLIES_RUNTIME_INTENT_TTL_SECONDS",
        "ALLIES_RUNTIME_INTENT_RETENTION_SECONDS",
        "ALLIES_RUNTIME_SPECULATIVE_START_COOLDOWN_SECONDS",
        "ALLIES_RUNTIME_READINESS_FRESHNESS_SECONDS",
        "PROFILE_PROVISIONING_PROVIDER",
        "PROFILE_PROVISIONING_MODEL",
        "PROFILE_PROVISIONING_BASE_URL",
        "PROFILE_PROVISIONING_CREDENTIAL_NAME",
        "PROFILE_PROVISIONING_CREDENTIAL_REF",
    ):
        environment.pop(name, None)
    environment["ALLIES_CLOUD_SERVICE_TOKEN"] = "s" * 32
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


def test_profile_provisioning_defaults_to_hermes_openai_api_provider():
    result = run_settings_probe(DJANGO_DEBUG="true")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "openai-api"


def test_readiness_freshness_must_exceed_twice_the_runtime_heartbeat():
    invalid = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_RUNTIME_READINESS_FRESHNESS_SECONDS="30",
    )
    valid = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_RUNTIME_READINESS_FRESHNESS_SECONDS="31",
    )

    assert invalid.returncode != 0
    assert "must be greater than twice" in invalid.stderr
    assert valid.returncode == 0, valid.stderr


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


def test_production_mode_requires_strong_cloud_service_token():
    common = {
        "DJANGO_DEBUG": "false",
        "DJANGO_SECRET_KEY": "synthetic-test-secret",
        "DJANGO_ALLOWED_HOSTS": "localhost",
        "DATABASE_URL": "sqlite:///test-production.sqlite3",
    }

    missing = run_settings_probe(**common, ALLIES_CLOUD_SERVICE_TOKEN="")
    weak = run_settings_probe(**common, ALLIES_CLOUD_SERVICE_TOKEN="short")

    assert "ALLIES_CLOUD_SERVICE_TOKEN is required" in missing.stderr
    assert "ALLIES_CLOUD_SERVICE_TOKEN must be a strong token" in weak.stderr


@pytest.mark.parametrize(
    "cloud_url",
    [
        "http://cloud.example.test",
        "https://user:password@cloud.example.test",
        "https://cloud.example.test/events?token=secret",
    ],
)
def test_event_delivery_requires_credential_free_https_cloud_url(cloud_url):
    result = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_CLOUD_EVENT_DELIVERY_ENABLED="true",
        ALLIES_CLOUD_URL=cloud_url,
        ALLIES_CLOUD_EVENT_SERVICE_TOKEN="c" * 32,
    )

    assert result.returncode != 0
    assert "ALLIES_CLOUD_URL must be an HTTPS origin" in result.stderr


def test_debug_power_proof_allows_only_the_compose_cloud_http_host():
    common = {
        "DJANGO_DEBUG": "true",
        "ALLIES_RUNTIME_POWER_PROOF_ENABLED": "true",
        "ALLIES_CLOUD_EVENT_DELIVERY_ENABLED": "true",
        "ALLIES_CLOUD_EVENT_SERVICE_TOKEN": "c" * 32,
    }
    allowed = run_settings_probe(
        **common,
        ALLIES_CLOUD_URL="http://host.docker.internal:8000",
    )
    rejected = run_settings_probe(
        **common,
        ALLIES_CLOUD_URL="http://cloud.example.test:8000",
    )

    assert allowed.returncode == 0, allowed.stderr
    assert rejected.returncode != 0
    assert "debug proof Cloud host" in rejected.stderr


def test_power_proof_origin_requires_debug_and_explicit_proof_gate():
    allowed = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_RUNTIME_POWER_PROOF_ENABLED="true",
        ALLIES_FLY_API_BASE_URL="http://fly-simulator:8080",
    )
    assert allowed.returncode == 0, allowed.stderr

    disabled = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_FLY_API_BASE_URL="http://simulator.test:8080",
    )
    assert disabled.returncode != 0
    assert "ALLIES_FLY_API_BASE_URL is only available" in disabled.stderr

    production = run_settings_probe(
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        DJANGO_ALLOWED_HOSTS="localhost",
        DATABASE_URL="sqlite:///test-production.sqlite3",
        ALLIES_RUNTIME_POWER_PROOF_ENABLED="true",
        ALLIES_FLY_API_BASE_URL="http://simulator.test:8080",
    )
    assert production.returncode != 0
    assert "ALLIES_FLY_API_BASE_URL is only available" in production.stderr


@pytest.mark.parametrize(
    "base_url",
    [
        "http://simulator.test/runtime",
        "http://simulator.test:8080?token=secret",
        "https://user:password@simulator.test",
    ],
)
def test_power_proof_origin_is_a_plain_origin(base_url):
    result = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_RUNTIME_POWER_PROOF_ENABLED="true",
        ALLIES_FLY_API_BASE_URL=base_url,
    )

    assert result.returncode != 0
    assert "ALLIES_FLY_API_BASE_URL must be a plain origin" in result.stderr


@pytest.mark.parametrize(
    "base_url", ["http://simulator.test:8080", "https://simulator.test:8080"]
)
def test_power_proof_rejects_remote_origin(base_url):
    result = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_RUNTIME_POWER_PROOF_ENABLED="true",
        ALLIES_FLY_API_BASE_URL=base_url,
    )

    assert result.returncode != 0
    assert "host must be loopback or fly-simulator" in result.stderr


def test_runtime_intent_retention_cannot_end_before_eligibility():
    result = run_settings_probe(
        DJANGO_DEBUG="true",
        ALLIES_RUNTIME_INTENT_TTL_SECONDS="120",
        ALLIES_RUNTIME_INTENT_RETENTION_SECONDS="60",
    )

    assert result.returncode != 0
    assert "ALLIES_RUNTIME_INTENT_RETENTION_SECONDS" in result.stderr


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("PROFILE_PROVISIONING_PROVIDER", ""),
        ("PROFILE_PROVISIONING_MODEL", ""),
        ("PROFILE_PROVISIONING_BASE_URL", ""),
        ("PROFILE_PROVISIONING_BASE_URL", "api.openai.com/v1"),
        ("PROFILE_PROVISIONING_CREDENTIAL_NAME", "api-server-key"),
        ("PROFILE_PROVISIONING_CREDENTIAL_REF", "/run/secrets/provider-key"),
    ],
)
def test_profile_provisioning_settings_fail_fast(setting, value):
    result = run_settings_probe(DJANGO_DEBUG="true", **{setting: value})

    assert result.returncode != 0
    assert setting in result.stderr


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
        (
            "postgres://user:pass@localhost:5432/foundry",
            "django.db.backends.postgresql",
        ),
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
