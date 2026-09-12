from __future__ import annotations

import asyncio
import sys
import threading
import types
from uuid import uuid4

import pytest

from allies_runtime import quiescence
from allies_runtime.quiescence import (
    CheckedCloseResult,
    ProfileResourceRegistry,
    QuiescenceError,
    QuiescenceProof,
    QuiescenceRequest,
    _bounded_epoch,
    _bounded_identifier,
    _bounded_uuid,
    _call_checked,
    _digest,
    _profile_key,
    checked_close_agent,
    parse_quiescence_proof,
)

PROFILE_KEY = "ally-v1-test"


def request() -> QuiescenceRequest:
    return QuiescenceRequest(
        operation_id=str(uuid4()),
        attempt_id=str(uuid4()),
        lifecycle_epoch=2,
        request_digest="a" * 64,
        machine_generation=3,
        runtime_start_epoch=4,
        hermes_instance_id=str(uuid4()),
    )


def proof_payload(expected: QuiescenceRequest) -> dict[str, object]:
    return {
        **expected.to_dict(),
        "profile_key": PROFILE_KEY,
        "state": "quiesced",
        "safe_error_code": "",
        "active_runs": 0,
        "active_profile_io": 0,
        "open_profile_stores": 0,
        "owned_children": 0,
    }


def test_quiescence_validators_reject_unbounded_or_noncanonical_values():
    with pytest.raises(ValueError):
        _bounded_identifier("", "value")
    with pytest.raises(ValueError):
        _bounded_identifier("x" * 256, "value")
    with pytest.raises(ValueError):
        _bounded_identifier("bad\nvalue", "value")
    with pytest.raises(ValueError):
        _bounded_uuid(str(uuid4()).upper(), "identity")
    with pytest.raises(ValueError):
        _bounded_uuid("not-a-uuid", "identity")
    with pytest.raises(ValueError):
        _bounded_epoch(True, "epoch")
    with pytest.raises(ValueError):
        _bounded_epoch(-1, "epoch")
    with pytest.raises(ValueError):
        _profile_key("../outside")
    with pytest.raises(ValueError):
        _digest("A" * 64)
    with pytest.raises(ValueError):
        _digest("a")
    with pytest.raises(ValueError):
        _digest("z" * 64)


def test_quiescence_proof_serializes_and_reports_incomplete_ownership():
    expected = request()
    parsed = parse_quiescence_proof(proof_payload(expected), expected=expected, profile_key=PROFILE_KEY)
    assert parsed.complete is True
    assert parsed.to_dict()["profile_key"] == PROFILE_KEY
    incomplete = QuiescenceProof(
        **{
            **parsed.to_dict(),
            "state": "quiescing",
            "safe_error_code": "waiting",
            "active_runs": 1,
        }
    )
    assert incomplete.complete is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.pop("version"),
        lambda payload: payload.update(profile_key="ally-v1-other"),
        lambda payload: payload.update(operation_id=str(uuid4())),
        lambda payload: payload.update(state="unknown"),
        lambda payload: payload.update(safe_error_code="bad\ncode"),
        lambda payload: payload.update(active_runs=True),
        lambda payload: payload.update(active_profile_io=-1),
        lambda payload: payload.update(open_profile_stores="0"),
        lambda payload: payload.update(owned_children=1),
    ],
)
def test_quiescence_proof_rejects_identity_state_and_counter_mutations(mutation):
    expected = request()
    payload = proof_payload(expected)
    mutation(payload)
    with pytest.raises(QuiescenceError):
        parse_quiescence_proof(payload, expected=expected, profile_key=PROFILE_KEY)


def test_quiescence_proof_rejects_nonmapping_and_nonzero_quiesced_state():
    expected = request()
    with pytest.raises(QuiescenceError):
        parse_quiescence_proof([], expected=expected, profile_key=PROFILE_KEY)
    payload = proof_payload(expected)
    payload["active_runs"] = 1
    with pytest.raises(QuiescenceError):
        parse_quiescence_proof(payload, expected=expected, profile_key=PROFILE_KEY)
    payload = proof_payload(expected)
    payload["state"] = "repair_required"
    parsed = parse_quiescence_proof(payload, expected=expected, profile_key=PROFILE_KEY)
    assert parsed.complete is False


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"failures": ("hook_failed",)}, "hook_failed"),
        ({"active_processes": 1}, "owned_processes_pending"),
        ({"active_environments": 1}, "owned_environment_pending"),
        ({"active_browsers": 1}, "owned_browser_pending"),
        ({"active_children": 1}, "owned_children_pending"),
        ({"reapers_joined": False}, "owned_reaper_pending"),
    ],
)
def test_checked_close_result_exposes_first_safe_error(kwargs, code):
    result = CheckedCloseResult("task-1", closed=False, **kwargs)
    assert result.safe_error_code == code
    assert CheckedCloseResult("task-1", closed=True).safe_error_code == ""


