from __future__ import annotations

import asyncio
import threading
import time

import pytest

from allies_runtime.fake import FakeHermesClient, FakeProfilePlan
from allies_runtime.integration import (
    CleanupResult,
    FakeSmokeIntegration,
    IntegrationSnapshot,
    OwnedResourceLedger,
    invoke,
    validate_run_id,
)
from allies_runtime.smoke import run_smoke


class Bootstrap:
    def __init__(self, available: bool = True):
        self.enabled = available
        self.prepared = False
        self.installed = False
        self.cleaned = False

    def available(self):
        return self.enabled

    def prepare(self, run_id):
        self.prepared = bool(run_id)

    def install(self, run_id, *, timeout_seconds):
        self.installed = bool(run_id)
        return self.installed

    def cleanup(self):
        self.cleaned = True


class NotFound(RuntimeError):
    code = "provider_not_found"


class BrokenIntegration(FakeSmokeIntegration):
    def __init__(self, *, phase="provision"):
        super().__init__()
        self.phase = phase

    def preflight(self):
        super().preflight()
        if self.phase == "preflight":
            raise RuntimeError("capability detail")

    def provision(self, run_id):
        if self.phase == "provision":
            raise RuntimeError("provider detail")
        return super().provision(run_id)

    async def cleanup(self, ledger, *, deadline):
        if self.phase == "cleanup":
            raise RuntimeError("cleanup detail")
        return super().cleanup(ledger, deadline=deadline)


class BrokenBootstrap(Bootstrap):
    def prepare(self, run_id):
        raise RuntimeError("secret detail")

    def install(self, run_id, *, timeout_seconds):
        raise RuntimeError("secret install detail")

    def cleanup(self):
        raise RuntimeError("secret cleanup detail")


class InstallBrokenBootstrap(Bootstrap):
    def install(self, run_id, *, timeout_seconds):
        raise RuntimeError("secret install detail")


class BeforeBindIntegration(FakeSmokeIntegration):
    def __init__(self):
        super().__init__()
        self.before_bind = None

    def configure_before_bind(self, callback):
        self.before_bind = callback

    def provision(self, run_id):
        assert self.before_bind is not None
        self.before_bind()
        return super().provision(run_id)


class ReservedThenFailIntegration(FakeSmokeIntegration):
    def reserve(self, run_id):
        return IntegrationSnapshot(
            resource_ids={
                "app": f"fake-app-{run_id}",
                "volume": f"fake-volume-{run_id}",
                "machine": f"fake-machine-{run_id}",
            }
        )

    def provision(self, run_id):
        raise RuntimeError("machine phase failed after ownership reservation")


def test_snapshot_rejects_unsafe_resource_ids():
    with pytest.raises(ValueError, match="safe"):
        IntegrationSnapshot(resource_ids={"machine": "machine/secret"})
    with pytest.raises(ValueError, match="kind"):
        IntegrationSnapshot(resource_ids={"": "machine-1"})
    with pytest.raises(ValueError, match="complete"):
        CleanupResult("pending")


def test_ledger_cleanup_is_ordered_and_treats_recorded_404_as_success():
    ledger = OwnedResourceLedger()
    ledger.record("app", "app-1")
    ledger.record("volume", "volume-1")
    ledger.record("machine", "machine-1")
    calls = []

    def cleaner(kind):
        def run(identifier):
            calls.append((kind, identifier))
            if kind == "volume":
                raise NotFound()

        return run

    result = asyncio.run(
        ledger.cleanup({kind: cleaner(kind) for kind in ("machine", "volume", "app")})
    )
    assert result.status == "complete"
    assert calls == [
        ("machine", "machine-1"),
        ("volume", "volume-1"),
        ("app", "app-1"),
    ]


def test_ledger_cleanup_marks_missing_cleaner_incomplete():
    ledger = OwnedResourceLedger()
    ledger.record("machine", "machine-1")
    result = asyncio.run(ledger.cleanup({}))
    assert result.status == "incomplete"
    assert result.checks[0].status == "fail"


