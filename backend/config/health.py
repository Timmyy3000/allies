"""Dependency-aware public health endpoint for platform readiness checks."""

from __future__ import annotations

import copy
import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from auths.api.common import (
    _client_identity,
    error_json,
    error_responses,
    success_json,
)
from auths.api.schemas import SuccessResponse
from auths.throttle import ThrottleExceeded, ThrottleUnavailable, check_rate_limit
from django.conf import settings
from django.core.cache import cache, caches
from django.core.cache.backends.redis import RedisCache
from django.db import connection, connections, transaction
from django.http import HttpRequest
from django.utils.connection import ConnectionProxy
from ninja import Schema
from ninja_extra import ControllerBase, api_controller, http_get

logger = logging.getLogger(__name__)


class HealthResponse(Schema):
    state: Literal["healthy"]


@dataclass(frozen=True)
class HealthResult:
    healthy: bool
    elapsed_seconds: float


class HealthBudgetExceeded(RuntimeError):
    """Raised when a dependency probe can no longer meet its endpoint budget."""


_RAILWAY_HEALTH_GATE_INTERVAL_SECONDS = 1.0
_railway_health_gate_lock = threading.Lock()
_railway_health_gate_in_flight = False
_railway_health_gate_last_at = 0.0
_railway_health_gate_last_result: HealthResult | None = None
_health_throttle_cache_lock = threading.Lock()
_health_throttle_cache_instance: RedisCache | None = None
_health_throttle_cache_signature: tuple[object, ...] | None = None
_health_failure_log_lock = threading.Lock()
_health_failure_last_at = 0.0
_HEALTH_FAILURE_LOG_INTERVAL_SECONDS = 60.0


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HealthBudgetExceeded
    return remaining


def _remaining_seconds_for_operation(deadline: float, timeout: float) -> float:
    """Require enough budget for a bounded operation before starting it."""

    remaining = _remaining_seconds(deadline)
    if remaining < timeout:
        raise HealthBudgetExceeded
    return min(timeout, remaining)


@contextmanager
def _health_db_probe(db, *, deadline: float):
    """Give each health connection attempt only the remaining probe budget.

    Django database wrappers keep their settings in a shared mutable mapping.
    Health probes therefore use a short-lived wrapper with a deep-copied
    settings mapping so concurrent requests cannot change application-wide
    connection behaviour while a probe is running.
    """

    settings_dict = getattr(db, "settings_dict", None)
    if settings_dict is None:
        # Lightweight test doubles do not expose Django's wrapper contract.
        yield db, True
        return

    isolated_settings = copy.deepcopy(settings_dict)
    # The health alias mirrors ``default`` in Django's test configuration so
    # the test suite does not create a second database.  That setting must not
    # follow the short-lived production probe wrapper: Django would route its
    # cursor calls back to the shared default connection and defeat the
    # probe-local timeout and isolation guarantees.
    isolated_settings.pop("TEST", None)
    options = isolated_settings.setdefault("OPTIONS", {})
    original_timeout = options.get("connect_timeout")
    remaining = _remaining_seconds(deadline)
    if remaining < 1:
        raise HealthBudgetExceeded
    if getattr(db, "vendor", None) == "postgresql":
        configured_timeout = float(original_timeout or 1)
        options["connect_timeout"] = max(
            1, min(int(remaining), int(configured_timeout))
        )
    probe_db = type(db)(
        isolated_settings,
        alias=f"{getattr(db, 'alias', 'default')}__health_probe",
    )
    try:
        probe_db.ensure_connection()
        yield probe_db, False
    finally:
        close = getattr(probe_db, "close", None)
        if close:
            close()


@contextmanager
def _health_probe_transaction(db, *, alias: str, use_atomic: bool):
    """Run the probe in a transaction without touching shared connections."""

    if use_atomic:
        # Lightweight test doubles do not expose a full database wrapper. The
        # production path uses ``use_atomic=False`` and controls the
        # transaction directly on the short-lived probe wrapper below.
        with transaction.atomic(using=alias), db.cursor() as cursor:
            yield cursor
        return

    db.set_autocommit(False)
    try:
        with db.cursor() as cursor:
            yield cursor
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.set_autocommit(True)