def test_call_checked_fails_closed_for_exceptions_false_and_async_hooks():
    assert _call_checked(lambda: True) is None
    assert _call_checked(lambda: False) == "cleanup_hook_failed"
    assert _call_checked(lambda: (_ for _ in ()).throw(RuntimeError("boom"))) == "cleanup_hook_failed"

    class Awaitable:
        def __await__(self):
            yield

    assert _call_checked(lambda: Awaitable()) == "cleanup_hook_failed"


def _install_tools(monkeypatch, *, failing=False):
    tools = types.ModuleType("tools")
    tools.__path__ = []
    process = types.ModuleType("tools.process_registry")
    terminal = types.ModuleType("tools.terminal_tool")
    browser = types.ModuleType("tools.browser_tool")
    computer = types.ModuleType("tools.computer_use")

    class Registry:
        def __init__(self):
            self.calls = []

        def kill_all(self, **kwargs):
            self.calls.append(("kill_all", kwargs))
            if failing:
                raise RuntimeError("registry")

        def list_sessions(self, **kwargs):
            self.calls.append(("list_sessions", kwargs))
            if failing:
                raise RuntimeError("registry")
            return []

    registry = Registry()
    process.process_registry = registry
    terminal.get_active_env = lambda _task_id: None
    terminal.cleanup_vm = lambda _task_id: (_ for _ in ()).throw(RuntimeError("terminal")) if failing else True
    browser._active_sessions = {"sibling": {"owner_task_id": "other"}}
    browser.cleanup_browser = lambda _task_id: (_ for _ in ()).throw(RuntimeError("browser")) if failing else None
    computer.release_computer_use_session = lambda _task_id: (_ for _ in ()).throw(RuntimeError("computer")) if failing else None

    monkeypatch.setitem(sys.modules, "tools", tools)
    monkeypatch.setitem(sys.modules, "tools.process_registry", process)
    monkeypatch.setitem(sys.modules, "tools.terminal_tool", terminal)
    monkeypatch.setitem(sys.modules, "tools.browser_tool", browser)
    monkeypatch.setitem(sys.modules, "tools.computer_use", computer)
    return registry


def test_checked_close_agent_runs_existing_hooks_and_checks_owned_resources(monkeypatch):
    registry = _install_tools(monkeypatch)
    calls = []

    class Child:
        def hard_interrupt(self, reason):
            calls.append(("interrupt", reason))

    class Agent:
        def __init__(self):
            self._active_children = [Child()]
            self._session_messages = []

        def shutdown_memory_provider(self, messages):
            calls.append(("memory", messages))

        def close(self):
            calls.append(("close",))
            self._active_children.clear()

    result = checked_close_agent(Agent(), "task-1")
    assert result.closed is True
    assert result.failures == ()
    assert registry.calls[0][0] == "kill_all"
    assert calls == [("interrupt", "profile deletion"), ("memory", []), ("close",)]


def test_checked_close_agent_surfaces_unavailable_hooks(monkeypatch):
    _install_tools(monkeypatch, failing=True)

    class BrokenChildren:
        def __iter__(self):
            raise RuntimeError("children")

    class Agent:
        _active_children = BrokenChildren()

        def shutdown_memory_provider(self, _messages):
            raise RuntimeError("memory")

        def close(self):
            return False

    result = checked_close_agent(Agent(), "task-2", timeout_seconds=0.1)
    assert result.closed is False
    assert "process_registry_unavailable" in result.failures
    assert "terminal_cleanup_failed" in result.failures
    assert "browser_cleanup_failed" in result.failures
    assert "computer_use_cleanup_failed" in result.failures
    assert "children_unreadable" in result.failures


def test_checked_close_agent_counts_remaining_process_environment_and_browser_ownership(monkeypatch):
    registry = _install_tools(monkeypatch)
    registry.list_sessions = lambda **_kwargs: [{"status": "running"}]
    terminal = sys.modules["tools.terminal_tool"]
    environment = types.SimpleNamespace(wait_for_cleanup=lambda **_kwargs: False)
    active_environments = iter((environment, object()))
    terminal.get_active_env = lambda _task_id: next(active_environments)
    terminal.cleanup_vm = lambda _task_id: False
    browser = sys.modules["tools.browser_tool"]
    browser._active_sessions = {"task-3": {"owner_task_id": "task-3"}}

    class Agent:
        def __init__(self):
            self._active_children_lock = threading.RLock()
            self._active_children = [object()]

        def close(self):
            self._active_children.clear()

    result = checked_close_agent(Agent(), "task-3", timeout_seconds=0.1)
    assert result.closed is False
    assert result.active_processes == 1
    assert result.active_environments == 1
    assert result.active_browsers == 1


def test_checked_close_agent_allows_agents_without_optional_hooks(monkeypatch):
    _install_tools(monkeypatch)

    class Agent:
        _active_children = ()

    result = checked_close_agent(Agent(), "task-4")
    assert result.closed is True


def test_checked_close_agent_records_child_interrupt_failure(monkeypatch):
    _install_tools(monkeypatch)

    class Child:
        def interrupt(self, _reason):
            raise RuntimeError("child")

    class Agent:
        def __init__(self):
            self._active_children = [Child()]

        def close(self):
            self._active_children.clear()

    result = checked_close_agent(Agent(), "task-5")
    assert result.closed is False
    assert result.failures == ("cleanup_hook_failed",)