def test_ledger_rejects_invalid_records_and_provider_failures():
    ledger = OwnedResourceLedger()
    with pytest.raises(ValueError, match="kind"):
        ledger.record("", "machine-1")
    with pytest.raises(ValueError, match="safe"):
        ledger.record("machine", "machine/1")
    with pytest.raises(ValueError, match="timeout"):
        asyncio.run(ledger.cleanup({}, timeout_seconds=0))
    ledger.record("machine", "machine-1")

    def fail(_identifier):
        raise RuntimeError("provider response must not escape")

    result = asyncio.run(ledger.cleanup({"machine": fail}))
    assert result.status == "incomplete"


def test_ledger_supports_async_cleaners_and_invoke_supports_both_shapes():
    ledger = OwnedResourceLedger()
    ledger.record("machine", "machine-1")
    called = []

    async def clean(identifier):
        called.append(identifier)

    result = asyncio.run(ledger.cleanup({"machine": clean}))
    assert result.status == "complete" and called == ["machine-1"]
    assert asyncio.run(invoke(lambda value: value + 1, 1)) == 2

    async def plus(value):
        return value + 1

    assert asyncio.run(invoke(plus, 1)) == 2


def test_fake_adapter_exercises_preflight_provision_and_cleanup():
    adapter = FakeSmokeIntegration()
    adapter.preflight()
    snapshot = adapter.provision("fixed")
    ledger = OwnedResourceLedger()
    ledger.record_snapshot(snapshot)
    result = adapter.cleanup(ledger, deadline=1.0)
    assert adapter.preflight_calls == 1
    assert adapter.provision_calls == 1
    assert adapter.cleanup_calls == 1
    assert result.status == "complete"


