import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen
from uuid import UUID

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.test import Client
from runtime.models import Execution, PublicationIntent, PublicationIntentState

sys.path.insert(0, os.environ["FOUNDRY_RUNTIME_ROOT"])
from allies_runtime.foundry import FoundryClaim, FoundryClient, FoundryWorker
from allies_runtime.hermes import HermesEvent
from allies_runtime.publication_bridge import PublicationBridge

pytest_plugins = ["runtime.tests.test_publications"]


@pytest.mark.django_db(transaction=True)
def test_real_cloud_foundry_runtime_roundtrip(
    publication_claim, settings, tmp_path, monkeypatch
):
    info = json.loads(Path(os.environ["CLOUD_ROUNDTRIP_INFO"]).read_text())
    settings.ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED = True
    settings.ALLIES_CLOUD_URL = info["url"]
    settings.ALLIES_CLOUD_EVENT_SERVICE_TOKEN = "f" * 32
    monkeypatch.setattr(
        "runtime.services.publications._validated_cloud_url",
        lambda value: value if value == info["url"] else None,
    )
    _context, claim, profile, execution, token = publication_claim
    claim = FoundryClaim(
        **{
            key: str(value) if isinstance(value, UUID) else value
            for key, value in asdict(claim).items()
        }
    )
    claim = replace(
        claim, payload={**claim.payload, "cloud_conversation_ref": "roundtrip"}
    )
    execution.cloud_binding_id = info["binding_id"]
    execution.cloud_message_id = info["message_id"]
    execution.save(update_fields=["cloud_binding_id", "cloud_message_id"])
    local = tmp_path / "profiles" / "ally" / "workspace"
    local.mkdir(parents=True)
    original = b"name,value\nroundtrip,42\n"
    source = local / "result.csv"
    source.write_bytes(original)
    client = Client()
    requests = []

    class Transport:
        async def request(self, method, path, *, headers, body=None):
            def send():
                data = (
                    body
                    if isinstance(body, bytes)
                    else json.dumps(body).encode()
                    if body is not None
                    else b""
                )
                content_type = headers.get("Content-Type", "application/json")
                extra = {
                    "HTTP_" + key.upper().replace("-", "_"): value
                    for key, value in headers.items()
                    if key.lower() not in {"content-type", "content-length"}
                }
                response = client.generic(
                    method, path, data=data, content_type=content_type, **extra
                )
                if response.status_code >= 400:
                    print("TEST API ERROR", path, response.content.decode())
                requests.append((method, path, response.status_code))
                return {"status": response.status_code, "body": response.content}

            return await sync_to_async(send, thread_sensitive=True)()

    class Profiles:
        def workspace_path(self, profile_key):
            assert profile_key == "ally"
            return local

    foundry = FoundryClient(runtime_token=token, transport=Transport())
    bridge = PublicationBridge(foundry, Profiles(), tmp_path)
    invocations = []

    class Hermes:
        async def ensure_profile_session(self, *args, **kwargs):
            return None

        async def stream_profile_incremental(self, *args, **kwargs):
            invocations.append(1)
            result = await bridge.publish(
                kwargs["publication_context"], "publish-1", ["result.csv"]
            )
            assert result["state"] == "failed", result

            async def events():
                yield HermesEvent(
                    "execution.completed",
                    "ally",
                    "session",
                    "run",
                    1,
                    {"run_id": "run", "status": "completed"},
                )

            return events()

    async def scenario():
        worker = FoundryWorker(
            foundry, Hermes(), profile_store=Profiles(), publication_bridge=bridge
        )
        receipt = await worker.run_claim(claim)
        assert receipt.status == "succeeded", (receipt, requests)
        exhausted = await sync_to_async(
            PublicationIntent.objects.update, thread_sensitive=True
        )(state=PublicationIntentState.FAILED, attempts=5)
        assert exhausted == 1
        source.write_bytes(b"changed after the model attempt ended")

        def retry():
            with urlopen(info["url"] + "/test/retry") as response:
                return json.load(response)

        result = await asyncio.to_thread(retry)
        assert result["cleanup_confirmed"] is True
        await bridge.recover(str(profile.id), "ally")

    async_to_sync(scenario)()
    with urlopen(info["url"] + "/test/state") as response:
        state = json.load(response)
    assert len(invocations) == 1
    assert Execution.objects.count() == 1
    assert PublicationIntent.objects.count() == 1
    assert [row["sha256"] for row in state["received"]] == [
        sha256(original).hexdigest()
    ] * 2, state
    assert [row["generation"] for row in state["received"]] == [1, 2], state
    assert state["files"][0]["state"] == "ready", state
    assert bytes.fromhex(state["files"][0]["bytes"]) == original
    assert state["storage"] == {
        "reserved_bytes": 0,
        "retained_bytes": len(original),
    }
    assert all(status < 300 for _, _, status in requests), requests
    print(
        json.dumps(
            {
                "model_invocations": len(invocations),
                "executions": Execution.objects.count(),
                "recovered_after_local_exhaustion": True,
                "retry_waited_for_cleanup": True,
                "received_generations": [
                    row["generation"] for row in state["received"]
                ],
                "sha256": sha256(original).hexdigest(),
                "requests": len(requests),
            }
        )
    )
