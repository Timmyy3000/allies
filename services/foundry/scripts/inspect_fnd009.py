"""Print a sanitized Foundry state summary for the FND-009 proof."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
repository_backend = Path(__file__).resolve().parents[1] / "backend"
container_backend = Path("/app")
sys.path.insert(
    0,
    str(container_backend if (container_backend / "manage.py").exists() else repository_backend),
)

import django  # noqa: E402

django.setup()

from fnd009_common import WORKSPACE_ID  # noqa: E402
from runtime.models import (  # noqa: E402
    Attempt,
    Execution,
    ExecutionEvent,
    ExecutionEventDelivery,
    Lease,
    RuntimeIntent,
    RuntimeProfile,
    Workspace,
)


def main() -> None:
    workspace = Workspace.objects.filter(pk=WORKSPACE_ID).first()
    if workspace is None:
        print(json.dumps({"status": "missing", "workspace_id": str(WORKSPACE_ID)}))
        return
    print(json.dumps({
        "status": "ok",
        "workspace_id": str(WORKSPACE_ID),
        "machine_generation": workspace.machine_generation,
        "runtime_operation_state": workspace.runtime_operation_state,
        "runtime_operation_trigger": workspace.runtime_operation_trigger,
        "runtime_start_epoch": workspace.runtime_start_epoch,
        "ready_generation": workspace.ready_generation,
        "ready_start_epoch": workspace.ready_start_epoch,
        "ready": workspace.ready_boot_id is not None,
        "keep_warm_configured": workspace.speculative_keep_warm_until is not None,
        "profile_count": RuntimeProfile.objects.filter(workspace=workspace).count(),
        "intent_count": RuntimeIntent.objects.filter(workspace=workspace).count(),
        "execution_count": Execution.objects.filter(workspace=workspace).count(),
        "attempt_count": Attempt.objects.filter(execution__workspace=workspace).count(),
        "lease_count": Lease.objects.filter(attempt__execution__workspace=workspace).count(),
        "event_count": ExecutionEvent.objects.filter(attempt__execution__workspace=workspace).count(),
        "delivery_count": ExecutionEventDelivery.objects.filter(event__attempt__execution__workspace=workspace).count(),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