def _health_probe_cache(*, deadline: float):
    """Build a binary-safe Redis probe backend within the remaining budget."""

    health_cache = _health_cache_backend()
    if not isinstance(health_cache, RedisCache):
        return health_cache
    config = settings.CACHES["health"]
    timeout = _remaining_seconds_for_operation(
        deadline,
        getattr(settings, "HEALTH_CACHE_OPERATION_TIMEOUT_SECONDS", 0.001),
    )
    params = {
        **config,
        "OPTIONS": {
            **config.get("OPTIONS", {}),
            "socket_connect_timeout": timeout,
            "socket_timeout": timeout,
        },
    }
    return RedisCache(config["LOCATION"], params)


def _log_health_failure(exc: Exception) -> None:
    """Keep outage tracebacks useful without emitting one for every probe."""

    global _health_failure_last_at
    now = time.monotonic()
    with _health_failure_log_lock:
        detailed = now - _health_failure_last_at >= _HEALTH_FAILURE_LOG_INTERVAL_SECONDS
        if detailed:
            _health_failure_last_at = now
    if detailed:
        logger.error(
            "health dependency check failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    else:
        logger.warning(
            "health dependency check failed; traceback suppressed",
            extra={"error_type": type(exc).__name__},
        )


def _probe_cache(*, deadline: float) -> None:
    # A unique short-lived key avoids a delete race between concurrent probes.
    key = f"allies:health:probe:{uuid4().hex}"
    health_cache = _health_probe_cache(deadline=deadline)

    timeout = getattr(settings, "HEALTH_CACHE_OPERATION_TIMEOUT_SECONDS", 0.001)
    _remaining_seconds_for_operation(deadline, timeout)
    health_cache.set(key, "ok", timeout=5)
    _remaining_seconds_for_operation(deadline, timeout)
    if health_cache.get(key) != "ok":
        raise RuntimeError("cache probe mismatch")
    _remaining_seconds(deadline)


def _health_cache_backend():
    if getattr(settings, "CACHE_URL", "") and "health" in settings.CACHES:
        return caches["health"]
    return cache


def _health_throttle_cache(*, deadline: float):
    """Use application cache semantics with a deadline-bounded Redis client."""

    global _health_throttle_cache_instance
    global _health_throttle_cache_signature

    application_cache = (
        caches["default"] if getattr(settings, "CACHE_URL", "") else cache
    )
    if not isinstance(application_cache, RedisCache):
        return application_cache
    config = settings.CACHES["default"]
    options = config.get("OPTIONS", {})
    configured_connect = float(
        options.get(
            "socket_connect_timeout",
            getattr(settings, "HEALTH_CACHE_OPERATION_TIMEOUT_SECONDS", 0.001),
        )
    )
    configured_socket = float(
        options.get(
            "socket_timeout",
            getattr(settings, "HEALTH_CACHE_OPERATION_TIMEOUT_SECONDS", 0.001),
        )
    )
    # A failed counter check can issue add then incr. Keep both operations
    # below the health operation budget while reusing one pool per worker.
    timeout = max(
        0.001,
        min(
            getattr(settings, "HEALTH_CACHE_OPERATION_TIMEOUT_SECONDS", 0.001),
            configured_connect,
            configured_socket,
        ),
    )
    _remaining_seconds_for_operation(deadline, timeout)
    signature = (config["LOCATION"], repr(options), timeout)
    with _health_throttle_cache_lock:
        if (
            _health_throttle_cache_instance is None
            or _health_throttle_cache_signature != signature
        ):
            params = {
                **config,
                "OPTIONS": {
                    **options,
                    "socket_connect_timeout": timeout,
                    "socket_timeout": timeout,
                },
            }
            _health_throttle_cache_instance = RedisCache(config["LOCATION"], params)
            _health_throttle_cache_signature = signature
        return _health_throttle_cache_instance


def check_health(*, total_budget: float | None = None) -> HealthResult:
    """Probe Postgres and Redis without exposing dependency details."""

    started = time.monotonic()
    operation_budget = getattr(settings, "ALLIES_HEALTH_OPERATION_TIMEOUT_SECONDS", 2.0)
    if total_budget is None:
        total_budget = getattr(settings, "ALLIES_HEALTH_TOTAL_TIMEOUT_SECONDS", 5.0)
    deadline = started + total_budget
    try:
        db = connections["health"] if "health" in connections.databases else connection
        db_alias = getattr(db, "alias", "default")
        if isinstance(db, ConnectionProxy):
            db = connections[db._alias]
        with (
            _health_db_probe(db, deadline=deadline) as (probe_db, use_atomic),
            _health_probe_transaction(
                probe_db,
                alias=db_alias,
                use_atomic=use_atomic,
            ) as cursor,
        ):
            operation_timeout = min(operation_budget, _remaining_seconds(deadline))
            if probe_db.vendor == "postgresql":
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    [str(max(1, int(operation_timeout * 1000)))],
                )
            _remaining_seconds(deadline)
            cursor.execute("SELECT 1")
            cursor.fetchone()
        _probe_cache(deadline=deadline)
        elapsed = time.monotonic() - started
        if elapsed > total_budget:
            raise HealthBudgetExceeded
    except HealthBudgetExceeded:
        elapsed = time.monotonic() - started
        logger.warning("health dependency check exceeded total budget")
        return HealthResult(healthy=False, elapsed_seconds=elapsed)
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed
        elapsed = time.monotonic() - started
        _log_health_failure(exc)
        return HealthResult(healthy=False, elapsed_seconds=elapsed)
    elapsed = time.monotonic() - started
    return HealthResult(healthy=True, elapsed_seconds=elapsed)


