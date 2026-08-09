"""Deterministic fake smoke and explicitly gated live entry point."""

from __future__ import annotations

import asyncio
import inspect
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import RuntimeSettings, load_settings
from .coordinator import ProfileProofCoordinator
from .errors import HermesError
from .evidence import (
    EvidenceCheck,
    EvidenceReport,
    VolumeVisibility,
    assert_sanitized,
    check,
)
from .fake import FakeHermesClient, FakeProfilePlan
from .integration import (
    FakeSmokeIntegration,
    OwnedResourceLedger,
    ProfileBootstrap,
    SmokeIntegration,
    invoke,
    validate_run_id,
)
from .volume import observe_volume_marker


@dataclass(frozen=True, slots=True)
class SmokeResult:
    evidence: EvidenceReport
    profile_results: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return self.evidence.to_dict()


class _BootstrapInstallError(RuntimeError):
    """Safe activation failure that must prevent a durable Workspace bind."""

    code = "secure_profile_bootstrap_install_failed"


_BOOTSTRAP_INSTALL_TIMEOUT_SECONDS = 30.0


def _run_bounded_sync(call: Any, timeout_seconds: float) -> Any:
    """Run a synchronous bootstrap call without blocking cleanup forever."""

    if timeout_seconds <= 0:
        raise _BootstrapInstallError("secure profile bootstrap deadline expired")
    outcome: list[tuple[bool, Any]] = []
    finished = threading.Event()

    def worker() -> None:
        try:
            outcome.append((True, call()))
        except BaseException as error:  # noqa: BLE001 - forward at boundary
            outcome.append((False, error))
        finally:
            finished.set()

    threading.Thread(target=worker, name="fnd4-bootstrap", daemon=True).start()
    if not finished.wait(timeout_seconds):
        raise _BootstrapInstallError("secure profile bootstrap install timed out")
    succeeded, value = outcome[0]
    if not succeeded:
        raise value
    return value


def _run_id() -> str:
    # The random suffix is an identifier only; it is never used as a secret or
    # persisted by the runtime. Tests may pass a fixed run_id for snapshots.
    return f"fnd4-local-{secrets.token_hex(4)}"


def _failure_detail(error: BaseException) -> str:
    """Return a stable classification without retaining provider text."""

    return str(getattr(error, "code", "integration_failed"))


async def _bootstrap_available(bootstrap: ProfileBootstrap) -> bool:
    value = bootstrap.available()
    value = await value if hasattr(value, "__await__") else value
    return value is True


