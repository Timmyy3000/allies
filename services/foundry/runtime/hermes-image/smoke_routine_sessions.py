"""Bounded Class A/Class B evidence probe for routine session feasibility.

Class A exercises the installed provider and its profile-local storage without
starting Hermes or a model. Class B is deliberately stricter: it only reports
capability after an authenticated, real Hermes service and model turn prove
the required session properties.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import importlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

MODEL = os.environ.get("CLD012_MODEL", "gpt-5.6-luna")
MAX_TIMEOUT_SECONDS = 60.0
SERVER_OBSERVABLE_BARRIER_PREREQUISITE = "server_observable_barrier_events_required"
MAIN_CONVERSATION = "cld012-main-conversation"
ROUTINE_CONVERSATIONS = (
    "cld012-routine-conversation-a",
    "cld012-routine-conversation-b",
)
HISTORY_CANARY_ASSERTIONS = (
    (MAIN_CONVERSATION, "CLD012_MAIN_CANARY", "CLD012_ROUTINE_A_CANARY"),
    (MAIN_CONVERSATION, "CLD012_MAIN_CANARY", "CLD012_ROUTINE_B_CANARY"),
    (ROUTINE_CONVERSATIONS[0], "CLD012_ROUTINE_A_CANARY", "CLD012_MAIN_CANARY"),
    (ROUTINE_CONVERSATIONS[0], "CLD012_ROUTINE_A_CANARY", "CLD012_ROUTINE_B_CANARY"),
    (ROUTINE_CONVERSATIONS[1], "CLD012_ROUTINE_B_CANARY", "CLD012_MAIN_CANARY"),
    (ROUTINE_CONVERSATIONS[1], "CLD012_ROUTINE_B_CANARY", "CLD012_ROUTINE_A_CANARY"),
)
OFFLINE_FACT_MARKERS = (
    "CLD012_OFFLINE_FACT_A",
    "CLD012_OFFLINE_FACT_B",
)
OFFLINE_CONTENTION_MARKERS = (
    "CLD012_OFFLINE_CONTENTION_A",
    "CLD012_OFFLINE_CONTENTION_B",
)
SUCCESS_STATUSES = frozenset({"ok", "stored"})
REJECTED_STATUSES = frozenset({"tool_rejected", "memory_unavailable", "tool_error"})
RESULT_CONTENT_KEYS = frozenset(
    {
        "body",
        "content",
        "contents",
        "data",
        "memories",
        "memory",
        "record",
        "records",
        "result",
        "results",
        "text",
        "value",
    }
)


def _check(name: str, status: str, detail: str | None = None) -> dict[str, str]:
    value = {"name": name, "status": status}
    if detail:
        value["detail"] = detail
    return value


def _safe_reason(error: BaseException) -> str:
    return type(error).__name__.lower().replace("error", "") or "probe_error"


def _report(mode: str, status: str, checks: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "episode": "CLD-012",
        "mode": mode,
        "status": status,
        "model": MODEL,
        "checks": checks,
        "provider": "allies_mnemosyne",
        "source_commit": "36cb5ae5530a75def7df3195e49b7a4aa2add482",
    }


def _service_status(checks: list[dict[str, str]]) -> str:
    if any(item["status"] == "fail" for item in checks):
        return "CAPABILITY_FAILED"
    if any(
        item["name"] == "server_observable_barrier" and item["status"] == "blocked"
        for item in checks
    ):
        return "SETUP_BLOCKED"
    return (
        "CAPABILITY_PASSED"
        if all(item["status"] == "pass" for item in checks)
        else "CAPABILITY_FAILED"
    )


def _provider_instance(
    provider_class: type[Any],
    root: Path,
    profile_key: str,
    *,
    session_id: str | None = None,
    memory_mode: str = "context_only",
    memory_tools: list[str] | None = None,
) -> Any:
    provider = provider_class()
    provider.initialize(
        session_id or f"{profile_key}-session",
        hermes_home=str(root),
        profile_root=str(root),
        agent_identity=profile_key,
        agent_context="conversation",
        memory_mode=memory_mode,
        tools=memory_tools or [],
    )
    return provider


def _tool_result(provider: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(provider.handle_tool_call(name, arguments))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"status": "malformed"}
    return value if isinstance(value, dict) else {"status": "malformed"}


def _tool_succeeded(result: dict[str, Any]) -> bool:
    status = result.get("status")
    return status in SUCCESS_STATUSES and status not in REJECTED_STATUSES


def _recall_succeeded(result: dict[str, Any]) -> bool:
    status = result.get("status")
    return (
        status in SUCCESS_STATUSES
        and status not in REJECTED_STATUSES
        and type(result.get("count")) is int
        and result["count"] >= 0
        and isinstance(result.get("results"), list)
    )


def _returned_record_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_returned_record_content(item) for item in value)
    if isinstance(value, dict):
        return " ".join(
            _returned_record_content(value[key])
            for key in RESULT_CONTENT_KEYS
            if key in value
        )
    return ""


def _shutdown_provider(provider: Any, timeout_seconds: float = 1.0) -> bool:
    completed = threading.Event()
    outcome = False

    def shutdown() -> None:
        nonlocal outcome
        try:
            provider.shutdown()
        except Exception:  # noqa: BLE001 - cleanup is best effort and sanitized
            return
        else:
            outcome = True
        finally:
            completed.set()

    thread = threading.Thread(target=shutdown, name="cld012-provider-cleanup", daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    return completed.is_set() and outcome


class _BoundedCallTimeout(TimeoutError):
    """A synchronous provider call exceeded the current probe deadline."""


def _bounded_call(
    function: Callable[[], Any],
    timeout_seconds: float,
    *,
    late_result_cleanup: Callable[[Any], Any] | None = None,
) -> Any:
    """Run one blocking call in a daemon worker without extending the deadline."""

    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise _BoundedCallTimeout

    lock = threading.Lock()
    completed = threading.Event()
    state: dict[str, Any] = {
        "outcome": "pending",
        "value": None,
        "error": None,
        "timed_out": False,
        "cleanup_claimed": False,
    }

    def cleanup_late_value(value: Any) -> None:
        if late_result_cleanup is None:
            return
        try:
            late_result_cleanup(value)
        except Exception:  # noqa: BLE001 - late cleanup is best effort
            return

    def worker() -> None:
        try:
            value = function()
        except BaseException as error:  # noqa: BLE001 - re-raised on the caller
            with lock:
                state["outcome"] = "error"
                state["error"] = error
        else:
            cleanup_value: Any = None
            should_cleanup = False
            with lock:
                state["outcome"] = "value"
                state["value"] = value
                if state["timed_out"] and not state["cleanup_claimed"]:
                    state["cleanup_claimed"] = True
                    cleanup_value = value
                    should_cleanup = True
            if should_cleanup:
                cleanup_late_value(cleanup_value)
        finally:
            completed.set()

    threading.Thread(
        target=worker,
        name="cld012-bounded-call",
        daemon=True,
    ).start()
    if completed.wait(timeout_seconds):
        with lock:
            outcome = state["outcome"]
            value = state["value"]
            error = state["error"]
        if outcome == "error":
            raise error
        return value

    cleanup_value = None
    should_cleanup = False
    with lock:
        state["timed_out"] = True
        if (
            state["outcome"] == "value"
            and not state["cleanup_claimed"]
        ):
            state["cleanup_claimed"] = True
            cleanup_value = state["value"]
            should_cleanup = True
    if should_cleanup:
        cleanup_late_value(cleanup_value)
    raise _BoundedCallTimeout


def _call_until(
    function: Callable[[], Any],
    deadline: float,
    *,
    late_result_cleanup: Callable[[Any], Any] | None = None,
) -> Any:
    return _bounded_call(
        function,
        deadline - time.monotonic(),
        late_result_cleanup=late_result_cleanup,
    )


def _sqlite_busy_timeout(database_path: Any) -> int:
    with sqlite3.connect(database_path) as connection:
        return connection.execute("PRAGMA busy_timeout").fetchone()[0]


def _run_concurrent_writes(
    first: Any,
    second: Any,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], bool]:
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        return [], False

    barrier = threading.Barrier(2)
    futures: list[concurrent.futures.Future[dict[str, Any]]] = []
    threads: list[threading.Thread] = []
    deadline = time.monotonic() + timeout_seconds

    def write(
        provider: Any,
        marker: str,
        future: concurrent.futures.Future[dict[str, Any]],
    ) -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            barrier.wait(timeout=max(0.01, deadline - time.monotonic()))
            # Keep the barrier directly adjacent to the provider call: both
            # distinct sessions must enter the contention window together.
            result = _tool_result(
                provider,
                "mnemosyne_remember",
                {"content": marker, "source": "preference"},
            )
        except threading.BrokenBarrierError:
            result = {"status": "barrier_broken"}
        except Exception as error:  # noqa: BLE001 - sanitized below
            try:
                future.set_exception(error)
            except concurrent.futures.InvalidStateError:
                pass
            return
        try:
            future.set_result(result)
        except concurrent.futures.InvalidStateError:
            pass

    try:
        for provider, marker in zip((first, second), OFFLINE_CONTENTION_MARKERS, strict=True):
            future: concurrent.futures.Future[dict[str, Any]] = concurrent.futures.Future()
            thread = threading.Thread(
                target=write,
                args=(provider, marker, future),
                name="cld012-contention-write",
                daemon=True,
            )
            futures.append(future)
            threads.append(thread)
            thread.start()
    except RuntimeError:
        barrier.abort()
        for future in futures:
            future.cancel()
        return [], False

    results: list[dict[str, Any]] = []
    timed_out = False
    for future in futures:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        try:
            results.append(future.result(timeout=remaining))
        except concurrent.futures.TimeoutError:
            timed_out = True
            break
        except Exception as error:  # noqa: BLE001 - output is sanitized below
            results.append({"status": "worker_error", "detail": _safe_reason(error)})

    if timed_out:
        barrier.abort()
        for future in futures:
            future.cancel()

    join_deadline = time.monotonic() + 0.05
    for thread in threads:
        thread.join(timeout=max(0.0, join_deadline - time.monotonic()))
    return results, not timed_out and len(results) == len(futures)


def _recall_markers(provider: Any, markers: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        _tool_result(provider, "mnemosyne_recall", {"query": marker})
        for marker in markers
    ]


def _markers_recalled(results: list[dict[str, Any]], markers: tuple[str, ...]) -> bool:
    return len(results) == len(markers) and all(
        _recall_succeeded(result) and marker in _returned_record_content(result)
        for result, marker in zip(results, markers, strict=True)
    )


def _blocked_memory_checks(checks: list[dict[str, str]], detail: str) -> None:
    checks.extend(
        _check(name, "blocked", detail)
        for name in (
            "shared_profile_concurrent_writes",
            "fresh_shared_session_recall",
            "fresh_shared_session_contention_recall",
            "second_profile_cannot_read_shared_fact",
        )
    )


def _offline_memory_checks(
    provider_class: type[Any], root: Path, checks: list[dict[str, str]], deadline: float
) -> None:
    shared_root = root / "shared-profile"
    shared_root.mkdir()
    profile_key = "cld012-shared-profile"
    approved_tools = ["mnemosyne_recall", "mnemosyne_remember"]
    isolated_root = root / "isolated-profile"
    isolated_root.mkdir()
    providers: list[Any] = []
    first: Any | None = None
    second: Any | None = None
    isolated: Any | None = None
    try:
        try:
            first = _call_until(
                lambda: _provider_instance(
                    provider_class,
                    shared_root,
                    profile_key,
                    session_id="cld012-shared-session-a",
                    memory_mode="narrow_tools",
                    memory_tools=approved_tools,
                ),
                deadline,
                late_result_cleanup=_shutdown_provider,
            )
            providers.append(first)
            second = _call_until(
                lambda: _provider_instance(
                    provider_class,
                    shared_root,
                    profile_key,
                    session_id="cld012-shared-session-b",
                    memory_mode="narrow_tools",
                    memory_tools=approved_tools,
                ),
                deadline,
                late_result_cleanup=_shutdown_provider,
            )
            providers.append(second)
            isolated = _call_until(
                lambda: _provider_instance(
                    provider_class,
                    isolated_root,
                    "cld012-isolated-profile",
                    memory_mode="narrow_tools",
                    memory_tools=approved_tools,
                ),
                deadline,
                late_result_cleanup=_shutdown_provider,
            )
            providers.append(isolated)
        except _BoundedCallTimeout:
            checks.append(
                _check(
                    "provider_initialization",
                    "fail",
                    "bounded provider initialization timed out",
                )
            )
            return

        for name, provider in (("shared_first", first), ("shared_second", second), ("isolated", isolated)):
            try:
                status = _call_until(provider.status, deadline)
                tool_names = _call_until(provider.get_tool_names, deadline)
            except _BoundedCallTimeout:
                checks.append(
                    _check(
                        f"{name}_narrow_tools_ready",
                        "fail",
                        "bounded provider status timed out",
                    )
                )
                return
            checks.append(
                _check(
                    f"{name}_narrow_tools_ready",
                    "pass"
                    if status.get("available")
                    and status.get("mode") == "narrow_tools"
                    and {"mnemosyne_remember", "mnemosyne_recall"}
                    <= set(tool_names)
                    else "fail",
                )
            )

        try:
            write_a = _call_until(
                lambda: _tool_result(
                    first,
                    "mnemosyne_remember",
                    {"content": "CLD012_OFFLINE_FACT_A", "source": "preference"},
                ),
                deadline,
            )
            write_b = _call_until(
                lambda: _tool_result(
                    second,
                    "mnemosyne_remember",
                    {"content": "CLD012_OFFLINE_FACT_B", "source": "preference"},
                ),
                deadline,
            )
        except _BoundedCallTimeout:
            checks.append(
                _check(
                    "shared_profile_distinct_writes",
                    "fail",
                    "bounded provider tool call timed out",
                )
            )
            _blocked_memory_checks(checks, "skipped after a bounded provider timeout")
            return
        checks.append(
            _check(
                "shared_profile_distinct_writes",
                "pass" if _tool_succeeded(write_a) and _tool_succeeded(write_b) else "fail",
            )
        )

        contention_budget = deadline - time.monotonic()
        concurrent_results, contention_completed = _run_concurrent_writes(
            first,
            second,
            contention_budget,
        )
        checks.append(
            _check(
                "shared_profile_concurrent_writes",
                "pass"
                if contention_completed
                and all(_tool_succeeded(result) for result in concurrent_results)
                else "fail",
                "bounded contention write timed out"
                if not contention_completed
                else None,
            )
        )

        if contention_completed:
            try:
                fresh = _call_until(
                    lambda: _provider_instance(
                        provider_class,
                        shared_root,
                        profile_key,
                        session_id="cld012-shared-session-fresh",
                        memory_mode="narrow_tools",
                        memory_tools=approved_tools,
                    ),
                    deadline,
                    late_result_cleanup=_shutdown_provider,
                )
            except _BoundedCallTimeout:
                checks.extend(
                    (
                        _check(
                            "fresh_shared_session_recall",
                            "blocked",
                            "fresh provider initialization timed out",
                        ),
                        _check(
                            "fresh_shared_session_contention_recall",
                            "blocked",
                            "fresh provider initialization timed out",
                        ),
                        _check(
                            "fresh_provider_cleanup",
                            "blocked",
                            "fresh provider initialization timed out",
                        ),
                        _check(
                            "second_profile_cannot_read_shared_fact",
                            "blocked",
                            "skipped after a bounded provider timeout",
                        ),
                    )
                )
                return
            try:
                try:
                    recall_results = _call_until(
                        lambda: _recall_markers(fresh, OFFLINE_FACT_MARKERS),
                        deadline,
                    )
                    contention_recall_results = _call_until(
                        lambda: _recall_markers(fresh, OFFLINE_CONTENTION_MARKERS),
                        deadline,
                    )
                except _BoundedCallTimeout:
                    recall_results = []
                    contention_recall_results = []
                    recall_timed_out = True
                else:
                    recall_timed_out = False
            finally:
                fresh_cleanup_ok = _shutdown_provider(fresh)
            if recall_timed_out:
                checks.extend(
                    (
                        _check(
                            "fresh_shared_session_recall",
                            "fail",
                            "bounded provider recall timed out",
                        ),
                        _check(
                            "fresh_shared_session_contention_recall",
                            "blocked",
                            "skipped after a bounded provider timeout",
                        ),
                        _check(
                            "fresh_provider_cleanup",
                            "pass" if fresh_cleanup_ok else "fail",
                        ),
                        _check(
                            "second_profile_cannot_read_shared_fact",
                            "blocked",
                            "skipped after a bounded provider timeout",
                        ),
                    )
                )
                return
            checks.extend(
                (
                    _check(
                        "fresh_shared_session_recall",
                        "pass"
                        if _markers_recalled(recall_results, OFFLINE_FACT_MARKERS)
                        else "fail",
                    ),
                    _check(
                        "fresh_shared_session_contention_recall",
                        "pass"
                        if _markers_recalled(
                            contention_recall_results, OFFLINE_CONTENTION_MARKERS
                        )
                        else "fail",
                    ),
                    _check(
                        "fresh_provider_cleanup",
                        "pass" if fresh_cleanup_ok else "fail",
                    ),
                )
            )
        else:
            checks.extend(
                (
                    _check(
                        "fresh_shared_session_recall",
                        "blocked",
                        "skipped after bounded contention-write timeout",
                    ),
                    _check(
                        "fresh_shared_session_contention_recall",
                        "blocked",
                        "skipped after bounded contention-write timeout",
                    ),
                    _check(
                        "second_profile_cannot_read_shared_fact",
                        "blocked",
                        "skipped after bounded contention-write timeout",
                    ),
                )
            )
            return
        try:
            isolated_recall = _call_until(
                lambda: _tool_result(
                    isolated,
                    "mnemosyne_recall",
                    {"query": "CLD012_OFFLINE_FACT_A"},
                ),
                deadline,
            )
        except _BoundedCallTimeout:
            checks.append(
                _check(
                    "second_profile_cannot_read_shared_fact",
                    "fail",
                    "bounded provider recall timed out",
                )
            )
            return
        isolated_content = _returned_record_content(isolated_recall)
        checks.append(
            _check(
                "second_profile_cannot_read_shared_fact",
                "pass"
                if _recall_succeeded(isolated_recall)
                and "CLD012_OFFLINE_FACT_A" not in isolated_content
                else "fail",
            )
        )
    finally:
        cleanup_results = [_shutdown_provider(provider) for provider in providers]
        if not all(cleanup_results):
            checks.append(_check("shared_provider_cleanup", "fail"))


def run_offline(timeout_seconds: float = MAX_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run provider/storage checks without a service, network, or model."""

    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be between 0 and 60")
    started = time.monotonic()
    deadline = started + timeout_seconds
    try:
        module = importlib.import_module("allies_mnemosyne")
        provider_class = module.AlliesMnemosyneProvider
    except (ImportError, AttributeError) as error:
        return _report(
            "offline",
            "SETUP_BLOCKED",
            [_check("provider_import", "blocked", _safe_reason(error))],
        )

    checks: list[dict[str, str]] = []
    providers: list[Any] = []
    timed_out = False
    try:
        with tempfile.TemporaryDirectory(prefix="cld012-provider-") as temporary:
            root = Path(temporary)
            profile_db_roots: list[Any] = []
            for index in ("a", "b"):
                if time.monotonic() >= deadline:
                    checks.append(_check("offline_timeout", "fail", "deadline exhausted"))
                    timed_out = True
                    break
                profile_root = root / f"profile-{index}"
                profile_root.mkdir()
                try:
                    provider = _call_until(
                        lambda profile_root=profile_root, index=index: _provider_instance(
                            provider_class,
                            profile_root,
                            f"cld012-profile-{index}",
                        ),
                        deadline,
                        late_result_cleanup=_shutdown_provider,
                    )
                except _BoundedCallTimeout:
                    checks.append(
                        _check(
                            f"provider_{index}_initialization",
                            "fail",
                            "bounded provider initialization timed out",
                        )
                    )
                    timed_out = True
                    break
                providers.append(provider)
                try:
                    status = _call_until(provider.status, deadline)
                    tool_schemas = _call_until(provider.get_tool_schemas, deadline)
                except _BoundedCallTimeout:
                    checks.append(
                        _check(
                            f"provider_{index}_status",
                            "fail",
                            "bounded provider status timed out",
                        )
                    )
                    timed_out = True
                    break
                profile_db_roots.append(status.get("profile_db_root"))
                checks.extend(
                    (
                        _check(f"provider_{index}_ready", "pass" if status.get("available") else "fail"),
                        _check(f"provider_{index}_profile_keyed", "pass" if status.get("profile_keyed") else "fail"),
                        _check(
                            f"provider_{index}_shared_surface_disabled",
                            "pass" if status.get("shared_surface") is False else "fail",
                        ),
                        _check(
                            f"provider_{index}_context_only_tools",
                            "pass" if tool_schemas == [] else "fail",
                        ),
                    )
                )
                database_path = getattr(provider, "_db_path", None)
                if database_path is None:
                    checks.append(_check(f"provider_{index}_database", "fail"))
                    continue
                try:
                    busy_timeout = _call_until(
                        lambda database_path=database_path: _sqlite_busy_timeout(database_path),
                        deadline,
                    )
                except _BoundedCallTimeout:
                    checks.append(
                        _check(
                            f"provider_{index}_sqlite_timeout",
                            "fail",
                            "bounded SQLite inspection timed out",
                        )
                    )
                    timed_out = True
                    break
                checks.append(
                    _check(f"provider_{index}_sqlite_timeout", "pass" if busy_timeout == 5000 else "fail")
                )
            if not timed_out:
                checks.append(
                    _check(
                        "profile_storage_isolation",
                        "pass"
                        if len(profile_db_roots) == 2
                        and profile_db_roots[0] != profile_db_roots[1]
                        else "fail",
                    )
                )
            if not timed_out and all(item["status"] == "pass" for item in checks):
                _offline_memory_checks(
                    provider_class,
                    root,
                    checks,
                    deadline=deadline,
                )
    except (ImportError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as error:
        checks.append(_check("provider_storage", "fail", _safe_reason(error)))
    finally:
        cleanup_results = [_shutdown_provider(provider) for provider in providers]
        if cleanup_results and not all(cleanup_results):
            checks.append(_check("provider_cleanup", "fail"))

    if timed_out:
        return _report("offline", "OFFLINE_DIAGNOSTICS_FAILED", checks)
    status = "CLASS_A_PASSED" if all(item["status"] == "pass" for item in checks) else "OFFLINE_DIAGNOSTICS_FAILED"
    return _report("offline", status, checks)


def _ready_status(health: Any) -> bool:
    status = getattr(health, "status", None)
    if isinstance(status, str) and status.lower() in {"ok", "ready", "healthy"}:
        return True
    readiness = getattr(health, "readiness", None)
    checks = readiness.get("checks") if isinstance(readiness, dict) else None
    gateway = checks.get("gateway") if isinstance(checks, dict) else None
    return (
        isinstance(status, str)
        and status.lower() == "degraded"
        and isinstance(gateway, dict)
        and gateway.get("status") == "ok"
        and gateway.get("state") == "running"
    )


def _server_observable_concurrency_checks(
    results: Mapping[str, Any],
    client_intervals: Mapping[str, tuple[float, float]],
) -> tuple[dict[str, str], ...]:
    """Refuse client-lifetime overlap without a Hermes server barrier marker."""

    _ = results, client_intervals
    detail = SERVER_OBSERVABLE_BARRIER_PREREQUISITE
    return (
        _check("server_observable_barrier", "blocked", detail),
        _check("main_and_routine_overlap", "blocked", detail),
        _check("main_completion_while_routine_active", "blocked", detail),
    )


async def _wait_ready(client: Any, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if await _ready_once(client):
            return True
        await asyncio.sleep(min(0.25, max(0.01, deadline - time.monotonic())))
    return False


async def _ready_once(client: Any) -> bool:
    try:
        return _ready_status(await client.health_detailed())
    except Exception:  # noqa: BLE001 - readiness must fail closed
        return False


async def _service_probe(timeout_seconds: float) -> dict[str, Any]:
    try:
        from allies_runtime.config import load_settings
        from allies_runtime.hermes import HermesClient, stable_session_identifiers
        from allies_runtime.profile_store import ProfileStore
    except (ImportError, AttributeError) as error:
        return _report("service", "SETUP_BLOCKED", [_check("runtime_import", "blocked", _safe_reason(error))])

    profile_id = os.environ.get("CLD012_HERMES_PROFILE_ID", "")
    if not profile_id or not os.environ.get("HERMES_CREDENTIAL_REF"):
        return _report("service", "SETUP_BLOCKED", [_check("profile_bootstrap", "blocked", "authorized profile and credential reference are required")])

    try:
        values = dict(os.environ)
        settings = load_settings(values)
        profile_store_root = Path(settings.volume_root)
        store = ProfileStore(profile_store_root)

        def resolver(_reference):
            return store.read_api_key(profile_id)

        def profile_resolver(key):
            return store.read_api_key(key)

        client = HermesClient(
            settings,
            resolver,
            profile_credential_resolver=profile_resolver,
        )
    except (OSError, TypeError, ValueError) as error:
        return _report("service", "SETUP_BLOCKED", [_check("service_configuration", "blocked", _safe_reason(error))])

    checks: list[dict[str, str]] = []
    if not await _wait_ready(client, timeout_seconds):
        return _report("service", "READINESS_FAILED", [_check("authenticated_readiness", "fail")])
    checks.append(_check("authenticated_readiness", "pass"))

    try:
        preflight_ids = stable_session_identifiers(profile_id, "cld012-model-preflight")
        await client.create_profile_session(profile_id, preflight_ids.candidate_id, model=MODEL)
        preflight = await asyncio.wait_for(
            client.stream_profile(
                profile_id,
                preflight_ids.candidate_id,
                "CLD012 model preflight. Reply with the word READY.",
                session_key=preflight_ids.session_key,
            ),
            timeout=timeout_seconds,
        )
        if not preflight.events:
            return _report("service", "MODEL_PREFLIGHT_FAILED", checks + [_check("model_preflight", "fail")])
    except Exception as error:  # noqa: BLE001 - output is sanitized below
        return _report("service", "MODEL_PREFLIGHT_FAILED", checks + [_check("model_preflight", "fail", _safe_reason(error))])
    checks.append(_check("model_preflight", "pass"))

    sessions: dict[str, tuple[str, str]] = {}
    for conversation in (MAIN_CONVERSATION, *ROUTINE_CONVERSATIONS):
        identifiers = stable_session_identifiers(profile_id, conversation)
        sessions[conversation] = (identifiers.candidate_id, identifiers.session_key)
        try:
            await client.create_profile_session(profile_id, identifiers.candidate_id, model=MODEL)
        except Exception as error:  # noqa: BLE001 - sanitized result
            return _report("service", "CAPABILITY_FAILED", checks + [_check("session_creation", "fail", _safe_reason(error))])

    results: dict[str, Any] = {}

    async def run_session(conversation: str, prompt: str) -> None:
        session_id, session_key = sessions[conversation]
        try:
            result = await asyncio.wait_for(
                client.stream_profile(
                    profile_id,
                    session_id,
                    prompt,
                    session_key=session_key,
                ),
                timeout=timeout_seconds,
            )
            results[conversation] = result
        except Exception as error:  # noqa: BLE001 - sanitized result
            results[conversation] = error

    await asyncio.gather(
        run_session(MAIN_CONVERSATION, "CLD012_MAIN_CANARY: report the synthetic main result."),
        run_session(ROUTINE_CONVERSATIONS[0], "CLD012_ROUTINE_A_CANARY: hold this synthetic routine briefly, then report."),
        run_session(ROUTINE_CONVERSATIONS[1], "CLD012_ROUTINE_B_CANARY: hold this synthetic routine briefly, then report."),
    )

    failed = [value for value in results.values() if isinstance(value, BaseException)]
    if failed:
        checks.append(_check("real_session_turns", "fail", _safe_reason(failed[0])))
        checks.extend(_server_observable_concurrency_checks(results, {}))
        return _report("service", "CAPABILITY_FAILED", checks)
    checks.append(_check("real_session_turns", "pass"))
    checks.extend(_server_observable_concurrency_checks(results, {}))

    identity_ok = bool(results) and all(
        event.profile_id == profile_id and event.session_id == sessions[name][0]
        for name, result in results.items()
        for event in result.events
    )
    checks.append(_check("event_identity_attribution", "pass" if identity_ok else "fail"))

    canaries_ok = True
    for name, expected, forbidden in HISTORY_CANARY_ASSERTIONS:
        session_id = sessions[name][0]
        try:
            canaries_ok &= await client.profile_session_matches_markers(
                profile_id,
                session_id,
                expected,
                forbidden,
            )
        except Exception:  # noqa: BLE001 - a missing history assertion is not success
            canaries_ok = False
    checks.append(_check("history_canary_isolation", "pass" if canaries_ok else "fail"))

    tool_names = {
        event.payload.get("tool_name")
        for result in results.values()
        for event in result.events
        if isinstance(event.payload, dict)
    }
    memory_file_ok = {"mnemosyne_remember", "write_file"} <= tool_names
    checks.append(
        _check(
            "memory_file_observations",
            "pass" if memory_file_ok else "blocked",
            "real memory and file canaries were not both observed",
        )
    )
    status = _service_status(checks)
    return _report("service", status, checks)


def run_service(timeout_seconds: float = MAX_TIMEOUT_SECONDS) -> dict[str, Any]:
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be between 0 and 60")
    return asyncio.run(_service_probe(timeout_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded CLD-012 routine evidence")
    parser.add_argument("--mode", choices=("offline", "service"), required=True)
    parser.add_argument("--timeout-seconds", type=float, default=MAX_TIMEOUT_SECONDS)
    args = parser.parse_args()
    try:
        report = run_offline(args.timeout_seconds) if args.mode == "offline" else run_service(args.timeout_seconds)
    except (TypeError, ValueError) as error:
        report = _report(args.mode, "SETUP_BLOCKED", [_check("arguments", "blocked", _safe_reason(error))])
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] in {"CLASS_A_PASSED", "CAPABILITY_PASSED"} else 2 if report["status"] == "SETUP_BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