def test_live_smoke_requires_bootstrap_before_provision(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    adapter = FakeSmokeIntegration()
    bootstrap = Bootstrap(available=False)
    result = asyncio.run(
        run_smoke(
            "live",
            run_id="live-gated",
            integration=adapter,
            bootstrap=bootstrap,
            client=FakeHermesClient(),
        )
    )
    assert adapter.provision_calls == 0
    assert result.evidence.cleanup == "complete"
    assert any(
        item.detail == "secure_profile_bootstrap_unavailable"
        for item in result.evidence.checks
    )


@pytest.mark.parametrize(
    ("integration", "bootstrap", "client", "detail"),
    [
        (None, None, None, "provider_lifecycle_adapter_required"),
        (FakeSmokeIntegration(), None, None, "secure_profile_bootstrap_required"),
        (FakeSmokeIntegration(), Bootstrap(), None, "live_hermes_client_required"),
    ],
)
def test_live_smoke_requires_all_gates(
    monkeypatch, integration, bootstrap, client, detail
):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    result = asyncio.run(
        run_smoke(
            "live",
            run_id="missing-gate",
            integration=integration,
            bootstrap=bootstrap,
            client=client,
        )
    )
    assert any(item.detail == detail for item in result.evidence.checks)


def test_live_smoke_runs_temporary_profile_proof_and_cleans(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    adapter = FakeSmokeIntegration()
    bootstrap = Bootstrap()
    client = FakeHermesClient(
        {"ally-a": FakeProfilePlan(delay=0.001), "ally-b": FakeProfilePlan(delay=0.001)}
    )
    result = asyncio.run(
        run_smoke(
            "live",
            run_id="live-success",
            integration=adapter,
            bootstrap=bootstrap,
            client=client,
        )
    )
    assert result.evidence.profile_proof_mode == "temporary-live-profiles"
    assert result.evidence.cleanup == "complete"
    assert bootstrap.prepared and bootstrap.cleaned
    assert bootstrap.installed
    assert adapter.provision_calls == adapter.cleanup_calls == 1
    assert result.to_dict()["resources"]["machine"] == "fake-machine-live-success"


def test_live_smoke_runs_install_as_the_before_bind_activation_gate(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    adapter = BeforeBindIntegration()
    bootstrap = Bootstrap()
    result = asyncio.run(
        run_smoke(
            "live",
            run_id="before-bind-success",
            integration=adapter,
            bootstrap=bootstrap,
            client=FakeHermesClient(),
        )
    )

    assert result.evidence.cleanup == "complete"
    assert bootstrap.installed and bootstrap.cleaned
    assert adapter.provision_calls == adapter.cleanup_calls == 1
    assert not any(
        item.name == "live_profile_bootstrap" and item.status == "fail"
        for item in result.evidence.checks
    )


def test_live_smoke_does_not_bind_when_before_bind_install_fails(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    adapter = BeforeBindIntegration()
    result = asyncio.run(
        run_smoke(
            "live",
            run_id="before-bind-failure",
            integration=adapter,
            bootstrap=InstallBrokenBootstrap(),
            client=FakeHermesClient(),
        )
    )

    assert adapter.provision_calls == 0
    assert any(
        item.name == "live_profile_bootstrap"
        and item.status == "fail"
        and item.detail == "secure_profile_bootstrap_install_failed"
        for item in result.evidence.checks
    )
    assert any(
        item.name == "profile_streams" and item.status == "skip"
        for item in result.evidence.checks
    )


def test_live_smoke_requires_install_hook_before_bind(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")

    class NoInstall(Bootstrap):
        install = None

    result = asyncio.run(
        run_smoke(
            "live",
            run_id="before-bind-install-required",
            integration=BeforeBindIntegration(),
            bootstrap=NoInstall(),
            client=FakeHermesClient(),
        )
    )

    assert any(
        item.name == "live_profile_bootstrap"
        and item.status == "fail"
        and item.detail == "secure_profile_bootstrap_install_failed"
        for item in result.evidence.checks
    )


def test_live_smoke_bounds_before_bind_install_and_still_cleans(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")

    class HangingBootstrap(Bootstrap):
        def __init__(self):
            super().__init__()
            self.release = threading.Event()

        def install(self, run_id, *, timeout_seconds):
            self.release.wait()
            return True

    adapter = BeforeBindIntegration()
    bootstrap = HangingBootstrap()
    started = time.monotonic()
    result = asyncio.run(
        run_smoke(
            "live",
            run_id="before-bind-timeout",
            integration=adapter,
            bootstrap=bootstrap,
            client=FakeHermesClient(),
            bootstrap_timeout_seconds=0.01,
        )
    )
    bootstrap.release.set()

    assert time.monotonic() - started < 0.2
    assert adapter.provision_calls == 0
    assert bootstrap.cleaned
    assert any(
        item.name == "live_profile_bootstrap"
        and item.status == "fail"
        and item.detail == "secure_profile_bootstrap_install_failed"
        for item in result.evidence.checks
    )


def test_smoke_rejects_invalid_mode_and_timeout():
    with pytest.raises(ValueError, match="mode"):
        asyncio.run(run_smoke("unknown"))
    with pytest.raises(ValueError, match="timeout"):
        asyncio.run(run_smoke(cleanup_timeout_seconds=0))
    with pytest.raises(ValueError, match="bootstrap timeout"):
        asyncio.run(run_smoke(bootstrap_timeout_seconds=0))
    with pytest.raises(ValueError, match="safe identifier"):
        asyncio.run(run_smoke(run_id="proof/with-secret"))
    with pytest.raises(ValueError, match="run_id"):
        asyncio.run(run_smoke(run_id="unsafe/run"))
    assert validate_run_id("safe-run.1") == "safe-run.1"


def test_smoke_records_marker_errors_and_adapter_failures(monkeypatch, tmp_path):
    marker = tmp_path / "outside" / "marker"
    result = asyncio.run(
        run_smoke(
            "fake",
            marker_path=marker,
            volume_root=tmp_path / "volume",
            integration=BrokenIntegration(),
            run_id="broken",
        )
    )
    names = {item.name for item in result.evidence.checks}
    assert "volume_marker_visibility" in names
    assert any(
        item.name == "provider_lifecycle" and item.status == "fail"
        for item in result.evidence.checks
    )


def test_smoke_cleans_reserved_refs_when_provision_phase_fails():
    integration = ReservedThenFailIntegration()
    result = asyncio.run(
        run_smoke("fake", integration=integration, run_id="phase-failure")
    )
    assert integration.cleanup_calls == 1
    assert result.evidence.cleanup == "complete"
    assert result.evidence.to_dict()["resources"] == {
        "app": "fake-app-phase-failure",
        "volume": "fake-volume-phase-failure",
        "machine": "fake-machine-phase-failure",
    }


def test_smoke_records_preflight_and_cleanup_failures(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    preflight = BrokenIntegration(phase="preflight")
    result = asyncio.run(
        run_smoke(
            "live",
            integration=preflight,
            bootstrap=Bootstrap(),
            client=FakeHermesClient(),
            run_id="preflight-broken",
        )
    )
    assert any(item.detail == "integration_failed" for item in result.evidence.checks)

    cleanup = BrokenIntegration(phase="cleanup")
    result = asyncio.run(
        run_smoke(
            "fake",
            integration=cleanup,
            run_id="cleanup-broken",
        )
    )
    assert result.evidence.cleanup == "incomplete"


def test_live_profile_bootstrap_failure_skips_streams_and_marks_cleanup(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    result = asyncio.run(
        run_smoke(
            "live",
            integration=FakeSmokeIntegration(),
            bootstrap=BrokenBootstrap(),
            client=FakeHermesClient(),
            run_id="bootstrap-broken",
        )
    )
    assert result.evidence.cleanup == "incomplete"
    assert any(
        item.name == "profile_streams" and item.status == "skip"
        for item in result.evidence.checks
    )


def test_live_profile_bootstrap_requires_post_provision_install(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")

    class NoInstall(Bootstrap):
        install = None

    bootstrap = NoInstall()
    adapter = FakeSmokeIntegration()
    result = asyncio.run(
        run_smoke(
            "live",
            integration=adapter,
            bootstrap=bootstrap,
            client=FakeHermesClient(),
            run_id="install-required",
        )
    )
    assert adapter.provision_calls == adapter.cleanup_calls == 1
    assert any(
        item.name == "live_profile_bootstrap"
        and item.detail == "secure_profile_bootstrap_install_required"
        for item in result.evidence.checks
    )
    assert any(
        item.name == "profile_streams" and item.status == "skip"
        for item in result.evidence.checks
    )


def test_live_profile_bootstrap_install_failure_skips_streams(monkeypatch):
    monkeypatch.setenv("FND004_LIVE_SMOKE", "1")
    bootstrap = InstallBrokenBootstrap()
    result = asyncio.run(
        run_smoke(
            "live",
            integration=FakeSmokeIntegration(),
            bootstrap=bootstrap,
            client=FakeHermesClient(),
            run_id="install-failed",
        )
    )
    assert any(
        item.name == "live_profile_bootstrap"
        and item.status == "fail"
        and item.detail == "integration_failed"
        for item in result.evidence.checks
    )


def test_smoke_classifies_health_and_stream_failures():
    unhealthy = asyncio.run(
        run_smoke(
            "fake",
            client=FakeHermesClient(health_status="auth-failed"),
            run_id="health-failed",
        )
    )
    assert any(
        item.name == "hermes_health" and item.status == "fail"
        for item in unhealthy.evidence.checks
    )

    disconnected = asyncio.run(
        run_smoke(
            "fake",
            client=FakeHermesClient(
                {
                    "ally-a": FakeProfilePlan(failure="disconnect"),
                    "ally-b": FakeProfilePlan(),
                }
            ),
            run_id="stream-failed",
        )
    )
    assert any(
        item.name == "profile_streams" and item.status == "fail"
        for item in disconnected.evidence.checks
    )
