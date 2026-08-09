"""Provider/lifecycle boundary used by the bounded runtime smoke.

The runtime package deliberately does not import Foundry's Django code.  This
module describes the narrow adapter contract that a backend-owned integration
implements with ``FlyProvider`` and ``WorkspaceLifecycle``.  Fake mode uses
the same contract, while live mode requires an explicitly supplied adapter and
bootstrap capability before it can provision anything.
"""

from __future__ import annotations

import inspect
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .evidence import EvidenceCheck, VolumeVisibility, check

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def validate_run_id(value: str) -> str:
    """Keep caller-supplied run IDs safe for namespaced resources/evidence."""

    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError("run_id must be a safe identifier")
    return value


class SmokeIntegrationError(RuntimeError):
    """A sanitized integration failure that is safe to put in evidence."""

    code = "integration_failed"


class SmokeCapabilityError(SmokeIntegrationError):
    code = "capability_unavailable"


class SmokeCleanupError(SmokeIntegrationError):
    code = "cleanup_incomplete"


@dataclass(frozen=True, slots=True)
class IntegrationSnapshot:
    """Safe result of a provision/inspection operation.

    Resource identifiers are accepted only after validation and are included
    in evidence as identifiers, never as provider payloads or response bodies.
    """

    resource_ids: Mapping[str, str] = field(default_factory=dict)
    checks: tuple[EvidenceCheck, ...] = ()
    volume_visibility: VolumeVisibility = VolumeVisibility.ABSENT

    def __post_init__(self) -> None:
        safe_ids: dict[str, str] = {}
        for kind, value in self.resource_ids.items():
            if not isinstance(kind, str) or not kind:
                raise ValueError("integration resource kind must be a non-empty string")
            if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
                raise ValueError("integration resource identifiers must be safe")
            safe_ids[kind] = value
        object.__setattr__(self, "resource_ids", safe_ids)
        object.__setattr__(self, "checks", tuple(self.checks))


@dataclass(frozen=True, slots=True)
class CleanupResult:
    status: str
    checks: tuple[EvidenceCheck, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"complete", "incomplete"}:
            raise ValueError("cleanup status must be complete or incomplete")
        object.__setattr__(self, "checks", tuple(self.checks))


class SmokeIntegration(Protocol):
    """Minimal adapter implemented by the backend/provider integration."""

    def preflight(self) -> Any: ...

    def provision(
        self, run_id: str
    ) -> IntegrationSnapshot | Awaitable[IntegrationSnapshot]: ...

    def cleanup(
        self, ledger: OwnedResourceLedger, *, deadline: float
    ) -> CleanupResult | Awaitable[CleanupResult]: ...


class ProfileBootstrap(Protocol):
    """Secure, ephemeral profile/key bootstrap for the live proof.

    ``install`` is the final activation gate. It receives a bounded
    ``timeout_seconds`` budget and returns exactly ``True`` only after the
    temporary Hermes profiles/keys are installed and authenticated readiness
    succeeds, before Foundry writes the durable Workspace binding.
    """

    def available(self) -> bool | Awaitable[bool]: ...

    def prepare(self, run_id: str) -> Any: ...

    def install(self, run_id: str, *, timeout_seconds: float) -> bool: ...

    def cleanup(self) -> Any: ...


class OwnedResourceLedger:
    """Bounded ledger for resources created by one smoke run.

    The ledger never discovers or adopts arbitrary provider resources.  An
    adapter records only deterministic IDs returned by its own provision call,
    then cleans those IDs in machine -> volume -> app order.  A recorded 404
    is treated as an idempotent success by the adapter's cleaner.
    """

    def __init__(self) -> None:
        self._resources: dict[str, str] = {}

    @property
    def resources(self) -> Mapping[str, str]:
        return dict(self._resources)

    def record(self, kind: str, identifier: str) -> None:
        if not isinstance(kind, str) or not kind:
            raise ValueError("resource kind must be a non-empty string")
        if not isinstance(identifier, str) or not _SAFE_ID.fullmatch(identifier):
            raise ValueError("resource identifier is not safe")
        self._resources[kind] = identifier

    def record_snapshot(self, snapshot: IntegrationSnapshot) -> None:
        for kind, identifier in snapshot.resource_ids.items():
            self.record(kind, identifier)

    async def cleanup(
        self,
        cleaners: Mapping[str, Callable[[str], Any]],
        *,
        timeout_seconds: float = 30.0,
    ) -> CleanupResult:
        if timeout_seconds <= 0:
            raise ValueError("cleanup timeout must be positive")
        deadline = time.monotonic() + timeout_seconds
        checks: list[EvidenceCheck] = []
        complete = True
        for kind in ("machine", "volume", "app"):
            identifier = self._resources.get(kind)
            if identifier is None:
                continue
            cleaner = cleaners.get(kind)
            if cleaner is None:
                complete = False
                checks.append(check(f"cleanup_{kind}", "fail", "cleaner unavailable"))
                continue
            if time.monotonic() >= deadline:
                complete = False
                checks.append(check(f"cleanup_{kind}", "fail", "deadline exceeded"))
                continue
            try:
                result = cleaner(identifier)
                if inspect.isawaitable(result):
                    remaining = max(0.001, deadline - time.monotonic())
                    await _await_bounded(result, remaining)
            except Exception as exc:  # noqa: BLE001 - classify without provider text
                if getattr(exc, "code", None) == "provider_not_found":
                    checks.append(check(f"cleanup_{kind}", "pass", "already absent"))
                    continue
                complete = False
                checks.append(
                    check(f"cleanup_{kind}", "fail", "provider cleanup failed")
                )
                continue
            checks.append(check(f"cleanup_{kind}", "pass"))
        return CleanupResult("complete" if complete else "incomplete", tuple(checks))


async def _await_bounded(value: Awaitable[Any], timeout: float) -> Any:
    import asyncio

    return await asyncio.wait_for(value, timeout=timeout)


class FakeSmokeIntegration:
    """Deterministic adapter used by local and CI smoke runs."""

    def __init__(self) -> None:
        self.preflight_calls = 0
        self.provision_calls = 0
        self.cleanup_calls = 0

    def preflight(self) -> None:
        self.preflight_calls += 1

    def provision(self, run_id: str) -> IntegrationSnapshot:
        self.provision_calls += 1
        return IntegrationSnapshot(
            resource_ids={"machine": f"fake-machine-{run_id}"},
            checks=(
                check("topology_capability", "pass"),
                check("machine_containers", "pass"),
                check("container_health", "pass"),
                check("process_failure_visibility", "pass"),
                check("volume_marker_continuity", "pass"),
            ),
            volume_visibility=VolumeVisibility.ABSENT,
        )

    def cleanup(self, ledger: OwnedResourceLedger, *, deadline: float) -> CleanupResult:
        self.cleanup_calls += 1
        return CleanupResult(
            "complete",
            (check("cleanup_owned_resources", "pass"),),
        )


async def invoke(value: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a sync or async adapter method without leaking its exceptions."""

    result = value(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = [
    "CleanupResult",
    "FakeSmokeIntegration",
    "IntegrationSnapshot",
    "OwnedResourceLedger",
    "ProfileBootstrap",
    "SmokeCapabilityError",
    "SmokeCleanupError",
    "SmokeIntegration",
    "SmokeIntegrationError",
    "invoke",
    "validate_run_id",
]
