"""Print a sanitized Cloud state summary for the FND-009 proof."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
repository_backend = Path(__file__).resolve().parents[1] / "backend"
container_backend = Path("/app")
sys.path.insert(
    0,
    str(container_backend if (container_backend / "manage.py").exists() else repository_backend),
)

import django  # noqa: E402

django.setup()

from activities.models import Activity  # noqa: E402
from allies.models import Ally  # noqa: E402
from chat.models import Conversation, DispatchOutbox, Message  # noqa: E402
from workspaces.models import Workspace  # noqa: E402

FND009_NAMESPACE = uuid5(NAMESPACE_URL, "allies-fnd009:proof:v1")
WORKSPACE_ID = uuid5(FND009_NAMESPACE, "fnd009-workspace")


def main() -> None:
    workspace = Workspace.objects.filter(pk=WORKSPACE_ID).first()
    if workspace is None:
        print(json.dumps({"status": "missing", "workspace_id": str(WORKSPACE_ID)}))
        return
    conversations = Conversation.objects.filter(ally__workspace=workspace)
    messages = Message.objects.filter(conversation__in=conversations)
    print(json.dumps({
        "status": "ok",
        "workspace_id": str(WORKSPACE_ID),
        "runtime_intent_mode": workspace.runtime_intent_mode,
        "ally_count": Ally.objects.filter(workspace=workspace).count(),
        "conversation_count": conversations.count(),
        "message_count": messages.count(),
        "message_statuses": sorted(set(messages.values_list("status", flat=True))),
        "activity_count": Activity.objects.filter(conversation__in=conversations).count(),
        "dispatch_outbox_count": DispatchOutbox.objects.filter(message__in=messages).count(),
        "dispatch_statuses": sorted(set(DispatchOutbox.objects.filter(message__in=messages).values_list("status", flat=True))),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
