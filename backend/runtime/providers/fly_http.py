"""Small, bounded HTTP boundary for the Fly Machines API.

The client deliberately knows nothing about Apps, Volumes, or Machines.  It
performs one request, validates the status and JSON boundary, and translates
provider failures into the provider-neutral errors used by the lifecycle
service.  Retries and reconciliation remain the lifecycle service's job.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import (
    ProviderCapacityError,
    ProviderConflictError,
    ProviderInvalidConfigurationError,
    ProviderNotFoundError,
    ProviderProtocolError,
    ProviderRateLimitError,
    ProviderRetryableError,
    ProviderTerminalError,
    ProviderTimeoutError,
    ProviderUnauthorizedError,
    ProviderUnsupportedTopologyError,
)

REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_API_BASE_URL = "https://api.machines.dev/v1"


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """Raw response returned by a transport implementation.

    ``body`` is intentionally kept at the transport boundary only.  The
    HTTP client decodes it for the caller and never puts it on an exception.
    """

    status_code: int
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)


class FlyTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse: ...


class UrllibFlyTransport:
    """Production transport using the Python standard library only."""

    def request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                response_body = response.read()
                response_headers = {
                    str(key).lower(): str(value)
                    for key, value in response.headers.items()
                }
                return TransportResponse(
                    status_code=int(response.status),
                    body=response_body,
                    headers=response_headers,
                )
        except HTTPError as exc:
            # HTTPError is also a file-like response.  Read it here so status
            # mapping can distinguish 401/429/5xx without retaining its body.
            try:
                response_body = exc.read()
            finally:
                exc.close()
            response_headers = {
                str(key).lower(): str(value) for key, value in exc.headers.items()
            }
            return TransportResponse(
                status_code=int(exc.code),
                body=response_body,
                headers=response_headers,
            )


class FlyHttpClient:
    """One-request Fly API client with a fixed ten-second timeout."""

    def __init__(
        self,
        *,
        api_token: str | None = None,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
        transport: FlyTransport | None = None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("Fly API base_url must be a non-empty string")
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise ValueError("Fly API timeout must be positive")
        if api_token is not None and not isinstance(api_token, str):
            raise TypeError("Fly API token must be a string or None")
        self.base_url = base_url.rstrip("/")
        # Lifecycle phase deadlines belong to the service; every individual
        # Fly request is capped at the accepted ten-second boundary.  A
        # smaller value remains useful for deterministic tests.
        self.timeout_seconds = min(float(timeout_seconds), REQUEST_TIMEOUT_SECONDS)
        self.api_token = api_token
        self.transport = transport or UrllibFlyTransport()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | list[Any] | None = None,
        headers: Mapping[str, str] | None = None,
        operation: str = "provider_request",
        query: Mapping[str, str | int] | None = None,
    ) -> Any:
        """Perform exactly one request and return decoded JSON.

        This method intentionally does not retry.  A timeout is marked as
        uncertain because a Fly create/stop request may have completed before
        the client lost its response.
        """

        if not isinstance(method, str) or not method:
            raise ValueError("Fly API method is required")
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("Fly API path must be absolute")
        if any(character in path for character in "\r\n"):
            raise ValueError("Fly API path must not contain newlines")
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"
        encoded_body: bytes | None = None
        request_headers: MutableMapping[str, str] = {
            "Accept": "application/json",
        }
        if body is not None:
            try:
                encoded_body = json.dumps(body, separators=(",", ":")).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ProviderProtocolError(
                    "provider request body is not JSON serializable",
                    operation=operation,
                ) from exc
            request_headers["Content-Type"] = "application/json"
        if self.api_token:
            request_headers["Authorization"] = f"Bearer {self.api_token}"
        if headers:
            for key, value in headers.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise TypeError("Fly API headers must be string pairs")
                request_headers[key] = value

        try:
            response = self.transport.request(
                method.upper(),
                url,
                body=encoded_body,
                headers=request_headers,
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                "provider request timed out",
                operation=operation,
                uncertain=True,
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise ProviderTimeoutError(
                    "provider request timed out",
                    operation=operation,
                    uncertain=True,
                ) from exc
            raise ProviderRetryableError(
                "provider transport is unavailable",
                operation=operation,
                uncertain=True,
            ) from exc
        except OSError as exc:
            raise ProviderRetryableError(
                "provider transport is unavailable",
                operation=operation,
                uncertain=True,
            ) from exc

        if not isinstance(response, TransportResponse):
            raise ProviderProtocolError(
                "provider transport returned an invalid response",
                operation=operation,
            )
        if not isinstance(response.headers, Mapping):
            raise ProviderProtocolError(
                "provider transport returned invalid headers",
                operation=operation,
            )
        status = response.status_code
        if not isinstance(status, int) or status < 100 or status > 599:
            raise ProviderProtocolError(
                "provider transport returned an invalid status",
                operation=operation,
            )
        if status < 200 or status >= 300:
            self._raise_status_error(response, operation=operation)
        if status == 204 or response.body in (None, b"", ""):
            return None
        return self._decode_json(response.body, operation=operation)

    def get(
        self,
        path: str,
        *,
        operation: str = "provider_get",
        query: Mapping[str, str | int] | None = None,
    ) -> Any:
        return self.request("GET", path, operation=operation, query=query)

    def post(
        self,
        path: str,
        *,
        body: Mapping[str, Any] | list[Any] | None = None,
        headers: Mapping[str, str] | None = None,
        operation: str = "provider_post",
    ) -> Any:
        return self.request(
            "POST", path, body=body, headers=headers, operation=operation
        )

    def delete(
        self,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        operation: str = "provider_delete",
    ) -> Any:
        return self.request("DELETE", path, headers=headers, operation=operation)

    @staticmethod
    def _decode_json(body: Any, *, operation: str) -> Any:
        if isinstance(body, (Mapping, list)):
            return body
        if isinstance(body, bytes):
            try:
                body = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProviderProtocolError(
                    "provider response was not UTF-8 JSON",
                    operation=operation,
                ) from exc
        if not isinstance(body, str):
            raise ProviderProtocolError(
                "provider response body has an invalid type",
                operation=operation,
            )
        try:
            return json.loads(body)
        except (TypeError, ValueError) as exc:
            raise ProviderProtocolError(
                "provider response was malformed JSON",
                operation=operation,
            ) from exc

    def _raise_status_error(
        self,
        response: TransportResponse,
        *,
        operation: str,
    ) -> None:
        status = response.status_code
        hint = _safe_error_hint(response.body)
        details: dict[str, str] = {"status": str(status)}
        if hint:
            details["reason"] = hint
        response_headers = {
            str(key).lower(): str(value) for key, value in response.headers.items()
        }
        if response_headers.get("retry-after"):
            details["retry_after"] = response_headers["retry-after"]
        kwargs = {
            "operation": operation,
            "status_code": status,
            "details": details,
        }
        if status in (401, 403):
            raise ProviderUnauthorizedError(
                "provider authorization was rejected", **kwargs
            )
        if status == 404:
            raise ProviderNotFoundError("provider resource was not found", **kwargs)
        if status == 408:
            raise ProviderTimeoutError(
                "provider request timed out", uncertain=True, **kwargs
            )
        if status == 429:
            raise ProviderRateLimitError("provider rate limit exceeded", **kwargs)
        if status == 409:
            raise ProviderConflictError(
                "provider reported a resource conflict", **kwargs
            )
        if status in (400, 422):
            if hint == "unsupported_topology":
                raise ProviderUnsupportedTopologyError(
                    "provider does not support the requested Machine topology", **kwargs
                )
            raise ProviderInvalidConfigurationError(
                "provider rejected the requested configuration", **kwargs
            )
        if status >= 500:
            if hint == "capacity":
                raise ProviderCapacityError(
                    "provider region has insufficient capacity", **kwargs
                )
            raise ProviderRetryableError(
                "provider returned a transient server error", **kwargs
            )
        raise ProviderTerminalError("provider request failed", **kwargs)


def _safe_error_hint(body: Any) -> str | None:
    """Extract a small, non-sensitive category from an error payload."""

    values: list[str] = []
    if isinstance(body, Mapping):
        for key in ("code", "error", "message", "detail", "reason"):
            value = body.get(key)
            if isinstance(value, str):
                values.append(value.lower())
    elif isinstance(body, (bytes, str)):
        # Do not copy arbitrary response text into an exception.  Only use it
        # as a bounded category signal when it contains known provider terms.
        try:
            decoded = body.decode("utf-8") if isinstance(body, bytes) else body
            parsed = json.loads(decoded)
            return _safe_error_hint(parsed)
        except (UnicodeDecodeError, TypeError, ValueError):
            return None
    joined = " ".join(values)
    if any(
        term in joined
        for term in ("pilot", "multi-container", "multicontainer", "containers")
    ):
        return "unsupported_topology"
    if any(
        term in joined for term in ("capacity", "insufficient_capacity", "no capacity")
    ):
        return "capacity"
    return None


__all__ = [
    "DEFAULT_API_BASE_URL",
    "REQUEST_TIMEOUT_SECONDS",
    "FlyHttpClient",
    "FlyTransport",
    "TransportResponse",
    "UrllibFlyTransport",
]
