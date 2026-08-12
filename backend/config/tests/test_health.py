import logging
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from django.test import Client, override_settings

from config import health
from config.health import (
    HealthResult,
    _health_check_with_gate,
    _health_db_probe,
    _log_health_failure,
    _probe_cache,
    check_health,
)


@pytest.fixture(autouse=True)
def reset_health_gate(monkeypatch):
    monkeypatch.setattr("config.health._railway_health_gate_last_result", None)
    monkeypatch.setattr("config.health._railway_health_gate_last_at", 0.0)
    monkeypatch.setattr("config.health._railway_health_gate_in_flight", False)
    monkeypatch.setattr("config.health._health_failure_last_at", -60.0)


def test_health_check_scopes_postgres_statement_timeout_to_probe(monkeypatch):
    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            calls.append((query, params))

        def fetchone(self):
            return (1,)

    monkeypatch.setattr(
        "config.health.connection",
        SimpleNamespace(vendor="postgresql", cursor=lambda: Cursor()),
    )
    monkeypatch.setattr("config.health.connections", SimpleNamespace(databases={}))
    monkeypatch.setattr(
        "config.health.transaction.atomic", lambda using=None: nullcontext()
    )
    monkeypatch.setattr("config.health.cache.set", lambda *args, **kwargs: True)
    monkeypatch.setattr("config.health.cache.get", lambda key: "ok")
    monkeypatch.setattr("config.health.cache.delete", lambda key: True)

    result = check_health()

    assert result.healthy
    assert calls == [
        ("SELECT set_config('statement_timeout', %s, true)", ["2000"]),
        ("SELECT 1", None),
    ]


@pytest.mark.django_db
def test_health_endpoint_returns_standard_success_envelope():
    response = Client().get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Service healthy",
        "data": {"state": "healthy"},
    }


@pytest.mark.django_db
@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_REDIRECT_EXEMPT=[r"^/?api/v1/health$"],
)
def test_health_endpoint_is_not_redirected_by_production_https_policy():
    response = Client().get("/api/v1/health")

    assert response.status_code == 200


@pytest.mark.django_db
def test_health_endpoint_returns_generic_503_on_dependency_failure(monkeypatch):
    monkeypatch.setattr(
        "config.health.cache.get",
        lambda key: (_ for _ in ()).throw(ConnectionError("redis.internal")),
    )

    response = Client().get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "Service unavailable",
        "data": {"code": "service_unavailable"},
    }
    assert b"redis.internal" not in response.content


def test_health_endpoint_returns_429_when_rate_limited(monkeypatch):
    from auths.throttle import ThrottleExceeded

    monkeypatch.setattr(
        "config.health.check_rate_limit",
        lambda **kwargs: (_ for _ in ()).throw(ThrottleExceeded()),
    )

    response = Client().get("/api/v1/health")

    assert response.status_code == 429
    assert response.json() == {
        "status": "error",
        "message": "try again later",
        "data": {"code": "throttled"},
    }


def test_health_endpoint_hides_throttle_dependency_failure(monkeypatch):
    from auths.throttle import ThrottleUnavailable

    monkeypatch.setattr(
        "config.health.check_rate_limit",
        lambda **kwargs: (_ for _ in ()).throw(ThrottleUnavailable()),
    )

    response = Client().get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "Service unavailable",
        "data": {"code": "service_unavailable"},
    }


def test_health_throttle_time_is_inside_endpoint_budget(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("config.health.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "config.health.check_rate_limit",
        lambda **kwargs: clock.__setitem__(0, 6.0),
    )
    monkeypatch.setattr(
        "config.health.check_health",
        lambda **kwargs: pytest.fail("dependency probe should not start"),
    )

    response = Client().get("/api/v1/health")

    assert response.status_code == 503


def test_health_rate_limit_uses_application_cache_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "config.health.check_rate_limit",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        "config.health._health_check_with_gate",
        lambda **kwargs: HealthResult(healthy=True, elapsed_seconds=0.0),
    )

    response = Client().get("/api/v1/health")

    assert response.status_code == 200
    assert calls[0]["cache_backend"] is health.cache


