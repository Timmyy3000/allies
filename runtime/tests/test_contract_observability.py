import json
from pathlib import Path

from allies_runtime import observability


def test_runtime_event_implementation_conforms_to_shared_contract():
    contract = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs/contracts/observability/wide-event-v1.json"
        ).read_text()
    )
    assert observability.ALLOWED_EVENT_NAMES <= set(contract["events"])
    assert observability.MAX_COLLECTION_ITEMS == contract["limits"]["max_collection_items"]
    assert observability.DEFAULT_MAX_EVENT_BYTES == contract["limits"]["max_event_bytes"]

    event = observability.build_event(
        "task.succeeded",
        task_name="runtime.tasks.profile_turn",
        task_id="task_123",
        queue="default",
        outcome="success",
    )
    encoded = json.loads(observability.serialize_event(event))
    assert set(contract["required"]) <= set(encoded)
    assert set(encoded) <= set(contract["required"]) | set(contract["optional"])
