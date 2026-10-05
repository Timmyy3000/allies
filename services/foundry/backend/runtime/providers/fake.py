"""Deterministic in-memory transport for provider contract tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .fly_http import TransportResponse


@dataclass(frozen=True, slots=True)
class FakeTransportCall:
    method: str
    url: str
    body: bytes | None
    headers: Mapping[str, str]
    timeout: float

    @property
    def json_body(self) -> Any:
        if self.body in (None, b""):
            return None
        import json

        return json.loads(self.body.decode("utf-8"))


ResponseFactory = Callable[[FakeTransportCall], TransportResponse]


class FakeFlyTransport:
    """Queue responses and capture safe request assertions.

    Authorization headers are redacted before they are retained in the call
    log.  Bodies remain available because tests need to assert Fly payload
    shape; the adapter only ever serializes opaque credential references.
    """

    def __init__(
        self,
        responses: list[TransportResponse | BaseException | ResponseFactory]
        | None = None,
    ) -> None:
        self._responses = deque(responses or [])
        self.calls: list[FakeTransportCall] = []
        # ``requests`` is a readable alias used by a few contract tests.
        self.requests = self.calls

    def enqueue(
        self, response: TransportResponse | BaseException | ResponseFactory
    ) -> None:
        self._responses.append(response)

    def respond(
        self,
        status_code: int,
        body: Any = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.enqueue(
            TransportResponse(
                status_code=status_code,
                body=body,
                headers=headers or {},
            )
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        safe_headers = {
            key: (
                "<redacted>"
                if key.lower() in {"authorization", "fly-machine-lease-nonce"}
                or "token" in key.lower()
                or "secret" in key.lower()
                else value
            )
            for key, value in headers.items()
        }
        call = FakeTransportCall(
            method=method,
            url=url,
            body=body,
            headers=safe_headers,
            timeout=timeout,
        )
        self.calls.append(call)
        if not self._responses:
            raise AssertionError(f"fake transport has no response for {method} {url}")
        response = self._responses.popleft()
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            response = response(call)
        if not isinstance(response, TransportResponse):
            raise TypeError("fake transport response must be TransportResponse")
        return response


FakeTransport = FakeFlyTransport
DeterministicFakeTransport = FakeFlyTransport


__all__ = [
    "DeterministicFakeTransport",
    "FakeFlyTransport",
    "FakeTransport",
    "FakeTransportCall",
]
