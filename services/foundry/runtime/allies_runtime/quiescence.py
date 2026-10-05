"""Deletion-only runtime quiescence and checked resource closure."""

from __future__ import annotations

import asyncio
import inspect
import re
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

_PROFILE_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class QuiescenceError(RuntimeError):
    """The runtime cannot prove that one profile is closed."""

    code = "quiescence_failed"


class QuiescencePending(QuiescenceError):
    code = "quiescence_pending"


class QuiescenceRepairRequired(QuiescenceError):
    code = "quiescence_repair_required"


def _bounded_identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise ValueError(f"{name} must be a bounded non-empty string")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value


def _bounded_uuid(value: Any, name: str) -> str:
    value = _bounded_identifier(value, name)
    try:
        parsed = str(UUID(value))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a UUID") from None
    if value != value.lower() or parsed != value:
        raise ValueError(f"{name} must be a canonical UUID")
    return parsed


def _bounded_epoch(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _profile_key(value: Any) -> str:
    if not isinstance(value, str) or _PROFILE_KEY.fullmatch(value) is None:
        raise ValueError("profile_key must be a canonical Hermes profile key")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("request_digest must be a SHA-256 hex digest")
    if value != value.lower():
        raise ValueError("request_digest must be a lowercase SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError:
        raise ValueError("request_digest must be a SHA-256 hex digest") from None
    return value


@dataclass(frozen=True, slots=True)
class QuiescenceRequest:
    """Identity tuple sent to the listener-level Hermes control route."""

    operation_id: str
    attempt_id: str
    lifecycle_epoch: int
    request_digest: str
    machine_generation: int
    runtime_start_epoch: int
    hermes_instance_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _bounded_uuid(self.operation_id, "operation_id"))
        object.__setattr__(self, "attempt_id", _bounded_uuid(self.attempt_id, "attempt_id"))
        object.__setattr__(
            self,
            "lifecycle_epoch",
            _bounded_epoch(self.lifecycle_epoch, "lifecycle_epoch"),
        )
        object.__setattr__(self, "request_digest", _digest(self.request_digest))
        object.__setattr__(
            self,
            "machine_generation",
            self.machine_generation,
        )
        if (
            isinstance(self.machine_generation, bool)
            or not isinstance(self.machine_generation, int)
            or self.machine_generation <= 0
        ):
            raise ValueError("machine_generation must be a positive integer")
        object.__setattr__(
            self,
            "runtime_start_epoch",
            _bounded_epoch(self.runtime_start_epoch, "runtime_start_epoch"),
        )
        object.__setattr__(
            self,
            "hermes_instance_id",
            _bounded_uuid(self.hermes_instance_id, "hermes_instance_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "lifecycle_epoch": self.lifecycle_epoch,
            "request_digest": self.request_digest,
            "machine_generation": self.machine_generation,
            "runtime_start_epoch": self.runtime_start_epoch,
            "hermes_instance_id": self.hermes_instance_id,
        }


@dataclass(frozen=True, slots=True)
class QuiescenceProof:
    """Bounded, content-free closure evidence returned by Hermes."""

    profile_key: str
    operation_id: str
    attempt_id: str
    lifecycle_epoch: int
    request_digest: str
    machine_generation: int
    runtime_start_epoch: int
    hermes_instance_id: str
    state: str
    safe_error_code: str
    active_runs: int = 0
    active_profile_io: int = 0
    open_profile_stores: int = 0
    owned_children: int = 0

    @property
    def complete(self) -> bool:
        return (
            self.state == "quiesced"
            and self.safe_error_code == ""
            and self.active_runs == 0
            and self.active_profile_io == 0
            and self.open_profile_stores == 0
            and self.owned_children == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "lifecycle_epoch": self.lifecycle_epoch,
            "request_digest": self.request_digest,
            "machine_generation": self.machine_generation,
            "runtime_start_epoch": self.runtime_start_epoch,
            "hermes_instance_id": self.hermes_instance_id,
            "state": self.state,
            "safe_error_code": self.safe_error_code,
            "active_runs": self.active_runs,
            "active_profile_io": self.active_profile_io,
            "open_profile_stores": self.open_profile_stores,
            "owned_children": self.owned_children,
        }


def _counter(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QuiescenceError(f"Hermes quiescence counter was malformed: {name}")
    return value


def parse_quiescence_proof(
    value: Mapping[str, Any], *, expected: QuiescenceRequest, profile_key: str
) -> QuiescenceProof:
    """Parse a strict Hermes response and bind every identity field."""

    if not isinstance(value, Mapping):
        raise QuiescenceError("Hermes quiescence response was malformed")
    allowed_fields = {
        "version",
        "profile_key",
        "operation_id",
        "attempt_id",
        "lifecycle_epoch",
        "request_digest",
        "machine_generation",
        "runtime_start_epoch",
        "hermes_instance_id",
        "state",
        "safe_error_code",
        "active_runs",
        "active_profile_io",
        "open_profile_stores",
        "owned_children",
    }
    try:
        if set(value) - allowed_fields or value.get("version") != 1:
            raise ValueError
        if _bounded_identifier(value.get("profile_key"), "profile_key") != profile_key:
            raise ValueError
        for name in (
            "operation_id",
            "attempt_id",
            "lifecycle_epoch",
            "request_digest",
            "machine_generation",
            "runtime_start_epoch",
            "hermes_instance_id",
        ):
            if value.get(name) != getattr(expected, name):
                raise ValueError
        state = value.get("state")
        if state not in {"quiescing", "quiesced", "repair_required"}:
            raise ValueError
        safe_error_code = value.get("safe_error_code")
        if (
            not isinstance(safe_error_code, str)
            or len(safe_error_code) > 128
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in safe_error_code
            )
        ):
            raise ValueError
        proof = QuiescenceProof(
            profile_key=profile_key,
            operation_id=expected.operation_id,
            attempt_id=expected.attempt_id,
            lifecycle_epoch=expected.lifecycle_epoch,
            request_digest=expected.request_digest,
            machine_generation=expected.machine_generation,
            runtime_start_epoch=expected.runtime_start_epoch,
            hermes_instance_id=expected.hermes_instance_id,
            state=state,
            safe_error_code=safe_error_code,
            active_runs=_counter(value["active_runs"], "active_runs"),
            active_profile_io=_counter(value["active_profile_io"], "active_profile_io"),
            open_profile_stores=_counter(value["open_profile_stores"], "open_profile_stores"),
            owned_children=_counter(value["owned_children"], "owned_children"),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise QuiescenceError("Hermes quiescence response was malformed") from None
    if proof.state == "quiesced" and not proof.complete:
        raise QuiescenceError("Hermes claimed quiescence with non-zero ownership")
    return proof


@dataclass(slots=True)
class CheckedCloseResult:
    """Evidence from each deletion-only cleanup hook."""

    task_id: str
    closed: bool
    failures: tuple[str, ...] = ()
    active_processes: int = 0
    active_environments: int = 0
    active_browsers: int = 0
    active_children: int = 0
    reapers_joined: bool = True

    @property
    def safe_error_code(self) -> str:
        if self.failures:
            return self.failures[0]
        if self.active_processes:
            return "owned_processes_pending"
        if self.active_environments:
            return "owned_environment_pending"
        if self.active_browsers:
            return "owned_browser_pending"
        if self.active_children:
            return "owned_children_pending"
        if not self.reapers_joined:
            return "owned_reaper_pending"
        return ""


def _call_checked(call: Callable[..., Any], *args: Any, **kwargs: Any) -> str | None:
    try:
        value = call(*args, **kwargs)
        if inspect.isawaitable(value):
            raise RuntimeError("async cleanup hook used from synchronous closure")
    except Exception:  # noqa: BLE001 - cleanup hooks must fail closed
        return "cleanup_hook_failed"
    if value is False:
        return "cleanup_hook_failed"
    return None


def checked_close_agent(
    agent: Any,
    task_id: str,
    *,
    timeout_seconds: float = 30.0,
) -> CheckedCloseResult:
    """Run the existing Hermes resource hooks and verify ownership is gone.

    This deliberately calls the individual hooks before ``close`` because the
    upstream method is best effort and suppresses exceptions.  The final
    ``close`` remains part of the lifecycle so its additional clients and
    session state are released as well.
    """

    task_id = _bounded_identifier(task_id, "task_id")
    failures: list[str] = []
    children: list[Any] = []
    child_lock = getattr(agent, "_active_children_lock", None)
    try:
        if child_lock is not None:
            with child_lock:
                children = list(getattr(agent, "_active_children", ()) or ())
        else:
            children = list(getattr(agent, "_active_children", ()) or ())
    except Exception:  # noqa: BLE001 - unreadable ownership is unsafe
        failures.append("children_unreadable")

    for child in children:
        interrupt = getattr(child, "hard_interrupt", None) or getattr(child, "interrupt", None)
        if callable(interrupt):
            failure = _call_checked(interrupt, "profile deletion")
            if failure:
                failures.append(failure)

    shutdown_provider = getattr(agent, "shutdown_memory_provider", None)
    if callable(shutdown_provider):
        failure = _call_checked(shutdown_provider, getattr(agent, "_session_messages", None))
        if failure:
            failures.append("memory_provider_shutdown_failed")

    close = getattr(agent, "close", None)
    if callable(close):
        failure = _call_checked(close)
        if failure:
            failures.append(failure)

    try:
        from tools.process_registry import process_registry

        process_registry.kill_all(task_id=task_id, source="profile_deletion")
        processes = process_registry.list_sessions(task_id=task_id)
        active_processes = sum(1 for item in processes if item.get("status") == "running")
    except Exception:  # noqa: BLE001 - unavailable registry is unsafe
        active_processes = 0
        failures.append("process_registry_unavailable")

    active_environments = 0
    try:
        from tools.terminal_tool import cleanup_vm, get_active_env

        env = get_active_env(task_id)
        cleanup_result = cleanup_vm(task_id)
        if cleanup_result is False:
            active_environments = 1
        wait = getattr(env, "wait_for_cleanup", None)
        if callable(wait) and wait(timeout=min(timeout_seconds, 30.0)) is False:
            active_environments = 1
        active_environments = max(active_environments, int(get_active_env(task_id) is not None))
    except Exception:  # noqa: BLE001 - terminal cleanup is best effort but checked
        failures.append("terminal_cleanup_failed")

    active_browsers = 0
    try:
        from tools.browser_tool import _active_sessions, cleanup_browser

        cleanup_browser(task_id)
        active_browsers = sum(
            1
            for key, info in list(_active_sessions.items())
            if key == task_id
            or key == f"{task_id}::local"
            or info.get("owner_task_id") == task_id
        )
    except Exception:  # noqa: BLE001 - browser cleanup is best effort but checked
        failures.append("browser_cleanup_failed")

    try:
        from tools.computer_use import release_computer_use_session

        release_computer_use_session(task_id)
    except Exception:  # noqa: BLE001 - release failures remain repair evidence
        failures.append("computer_use_cleanup_failed")

    active_children = 0
    try:
        if child_lock is not None:
            with child_lock:
                active_children = len(getattr(agent, "_active_children", ()) or ())
        else:
            active_children = len(getattr(agent, "_active_children", ()) or ())
    except Exception:  # noqa: BLE001 - unreadable ownership is unsafe
        failures.append("children_unreadable")

    return CheckedCloseResult(
        task_id=task_id,
        closed=not failures
        and not active_processes
        and not active_environments
        and not active_browsers
        and not active_children,
        failures=tuple(dict.fromkeys(failures)),
        active_processes=active_processes,
        active_environments=active_environments,
        active_browsers=active_browsers,
        active_children=active_children,
    )


@dataclass(slots=True)
class _Registration:
    token: str
    profile_key: str
    task_id: str
    future: Any = None
    agent: Any = None
    close: Callable[[], Any] | None = None
    active_io: int = 0


class ProfileResourceRegistry:
    """Profile-scoped admission and ownership registry for runtime workers."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, _Registration]] = defaultdict(dict)
        self._fenced: set[str] = set()
        self._counter = 0

    def is_fenced(self, profile_key: str) -> bool:
        _profile_key(profile_key)
        with self._lock:
            return profile_key in self._fenced

    def admit(self, profile_key: str) -> None:
        _profile_key(profile_key)
        with self._lock:
            if profile_key in self._fenced:
                raise QuiescenceError("profile is fenced for deletion")

    def fence(self, profile_key: str) -> None:
        """Persist the admission fence without waiting on an executor."""

        _profile_key(profile_key)
        with self._lock:
            self._fenced.add(profile_key)

    def register(
        self,
        profile_key: str,
        task_id: str,
        *,
        future: Any = None,
        agent: Any = None,
        close: Callable[[], Any] | None = None,
        active_io: int = 0,
    ) -> str:
        _profile_key(profile_key)
        self.admit(profile_key)
        if not isinstance(active_io, int) or isinstance(active_io, bool) or active_io < 0:
            raise ValueError("active_io must be a non-negative integer")
        task_id = _bounded_identifier(task_id, "task_id")
        with self._lock:
            self._counter += 1
            token = f"resource-{self._counter}"
            self._entries[profile_key][token] = _Registration(
                token, profile_key, task_id, future, agent, close, active_io
            )
            return token

    def release(self, token: str) -> None:
        with self._lock:
            for profile_entries in self._entries.values():
                if profile_entries.pop(token, None) is not None:
                    break

    def registrations(self, profile_key: str) -> tuple[_Registration, ...]:
        with self._lock:
            return tuple(self._entries.get(profile_key, {}).values())

    async def quiesce(
        self,
        profile_key: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> tuple[str, tuple[str, ...]]:
        """Fence, interrupt, await real workers, and run checked close hooks."""

        if timeout_seconds <= 0:
            raise ValueError("quiescence timeout must be positive")
        _profile_key(profile_key)
        self.fence(profile_key)
        with self._lock:
            entries = tuple(self._entries.get(profile_key, {}).values())
        failures: list[str] = []
        for entry in entries:
            interrupt = getattr(entry.agent, "hard_interrupt", None) or getattr(
                entry.agent, "interrupt", None
            )
            if callable(interrupt):
                try:
                    result = interrupt("profile deletion")
                    if inspect.isawaitable(result):
                        await result
                except Exception:  # noqa: BLE001 - interrupt failures stay visible
                    failures.append("interrupt_failed")

        deadline = time.monotonic() + timeout_seconds
        pending = []
        for entry in entries:
            future = entry.future
            if future is None or not hasattr(future, "done"):
                continue
            if future.done():
                continue
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0:
                pending.append(entry)
                continue
            try:
                await asyncio.wait_for(asyncio.shield(future), remaining)
            except TimeoutError:
                pending.append(entry)
            except asyncio.CancelledError:
                pending.append(entry)
            except Exception:  # noqa: BLE001 - executor failures stay pending
                failures.append("executor_failed")

        if pending:
            return "quiescing", tuple(dict.fromkeys(failures + ["executor_pending"]))

        for entry in entries:
            try:
                if entry.close is not None:
                    result = entry.close()
                    if inspect.isawaitable(result):
                        result = await result
                    if result is False:
                        failures.append("cleanup_failed")
                elif entry.agent is not None:
                    checked = await asyncio.to_thread(
                        checked_close_agent, entry.agent, entry.task_id
                    )
                    if not checked.closed:
                        failures.append(checked.safe_error_code or "cleanup_failed")
            except Exception:  # noqa: BLE001 - cleanup failures stay repair-required
                failures.append("cleanup_failed")

        with self._lock:
            remaining_entries = tuple(self._entries.get(profile_key, {}).values())
        if remaining_entries:
            failures.append("resource_registration_pending")
        return ("repair_required" if failures else "quiesced"), tuple(
            dict.fromkeys(failures)
        )


__all__ = [
    "CheckedCloseResult",
    "ProfileResourceRegistry",
    "QuiescenceError",
    "QuiescencePending",
    "QuiescenceProof",
    "QuiescenceRepairRequired",
    "QuiescenceRequest",
    "checked_close_agent",
    "parse_quiescence_proof",
]