def test_health_probe_does_not_follow_database_test_mirror(monkeypatch):
    class FakeDatabase:
        vendor = "postgresql"

        def __init__(self, settings_dict, alias):
            self.settings_dict = settings_dict
            self.alias = alias

        def ensure_connection(self):
            return None

        def close(self):
            return None

    source = FakeDatabase(
        {
            "TEST": {"MIRROR": "default"},
            "OPTIONS": {"connect_timeout": 10},
        },
        alias="health",
    )

    with _health_db_probe(source, deadline=time.monotonic() + 5) as (probe, _):
        assert "TEST" not in probe.settings_dict
    assert source.settings_dict["TEST"] == {"MIRROR": "default"}


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True)
def test_railway_health_does_not_use_shared_edge_throttle(monkeypatch):
    monkeypatch.setattr("config.health._railway_health_gate_last_result", None)
    monkeypatch.setattr("config.health._railway_health_gate_last_at", 0.0)
    monkeypatch.setattr("config.health._railway_health_gate_in_flight", False)
    monkeypatch.setattr(
        "config.health.check_rate_limit",
        lambda **kwargs: pytest.fail("Railway mode must not use shared peer bucket"),
    )
    monkeypatch.setattr(
        "config.health.check_health",
        lambda **kwargs: type("Result", (), {"healthy": True})(),
    )

    response = Client().get("/api/v1/health")

    assert response.status_code == 200


@override_settings(ALLIES_RAILWAY_PROXY_MODE=True)
def test_railway_health_gate_coalesces_repeated_dependency_probes(monkeypatch):
    calls = []
    monkeypatch.setattr("config.health._railway_health_gate_last_result", None)
    monkeypatch.setattr("config.health._railway_health_gate_last_at", 0.0)
    monkeypatch.setattr("config.health._railway_health_gate_in_flight", False)
    monkeypatch.setattr(
        "config.health.check_health",
        lambda **kwargs: (
            calls.append(kwargs) or type("Result", (), {"healthy": True})()
        ),
    )

    client = Client()
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200

    assert len(calls) == 1


def test_direct_health_gate_coalesces_distributed_probe_work(monkeypatch):
    calls = []
    monkeypatch.setattr("config.health.check_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr(
        "config.health.check_health",
        lambda **kwargs: (
            calls.append(kwargs) or type("Result", (), {"healthy": True})()
        ),
    )

    client = Client()
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200

    assert len(calls) == 1


def test_health_gate_fails_closed_while_a_previous_healthy_probe_is_in_flight(
    monkeypatch,
):
    monkeypatch.setattr("config.health._railway_health_gate_in_flight", True)
    monkeypatch.setattr(
        "config.health._railway_health_gate_last_result",
        HealthResult(healthy=True, elapsed_seconds=0.1),
    )

    result = _health_check_with_gate(total_budget=5.0)

    assert not result.healthy


def test_health_gate_preserves_a_previous_failure_while_a_probe_is_in_flight(
    monkeypatch,
):
    monkeypatch.setattr("config.health._railway_health_gate_in_flight", True)
    monkeypatch.setattr(
        "config.health._railway_health_gate_last_result",
        HealthResult(healthy=False, elapsed_seconds=0.1),
    )

    result = _health_check_with_gate(total_budget=5.0)

    assert result == HealthResult(healthy=False, elapsed_seconds=0.1)


@override_settings(
    CACHE_URL="redis://cache.internal:6379/0",
    CACHES={"health": {"BACKEND": "django.core.cache.backends.redis.RedisCache"}},
)
def test_redis_health_probe_uses_public_cache_api(monkeypatch):
    calls = []

    class HealthCache:
        def set(self, *args, **kwargs):
            calls.append(("set", args, kwargs))

        def get(self, *args, **kwargs):
            calls.append(("get", args, kwargs))
            return "ok"

        def delete(self, *args, **kwargs):
            calls.append(("delete", args, kwargs))

    monkeypatch.setattr("config.health.caches", {"health": HealthCache()})

    _probe_cache(deadline=time.monotonic() + 100.0)

    assert [name for name, _, _ in calls] == ["set", "get"]
    assert calls[0][2] == {"timeout": 5}


@pytest.mark.django_db
@override_settings(ALLIES_HEALTH_TOTAL_TIMEOUT_SECONDS=5.0)
def test_health_check_fails_when_total_budget_is_exceeded(monkeypatch, caplog):
    clock = [10.0]
    monkeypatch.setattr("config.health.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "config.health.cache.set", lambda *args, **kwargs: clock.__setitem__(0, 15.1)
    )

    with caplog.at_level(logging.WARNING, logger="config.health"):
        result = check_health()

    assert not result.healthy
    assert result.elapsed_seconds == pytest.approx(5.1)
    assert "exceeded total budget" in caplog.text


def test_health_failure_tracebacks_are_rate_limited(monkeypatch):
    detailed = []
    warnings = []
    monkeypatch.setattr(
        "config.health.logger.error", lambda *args, **kwargs: detailed.append(args)
    )
    monkeypatch.setattr(
        "config.health.logger.warning", lambda *args, **kwargs: warnings.append(args)
    )
    monkeypatch.setattr("config.health._health_failure_last_at", -60.0)
    monkeypatch.setattr("config.health.time.monotonic", lambda: 10.0)

    _log_health_failure(ConnectionError("redis.internal"))
    _log_health_failure(ConnectionError("redis.internal"))

    assert len(detailed) == 1
    assert len(warnings) == 1
