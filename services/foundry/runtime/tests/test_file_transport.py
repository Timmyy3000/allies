from io import BytesIO
from urllib.error import HTTPError
from uuid import UUID

import pytest

from allies_runtime.foundry import (
    FoundryClient,
    FoundryError,
    InvalidRequestError,
    ResponseLossError,
    UrllibFoundryTransport,
)

ATTEMPT, PROFILE, PUBLICATION, FILE, LEASE = [UUID(int=n) for n in range(1, 6)]


class Transport:
    def __init__(self, response=None):
        self.response = response or {"status": 200, "body": {"state": "ready"}}
        self.calls = []

    async def request(self, method, path, *, headers, body=None):
        self.calls.append((method, path, headers, body))
        return self.response


@pytest.mark.asyncio
async def test_publication_transport_preserves_frozen_bytes_and_retry_authority():
    transport = Transport()
    client = FoundryClient(runtime_token="runtime-only", transport=transport)
    prepared = [{"name": "résultat.csv", "size": 3}]
    frozen = [{**prepared[0], "source_version_id": str(FILE), "sha256": "a" * 64}]
    await client.create_publication_intent(ATTEMPT, "attempt-lease", "tool-1", prepared)
    await client.freeze_publication_intent(PROFILE, PUBLICATION, frozen)
    await client.register_publication(ATTEMPT, "attempt-lease", PUBLICATION, frozen)
    await client.upload_publication_file(
        PROFILE, PUBLICATION, FILE, 2, b"a\x00b", 3, LEASE
    )
    await client.get_publication(PROFILE, PUBLICATION)
    await client.publication_retry_result(PROFILE, PUBLICATION, 3, LEASE, "submitted")
    await client.publication_retry_result(
        PROFILE, PUBLICATION, 3, LEASE, "failed", "transport_unavailable"
    )
    intent, freeze, reserve, upload, detail, submitted, failed = transport.calls
    assert intent[:2] == (
        "POST",
        f"/api/v1/runtime/attempts/{ATTEMPT}/file-publication-intents",
    )
    assert intent[3] == {"tool_call_id": "tool-1", "files": prepared}
    assert freeze[3] == {"files": frozen}
    assert reserve[3] == {"publication_id": str(PUBLICATION), "files": frozen}
    assert upload[:2] == (
        "PUT",
        f"/api/v1/runtime/profiles/{PROFILE}/file-publications/{PUBLICATION}/files/{FILE}/content?generation=2",
    )
    assert upload[3] == b"a\x00b"
    assert upload[2]["Content-Length"] == "3"
    assert upload[2]["Content-Type"] == "application/octet-stream"
    assert upload[2]["X-Allies-Publication-Revision"] == "3"
    assert upload[2]["X-Allies-Publication-Lease-Token"] == str(LEASE)
    assert detail[0] == "GET"
    assert submitted[3] == {
        "revision": 3,
        "lease_token": str(LEASE),
        "outcome": "submitted",
    }
    assert failed[3]["safe_error_code"] == "transport_unavailable"
    for _, _, headers, _ in transport.calls:
        assert headers["Authorization"] == "Bearer runtime-only"
    assert intent[2]["X-Foundry-Lease-Token"] == "attempt-lease"
    assert "X-Foundry-Lease-Token" not in upload[2]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "generation,content,revision",
    [
        (0, b"x", 1),
        (True, b"x", 1),
        (1, b"x", 0),
        (1, b"x", True),
        (1, b"", 1),
        (1, "text", 1),
    ],
)
async def test_invalid_publication_upload_does_not_send(generation, content, revision):
    transport = Transport()
    client = FoundryClient(runtime_token="runtime-only", transport=transport)
    with pytest.raises(ValueError):
        await client.upload_publication_file(
            PROFILE, PUBLICATION, FILE, generation, content, revision
        )
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["../file", "?token=x", None])
async def test_invalid_publication_identity_cannot_change_transport_path(identity):
    transport = Transport()
    client = FoundryClient(runtime_token="runtime-only", transport=transport)
    with pytest.raises(ValueError):
        await client.get_publication(PROFILE, identity)
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], {"items": None}, {"items": ["bad"]}])
async def test_recovery_rejects_malformed_claims(body):
    client = FoundryClient(
        runtime_token="runtime-only", transport=Transport({"status": 200, "body": body})
    )
    with pytest.raises(FoundryError):
        await client.claim_publication_retries(PROFILE)


@pytest.mark.asyncio
async def test_recovery_claims_use_current_profile_without_attempt_lease():
    claim = {"publication_id": str(PUBLICATION), "revision": 2}
    transport = Transport({"status": 200, "body": {"items": [claim]}})
    client = FoundryClient(runtime_token="runtime-only", transport=transport)
    assert await client.claim_publication_retries(PROFILE, 20) == [claim]
    method, path, headers, body = transport.calls[0]
    assert (method, path, body) == (
        "POST",
        f"/api/v1/runtime/profiles/{PROFILE}/file-publication-retries/claim",
        {"limit": 20},
    )
    assert "X-Foundry-Lease-Token" not in headers
    for limit in (0, 21, True):
        with pytest.raises(ValueError):
            await client.claim_publication_retries(PROFILE, limit)
    assert len(transport.calls) == 1