def test_registry_rejects_fenced_admission_and_invalid_active_io():
    registry = ProfileResourceRegistry()
    with pytest.raises(ValueError):
        registry.register(PROFILE_KEY, "task", active_io=True)
    assert registry.is_fenced(PROFILE_KEY) is False
    registry.fence(PROFILE_KEY)
    assert registry.is_fenced(PROFILE_KEY) is True
    with pytest.raises(QuiescenceError):
        registry.admit(PROFILE_KEY)
    registry.release("missing-token")
    assert registry.registrations(PROFILE_KEY) == ()


@pytest.mark.asyncio
async def test_registry_returns_pending_and_repair_states_from_real_workers(monkeypatch):
    registry = ProfileResourceRegistry()
    pending = asyncio.create_task(asyncio.sleep(1))
    token = registry.register(PROFILE_KEY, "pending-task", future=pending)
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=0.001)
    assert state == "quiescing"
    assert "executor_pending" in failures
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    registry.release(token)

    class BadAgent:
        def interrupt(self, _reason):
            raise RuntimeError("interrupt")

    monkeypatch.setattr(
        quiescence,
        "checked_close_agent",
        lambda *_args, **_kwargs: CheckedCloseResult("bad-task", closed=False, active_processes=1),
    )
    registry = ProfileResourceRegistry()
    registry.register(PROFILE_KEY, "bad-task", agent=BadAgent())
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=1)
    assert state == "repair_required"
    assert "interrupt_failed" in failures
    assert "owned_processes_pending" in failures
    assert "resource_registration_pending" in failures


@pytest.mark.asyncio
async def test_registry_awaits_async_interrupt_and_close_hooks(monkeypatch):
    registry = ProfileResourceRegistry()
    events = []

    class Agent:
        async def interrupt(self, _reason):
            events.append("interrupt")

    async def close():
        events.append("close")
        return False

    task = asyncio.create_task(asyncio.sleep(0))
    await task
    registry.register(PROFILE_KEY, "async-task", future=task, agent=Agent(), close=close)
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=1)
    assert state == "repair_required"
    assert failures == ("cleanup_failed", "resource_registration_pending")
    assert events == ["interrupt", "close"]


@pytest.mark.asyncio
async def test_registry_rejects_nonpositive_timeout_and_unowned_registration(monkeypatch):
    registry = ProfileResourceRegistry()
    with pytest.raises(ValueError):
        await registry.quiesce(PROFILE_KEY, timeout_seconds=0)

    registry.register(PROFILE_KEY, "unowned-task")
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=1)
    assert state == "repair_required"
    assert failures == ("resource_registration_pending",)


@pytest.mark.asyncio
async def test_registry_handles_cancelled_executor_and_checked_close_success(monkeypatch):
    class CancelledFuture:
        def done(self):
            return False

        def __await__(self):
            async def cancelled():
                raise asyncio.CancelledError

            return cancelled().__await__()

    registry = ProfileResourceRegistry()
    registry.register(PROFILE_KEY, "cancelled-task", future=CancelledFuture())
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=1)
    assert state == "quiescing"
    assert failures == ("executor_pending",)

    monkeypatch.setattr(
        quiescence,
        "checked_close_agent",
        lambda *_args, **_kwargs: CheckedCloseResult("closed-task", closed=True),
    )
    registry = ProfileResourceRegistry()
    registry.register(PROFILE_KEY, "closed-task", agent=object())
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=1)
    assert state == "repair_required"
    assert failures == ("resource_registration_pending",)


@pytest.mark.asyncio
async def test_registry_reports_exception_from_cleanup_hook():
    def broken_close():
        raise RuntimeError("close")

    registry = ProfileResourceRegistry()
    registry.register(PROFILE_KEY, "broken-task", close=broken_close)
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=1)
    assert state == "repair_required"
    assert failures == ("cleanup_failed", "resource_registration_pending")


@pytest.mark.asyncio
async def test_registry_marks_zero_time_remaining_as_pending(monkeypatch):
    registry = ProfileResourceRegistry()
    future = asyncio.Future()
    token = registry.register(PROFILE_KEY, "slow-task", future=future)
    values = iter((0.0, 1.0))
    monkeypatch.setattr(
        quiescence,
        "time",
        types.SimpleNamespace(monotonic=lambda: next(values)),
    )
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=0.5)
    assert state == "quiescing"
    assert failures == ("executor_pending",)
    registry.release(token)
    future.cancel()


@pytest.mark.asyncio
async def test_registry_records_executor_and_close_failures():
    async def failed_worker():
        raise RuntimeError("executor")

    registry = ProfileResourceRegistry()
    task = asyncio.create_task(failed_worker())
    registry.register(PROFILE_KEY, "failed-task", future=task, close=lambda: False)
    state, failures = await registry.quiesce(PROFILE_KEY, timeout_seconds=1)
    assert state == "repair_required"
    assert "executor_failed" in failures
    assert "cleanup_failed" in failures
    assert "resource_registration_pending" in failures