def _health_check_with_gate(*, total_budget: float) -> HealthResult:
    """Bound public probes while preserving a fresh readiness result.

    Railway presents a shared peer address, so an IP bucket cannot distinguish
    platform probes from public traffic. Direct deployments can also receive
    distributed traffic across many /24s. A process-local gate permits one
    dependency probe per short interval and serves its last result to bursts;
    this caps dependency load without making readiness depend on caller IP.
    """

    global _railway_health_gate_in_flight
    global _railway_health_gate_last_at
    global _railway_health_gate_last_result

    now = time.monotonic()
    with _railway_health_gate_lock:
        if _railway_health_gate_in_flight:
            if _railway_health_gate_last_result is not None:
                return _railway_health_gate_last_result
            return HealthResult(healthy=False, elapsed_seconds=0.0)
        if (
            _railway_health_gate_last_result is not None
            and now - _railway_health_gate_last_at
            < _RAILWAY_HEALTH_GATE_INTERVAL_SECONDS
        ):
            return _railway_health_gate_last_result
        _railway_health_gate_in_flight = True

    result = HealthResult(healthy=False, elapsed_seconds=0.0)
    try:
        result = check_health(total_budget=total_budget)
    except Exception as exc:  # noqa: BLE001 - readiness must fail closed
        _log_health_failure(exc)
    finally:
        with _railway_health_gate_lock:
            _railway_health_gate_in_flight = False
            _railway_health_gate_last_result = result
            _railway_health_gate_last_at = time.monotonic()
    return result


@api_controller("", tags=["Operations"])
class HealthController(ControllerBase):
    @http_get(
        "/health",
        response={
            200: SuccessResponse[HealthResponse],
            **error_responses(429, 503),
        },
    )
    def health(self, request: HttpRequest):
        started = time.monotonic()
        total_budget = getattr(settings, "ALLIES_HEALTH_TOTAL_TIMEOUT_SECONDS", 5.0)
        if not getattr(settings, "ALLIES_RAILWAY_PROXY_MODE", False):
            try:
                check_rate_limit(
                    scope="health-ip",
                    identity=_client_identity(request),
                    limit=60,
                    period=60,
                    cache_backend=_health_throttle_cache(
                        deadline=started + total_budget
                    ),
                )
            except ThrottleExceeded:
                return error_json("throttled", "try again later", 429)
            except ThrottleUnavailable:
                return error_json("service_unavailable", "Service unavailable", 503)
            except HealthBudgetExceeded:
                return error_json("service_unavailable", "Service unavailable", 503)
            remaining_budget = total_budget - (time.monotonic() - started)
            if remaining_budget <= 0:
                return error_json("service_unavailable", "Service unavailable", 503)
            result = _health_check_with_gate(total_budget=remaining_budget)
        else:
            result = _health_check_with_gate(total_budget=total_budget)
        if not result.healthy:
            return error_json("service_unavailable", "Service unavailable", 503)
        return success_json(HealthResponse(state="healthy"), "Service healthy")