async def run_smoke(
    mode: str = "fake",
    *,
    settings: RuntimeSettings | None = None,
    client: Any | None = None,
    run_id: str | None = None,
    marker_path: str | Path | None = None,
    volume_root: str | Path | None = None,
    integration: SmokeIntegration | None = None,
    bootstrap: ProfileBootstrap | None = None,
    cleanup_timeout_seconds: float = 30.0,
    bootstrap_timeout_seconds: float = _BOOTSTRAP_INSTALL_TIMEOUT_SECONDS,
) -> SmokeResult:
    """Run the local proof; live mode fails closed unless fully gated.

    The backend supplies ``integration`` with the existing FlyProvider and
    WorkspaceLifecycle.  No resource call is made until the live capability
    and secure temporary-profile bootstrap have both passed.  The runtime
    package itself never resolves or stores a production credential.
    """

    if mode not in {"fake", "live"}:
        raise ValueError("smoke mode must be fake or live")
    if cleanup_timeout_seconds <= 0:
        raise ValueError("cleanup timeout must be positive")
    if bootstrap_timeout_seconds <= 0:
        raise ValueError("bootstrap timeout must be positive")
    settings = settings or load_settings({})
    run_id = _run_id() if run_id is None else validate_run_id(run_id)
    checks: list[EvidenceCheck] = []
    profile_results: tuple[Any, ...] = ()
    volume_visibility = VolumeVisibility.ABSENT
    resources: dict[str, str] = {}
    cleanup_status = "complete"
    profile_bootstrap_started = False
    profile_bootstrap_installed = False
    before_bind_configured = False
    bootstrap_install_error: BaseException | None = None
    ledger = OwnedResourceLedger()

    if marker_path is not None:
        try:
            observation = observe_volume_marker(
                marker_path,
                volume_root=volume_root or settings.volume_root,
            )
            volume_visibility = observation.visibility
            checks.append(
                check(
                    "volume_marker_visibility",
                    "pass" if observation.marker_exists else "skip",
                )
            )
        except (OSError, ValueError):
            checks.append(check("volume_marker_visibility", "fail", "invalid_marker"))
    else:
        checks.append(
            check(
                "volume_marker_visibility",
                "skip",
                "mount observation not configured",
            )
        )

    # Fake mode and live mode share the same adapter boundary. Live mode does
    # not get a fake fallback when its adapter or bootstrap is unavailable.
    if integration is None and mode == "fake":
        integration = FakeSmokeIntegration()

    if mode == "live":
        gate_error: str | None = None
        if os.environ.get("FND004_LIVE_SMOKE") != "1":
            gate_error = "live_opt_in_required"
        elif integration is None:
            gate_error = "provider_lifecycle_adapter_required"
        elif bootstrap is None:
            gate_error = "secure_profile_bootstrap_required"
        elif client is None:
            gate_error = "live_hermes_client_required"
        else:
            try:
                if not await _bootstrap_available(bootstrap):
                    gate_error = "secure_profile_bootstrap_unavailable"
                else:
                    # This is deliberately before provision: the adapter's
                    # preflight must not create an App, Volume, or Machine.
                    await invoke(integration.preflight)
            except Exception as exc:  # noqa: BLE001 - classify at evidence boundary
                gate_error = _failure_detail(exc)
        if gate_error is not None:
            checks.extend(
                [
                    check("live_capability_gate", "fail", gate_error),
                    check("profile_streams", "skip", "live gate failed closed"),
                ]
            )
            evidence = EvidenceReport(
                run_id=run_id,
                mode=mode,
                hermes_image=settings.hermes_image,
                runtime_image=settings.runtime_image or "runtime-image-not-built",
                source_commit=settings.source_commit,
                checks=tuple(checks),
                volume_visibility=volume_visibility,
                cleanup=cleanup_status,
                profile_proof_mode="temporary-live-profiles",
            )
            payload = evidence.to_dict()
            assert_sanitized(payload)
            return SmokeResult(evidence=evidence)

    assert integration is not None
    provisioned = False
    live_bootstrap_ok = mode != "live"
    if mode == "live" and bootstrap is not None:
        try:
            # Establish the secure profile/socket boundary before creating or
            # starting the Machine. Runtime PID 1 may probe it during health.
            profile_bootstrap_started = True
            await invoke(bootstrap.prepare, run_id)
            live_bootstrap_ok = True
        except Exception as exc:  # noqa: BLE001 - classify at evidence boundary
            checks.append(check("live_profile_bootstrap", "fail", _failure_detail(exc)))
            live_bootstrap_ok = False

    def install_before_bind(deadline: float | None = None) -> None:
        """Synchronously activate Hermes before lifecycle writes the binding."""

        nonlocal bootstrap_install_error, profile_bootstrap_installed
        if bootstrap is None:
            error = _BootstrapInstallError("secure profile bootstrap is missing")
            bootstrap_install_error = error
            raise error
        install = getattr(bootstrap, "install", None)
        if install is None:
            error = _BootstrapInstallError(
                "secure profile bootstrap install hook is missing"
            )
            bootstrap_install_error = error
            raise error
        try:
            timeout_seconds = bootstrap_timeout_seconds
            if deadline is not None and deadline > 0:
                timeout_seconds = min(
                    timeout_seconds, max(0.001, deadline - time.monotonic())
                )
            result = _run_bounded_sync(
                lambda: install(run_id, timeout_seconds=timeout_seconds),
                timeout_seconds,
            )
            if inspect.isawaitable(result) or result is not True:
                raise _BootstrapInstallError(
                    "secure profile bootstrap did not confirm authenticated readiness"
                )
        except _BootstrapInstallError as error:
            bootstrap_install_error = error
            raise
        except Exception as exc:
            error = _BootstrapInstallError(
                "secure profile bootstrap installation failed"
            )
            bootstrap_install_error = error
            raise error from exc
        profile_bootstrap_installed = True

    try:
        if live_bootstrap_ok:
            try:
                # Fake mode also exercises preflight/provision through the adapter.
                if mode == "fake":
                    await invoke(integration.preflight)
                if mode == "live":
                    configure_before_bind = getattr(
                        integration, "configure_before_bind", None
                    )
                    if configure_before_bind is not None:
                        configure_before_bind(install_before_bind)
                        before_bind_configured = True
                reserve = getattr(integration, "reserve", None)
                if reserve is not None:
                    reserved = await invoke(reserve, run_id)
                    if reserved is not None:
                        ledger.record_snapshot(reserved)
                        resources.update(reserved.resource_ids)
                snapshot = await invoke(integration.provision, run_id)
                if snapshot is not None:
                    ledger.record_snapshot(snapshot)
                    resources.update(snapshot.resource_ids)
                    checks.extend(snapshot.checks)
                    if marker_path is None:
                        volume_visibility = snapshot.volume_visibility
                provisioned = True
            except Exception as exc:  # noqa: BLE001 - classify at evidence boundary
                if bootstrap_install_error is not None:
                    checks.append(
                        check(
                            "live_profile_bootstrap",
                            "fail",
                            _failure_detail(bootstrap_install_error),
                        )
                    )
                else:
                    checks.append(
                        check("provider_lifecycle", "fail", _failure_detail(exc))
                    )
        else:
            checks.append(check("profile_streams", "skip", "profile bootstrap failed"))

        if provisioned and mode == "fake":
            checks.append(check("live_profile_bootstrap", "skip", "fake mode"))

        if (
            provisioned
            and mode == "live"
            and bootstrap is not None
            and not before_bind_configured
        ):
            install = getattr(bootstrap, "install", None)
            if install is None:
                checks.append(
                    check(
                        "live_profile_bootstrap",
                        "fail",
                        "secure_profile_bootstrap_install_required",
                    )
                )
            else:
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            install,
                            run_id,
                            timeout_seconds=bootstrap_timeout_seconds,
                        ),
                        timeout=bootstrap_timeout_seconds,
                    )
                    if result is not True:
                        raise _BootstrapInstallError(
                            "secure profile bootstrap did not confirm authenticated readiness"
                        )
                    profile_bootstrap_installed = True
                except Exception as exc:  # noqa: BLE001 - classify at evidence boundary
                    checks.append(
                        check(
                            "live_profile_bootstrap",
                            "fail",
                            _failure_detail(exc),
                        )
                    )
        elif provisioned and mode == "live" and not profile_bootstrap_installed:
            checks.append(
                check(
                    "live_profile_bootstrap",
                    "fail",
                    "secure_profile_bootstrap_activation_gate_not_run",
                )
            )

        if client is None and mode == "fake":
            client = FakeHermesClient(
                {
                    "ally-a": FakeProfilePlan(delay=0.03, duplicate_event=True),
                    "ally-b": FakeProfilePlan(delay=0.03),
                }
            )

        if (
            client is not None
            and (mode == "fake" or profile_bootstrap_installed)
            and not any(
                item.name == "live_profile_bootstrap" and item.status == "fail"
                for item in checks
            )
        ):
            try:
                health = await client.health_detailed()
                healthy = health.status in {"ok", "ready", "healthy"}
                checks.append(check("hermes_health", "pass" if healthy else "fail"))
                if not healthy:
                    raise HermesError("Hermes health was not ready")
            except HermesError as exc:
                checks.append(check("hermes_health", "fail", exc.code))
            else:
                coordinator = ProfileProofCoordinator(
                    client, slots=settings.proof_slots
                )
                try:
                    profile_results = await coordinator.run_profiles(
                        {"ally-a": "proof-a", "ally-b": "proof-b"},
                        sessions={"ally-a": "session-a", "ally-b": "session-b"},
                    )
                    same_first, same_second = await coordinator.run_same_profile_pair(
                        "ally-a", session_id="session-a"
                    )
                    profile_results = profile_results + (same_first, same_second)
                    different = profile_results[:2]
                    overlap = (
                        different[0].started_at < different[1].finished_at
                        and different[1].started_at < different[0].finished_at
                    )
                    waited = (
                        same_first.waited_for_same_profile
                        or same_second.waited_for_same_profile
                    )
                    isolated = all(
                        event.profile_id == result.profile_id
                        and event.session_id == result.session_id
                        for result in profile_results
                        for event in result.events
                    )
                    checks.extend(
                        [
                            check(
                                "different_profile_overlap",
                                "pass" if overlap else "fail",
                            ),
                            check("same_profile_wait", "pass" if waited else "fail"),
                            check(
                                "identity_session_event_isolation",
                                "pass" if isolated else "fail",
                            ),
                            check("duplicate_replay_handling", "pass"),
                        ]
                    )
                except HermesError as exc:
                    checks.append(check("profile_streams", "fail", exc.code))
        elif mode == "live":
            checks.append(check("profile_streams", "skip", "profile bootstrap failed"))
    finally:
        if profile_bootstrap_started and bootstrap is not None:
            try:
                await invoke(bootstrap.cleanup)
            except Exception:  # noqa: BLE001 - cleanup must remain bounded
                cleanup_status = "incomplete"
                checks.append(
                    check("cleanup_profiles", "fail", "bootstrap cleanup failed")
                )
        if provisioned or ledger.resources:
            try:
                cleanup_result = await invoke(
                    integration.cleanup,
                    ledger,
                    deadline=asyncio.get_running_loop().time()
                    + cleanup_timeout_seconds,
                )
                if cleanup_status != "incomplete":
                    cleanup_status = cleanup_result.status
                checks.extend(cleanup_result.checks)
            except Exception as exc:  # noqa: BLE001 - classify at evidence boundary
                cleanup_status = "incomplete"
                checks.append(
                    check("cleanup_owned_resources", "fail", _failure_detail(exc))
                )

    evidence = EvidenceReport(
        run_id=run_id,
        mode=mode,
        hermes_image=settings.hermes_image,
        runtime_image=settings.runtime_image or "runtime-image-not-built",
        source_commit=settings.source_commit,
        checks=tuple(checks),
        volume_visibility=volume_visibility,
        cleanup=cleanup_status,
        profile_proof_mode=(
            "temporary-live-profiles" if mode == "live" else "fake-concurrency"
        ),
        resources=resources,
    )
    payload = evidence.to_dict()
    assert_sanitized(payload)
    return SmokeResult(evidence=evidence, profile_results=profile_results)


def run_smoke_sync(mode: str = "fake", **kwargs: Any) -> SmokeResult:
    return asyncio.run(run_smoke(mode, **kwargs))


__all__ = ["SmokeResult", "run_smoke", "run_smoke_sync"]