class StreamTransport:
    def __init__(self, response=None, error=None, status=200):
        self.response = response
        self.error = error
        self.status = status
        self.calls = []

    async def stream(self, method, path, *, headers):
        self.calls.append((method, path, headers))
        if self.error:
            raise self.error
        return {"status": self.status, "body": {}, "response": self.response}


@pytest.mark.asyncio
async def test_incoming_stream_is_bounded_and_closed_and_carries_attempt_lease():
    content = b"x" * (64 * 1024 + 7)
    response = BytesIO(content)
    transport = StreamTransport(response)
    client = FoundryClient(runtime_token="runtime-only", transport=transport)
    chunks = [
        chunk
        async for chunk in client.incoming_file_chunks(
            str(ATTEMPT), str(FILE), "attempt-lease"
        )
    ]
    assert b"".join(chunks) == content
    assert [len(chunk) for chunk in chunks] == [64 * 1024, 7]
    assert response.closed
    method, path, headers = transport.calls[0]
    assert (method, path) == (
        "GET",
        f"/api/v1/runtime/attempts/{ATTEMPT}/files/{FILE}/content",
    )
    assert headers == {
        "Accept": "application/octet-stream",
        "Authorization": "Bearer runtime-only",
        "X-Foundry-Lease-Token": "attempt-lease",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity,lease,expected",
    [
        ("bad", "lease", InvalidRequestError),
        (str(FILE), "\r\nheader", ValueError),
        (str(FILE), "", ValueError),
    ],
)
async def test_invalid_incoming_authority_never_opens_stream(identity, lease, expected):
    transport = StreamTransport()
    client = FoundryClient(runtime_token="runtime-only", transport=transport)
    with pytest.raises(expected):
        _ = [
            chunk
            async for chunk in client.incoming_file_chunks(
                str(ATTEMPT), identity, lease
            )
        ]
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport,expected",
    [
        (StreamTransport(error=OSError("lost")), ResponseLossError),
        (StreamTransport(status=404), FoundryError),
        (StreamTransport(), FoundryError),
        (Transport(), FoundryError),
    ],
)
async def test_unavailable_incoming_transport_fails_closed(transport, expected):
    client = FoundryClient(runtime_token="runtime-only", transport=transport)
    with pytest.raises(expected):
        _ = [
            chunk
            async for chunk in client.incoming_file_chunks(
                str(ATTEMPT), str(FILE), "lease"
            )
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    ["not-bytes", b"x" * (64 * 1024 + 1), OSError("lost")],
    ids=["wrong-type", "oversized-chunk", "connection-lost"],
)
async def test_corrupt_or_broken_incoming_stream_is_closed(result):
    class Response:
        closed = False

        def read(self, _size):
            if isinstance(result, Exception):
                raise result
            return result

        def close(self):
            self.closed = True

    response = Response()
    client = FoundryClient(
        runtime_token="runtime-only", transport=StreamTransport(response)
    )
    with pytest.raises(FoundryError):
        _ = [
            chunk
            async for chunk in client.incoming_file_chunks(
                str(ATTEMPT), str(FILE), "lease"
            )
        ]
    assert response.closed


@pytest.mark.asyncio
async def test_http_stream_open_does_not_buffer_body(monkeypatch):
    response = BytesIO(b"private file")
    response.status = 200
    calls = []

    def open_response(request, timeout):
        calls.append((request.full_url, timeout, request.get_header("Authorization")))
        return response

    monkeypatch.setattr("urllib.request.urlopen", open_response)
    transport = UrllibFoundryTransport("https://foundry.example", timeout=10)
    opened = await transport.stream(
        "GET",
        "/api/v1/runtime/files/content",
        headers={"Authorization": "Bearer runtime-only"},
    )
    assert calls == [
        (
            "https://foundry.example/api/v1/runtime/files/content",
            10,
            "Bearer runtime-only",
        )
    ]
    assert opened == {"status": 200, "response": response}
    assert response.tell() == 0
    response.close()


@pytest.mark.asyncio
async def test_http_stream_error_body_is_bounded_and_closed(monkeypatch):
    body = BytesIO(b"x" * 20_000)

    def denied(*_args, **_kwargs):
        raise HTTPError("https://foundry.example", 404, "unavailable", {}, body)

    monkeypatch.setattr("urllib.request.urlopen", denied)
    result = await UrllibFoundryTransport("https://foundry.example").stream(
        "GET", "/file", headers={}
    )
    assert result["status"] == 404
    assert len(result["body"]) == 16_385
    assert body.closed
