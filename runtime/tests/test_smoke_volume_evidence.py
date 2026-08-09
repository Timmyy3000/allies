from __future__ import annotations

import asyncio
import json

from allies_runtime.evidence import (
    EvidenceReport,
    VolumeVisibility,
    assert_sanitized,
    check,
    sanitize_value,
)
from allies_runtime.smoke import run_smoke, run_smoke_sync
from allies_runtime.volume import marker_namespace, observe_volume_marker


def test_volume_observation_is_read_only(tmp_path):
    marker = tmp_path / "proof" / "marker"
    marker.parent.mkdir()
    marker.write_text("hermes marker", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")
    observation = observe_volume_marker(marker, volume_root=tmp_path)
    assert observation.marker_exists
    assert observation.visibility == VolumeVisibility.READ_WRITE
    assert marker.read_text(encoding="utf-8") == before
    assert marker_namespace("run-1").name == "run-1"


def test_evidence_redacts_sensitive_values():
    payload = sanitize_value(
        {"authorization": "Bearer secret", "url": "http://127.0.0.1:8642"}
    )
    assert payload == {"authorization": "<redacted>", "url": "<private-url>"}
    assert_sanitized(payload)
    report = EvidenceReport(
        "run", "fake", "hermes@sha256:" + "a" * 64, "runtime", (check("x", "pass"),)
    )
    assert report.to_dict()["checks"][0]["status"] == "pass"


def test_fake_smoke_has_sanitized_concurrency_evidence():
    result = run_smoke_sync("fake", run_id="fixed-run")
    payload = result.to_dict()
    assert payload["run_id"] == "fixed-run"
    assert {item["name"] for item in payload["checks"]} >= {
        "hermes_health",
        "different_profile_overlap",
        "same_profile_wait",
        "identity_session_event_isolation",
    }
    assert json.dumps(payload).find("Bearer") == -1


def test_live_smoke_fails_closed(monkeypatch):
    monkeypatch.delenv("FND004_LIVE_SMOKE", raising=False)
    payload = asyncio.run(run_smoke("live", run_id="fixed-live")).to_dict()
    assert payload["cleanup"] == "complete"
    assert any(
        item["name"] == "live_capability_gate" and item["status"] == "fail"
        for item in payload["checks"]
    )
