"""Private object-store port and the R2/S3 implementation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol

from botocore.config import Config

from auths.config import setting


@dataclass(frozen=True)
class ObjectMetadata:
    content_type: str
    size: int
    sha256: str = ""


class AvatarObjectStore(Protocol):
    def sign_put(
        self, *, key: str, content_type: str, size: int, expires_in: int
    ) -> tuple[str, dict[str, str]]: ...

    def head(self, *, key: str) -> ObjectMetadata: ...

    def stream_get(self, *, key: str, max_bytes: int) -> Iterable[bytes]: ...

    def put_verified(self, *, key: str, data: bytes, content_type: str) -> None: ...

    def sign_get(self, *, key: str, expires_in: int) -> tuple[str, datetime]: ...

    def delete(self, *, key: str) -> None: ...


class InMemoryAvatarObjectStore:
    """Deterministic test store; it never pretends to be public storage."""

    def __init__(self):
        self._objects: dict[str, tuple[bytes, str]] = {}
        self._lock = RLock()

    def put(self, key: str, data: bytes, content_type: str) -> None:
        with self._lock:
            self._objects[key] = (bytes(data), content_type)

    def put_verified(self, *, key: str, data: bytes, content_type: str) -> None:
        self.put(key, data, content_type)

    def sign_put(self, *, key: str, content_type: str, size: int, expires_in: int):
        return f"memory://put/{key}?exp={expires_in}", {
            "Content-Type": content_type,
            "Content-Length": str(size),
        }

    def head(self, *, key: str) -> ObjectMetadata:
        with self._lock:
            data, content_type = self._objects[key]
        return ObjectMetadata(content_type, len(data), hashlib.sha256(data).hexdigest())

    def stream_get(self, *, key: str, max_bytes: int):
        with self._lock:
            data, _ = self._objects[key]
        if len(data) > max_bytes:
            raise ValueError("object exceeds bound")
        return (
            data[index : index + 64 * 1024] for index in range(0, len(data), 64 * 1024)
        )

    def sign_get(self, *, key: str, expires_in: int):
        expires = datetime.now(UTC) + timedelta(seconds=expires_in)
        return f"memory://get/{key}?exp={int(expires.timestamp())}", expires

    def delete(self, *, key: str) -> None:
        with self._lock:
            self._objects.pop(key, None)


class Boto3AvatarObjectStore:
    def __init__(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - deployment dependency check
            raise RuntimeError("boto3 is required for R2 avatar storage") from exc
        endpoint = setting("ALLIES_R2_ENDPOINT_URL", "")
        bucket = setting("ALLIES_R2_BUCKET", "")
        if not endpoint or not bucket:
            raise RuntimeError("R2 storage is not configured")
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=setting("ALLIES_R2_ACCESS_KEY_ID", ""),
            aws_secret_access_key=setting("ALLIES_R2_SECRET_ACCESS_KEY", ""),
            region_name="auto",
            config=Config(
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    def sign_put(self, *, key: str, content_type: str, size: int, expires_in: int):
        params = {
            "Bucket": self.bucket,
            "Key": key,
            "ContentType": content_type,
            "ContentLength": size,
        }
        url = self.client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_in
        )
        return url, {"Content-Type": content_type, "Content-Length": str(size)}

    def head(self, *, key: str) -> ObjectMetadata:
        result = self.client.head_object(Bucket=self.bucket, Key=key)
        return ObjectMetadata(
            str(result.get("ContentType", "")), int(result.get("ContentLength", 0))
        )

    def stream_get(self, *, key: str, max_bytes: int):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        total = 0
        try:
            while True:
                chunk = body.read(min(64 * 1024, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("object exceeds bound")
                yield chunk
        finally:
            close = getattr(body, "close", None)
            if close:
                close()

    def put_verified(self, *, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ContentLength=len(data),
            Metadata={"sha256": hashlib.sha256(data).hexdigest()},
        )

    def sign_get(self, *, key: str, expires_in: int):
        expires = datetime.now(UTC) + timedelta(seconds=expires_in)
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url, expires

    def delete(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_store: AvatarObjectStore | None = None


def set_avatar_store(store: AvatarObjectStore | None) -> None:
    global _store
    _store = store


def get_avatar_store() -> AvatarObjectStore:
    global _store
    if _store is not None:
        return _store
    if bool(setting("ALLIES_R2_ENABLED", False)):
        _store = Boto3AvatarObjectStore()
    else:
        raise RuntimeError(
            "private R2 storage is not enabled; inject a test store explicitly"
        )
    return _store
