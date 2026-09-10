"""Private file-object storage. This port deliberately has no URL methods."""

from __future__ import annotations

from io import BytesIO
from threading import RLock
from typing import BinaryIO, Protocol

from botocore.config import Config
from django.conf import settings


class FileObjectMissing(Exception):
    pass


class PrivateFileStore(Protocol):
    def put_stream(
        self, *, key: str, stream, content_type: str, size: int, sha256: str
    ) -> None: ...

    def metadata(self, *, key: str) -> tuple[int, str]: ...

    def promote(self, *, source_key: str, destination_key: str) -> None: ...

    def open_stream(self, *, key: str) -> BinaryIO: ...

    def delete(self, *, key: str) -> None: ...


class InMemoryFileObjectStore:
    """A test-only private store. It is injected; it is never a deployment default."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str, str]] = {}
        self._lock = RLock()

    def put_stream(
        self, *, key: str, stream, content_type: str, size: int, sha256: str
    ) -> None:
        chunks: list[bytes] = []
        while chunk := stream.read(64 * 1024):
            chunks.append(chunk)
        data = b"".join(chunks)
        if len(data) != size:
            raise ValueError("stream length mismatch")
        with self._lock:
            self.objects[key] = (data, content_type, sha256)

    def metadata(self, *, key: str) -> tuple[int, str]:
        try:
            with self._lock:
                data, _, digest = self.objects[key]
        except KeyError as exc:
            raise FileObjectMissing("private object missing") from exc
        return len(data), digest

    def promote(self, *, source_key: str, destination_key: str) -> None:
        with self._lock:
            self.objects[destination_key] = self.objects[source_key]

    def open_stream(self, *, key: str) -> BinaryIO:
        try:
            with self._lock:
                data = self.objects[key][0]
        except KeyError as exc:
            raise FileObjectMissing("private object missing") from exc
        return BytesIO(data)

    def delete(self, *, key: str) -> None:
        with self._lock:
            self.objects.pop(key, None)


class Boto3PrivateFileStore:
    def __init__(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("boto3 is required for private file storage") from exc
        required = (
            settings.ALLIES_FILE_STORAGE_ENDPOINT_URL,
            settings.ALLIES_FILE_STORAGE_BUCKET,
            settings.ALLIES_FILE_STORAGE_ACCESS_KEY_ID,
            settings.ALLIES_FILE_STORAGE_SECRET_ACCESS_KEY,
        )
        if not all(required):
            raise RuntimeError("private file storage is not configured")
        self.bucket = settings.ALLIES_FILE_STORAGE_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.ALLIES_FILE_STORAGE_ENDPOINT_URL,
            aws_access_key_id=settings.ALLIES_FILE_STORAGE_ACCESS_KEY_ID,
            aws_secret_access_key=settings.ALLIES_FILE_STORAGE_SECRET_ACCESS_KEY,
            region_name="auto",
            config=Config(
                connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}
            ),
        )

    def put_stream(
        self, *, key: str, stream, content_type: str, size: int, sha256: str
    ) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=stream,
            ContentType=content_type,
            ContentLength=size,
            Metadata={"sha256": sha256},
        )

    def metadata(self, *, key: str) -> tuple[int, str]:
        try:
            result = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise FileObjectMissing("private object missing") from exc
            raise
        return int(result["ContentLength"]), str(
            result.get("Metadata", {}).get("sha256", "")
        )

    def promote(self, *, source_key: str, destination_key: str) -> None:
        self.client.copy_object(
            Bucket=self.bucket,
            Key=destination_key,
            CopySource={"Bucket": self.bucket, "Key": source_key},
            MetadataDirective="COPY",
        )

    def open_stream(self, *, key: str) -> BinaryIO:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise FileObjectMissing("private object missing") from exc
            raise

    def delete(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_store: PrivateFileStore | None = None


def set_file_store(store: PrivateFileStore | None) -> None:
    global _store
    _store = store


def get_file_store() -> PrivateFileStore:
    global _store
    if _store is not None:
        return _store
    if not settings.ALLIES_FILE_STORAGE_ENABLED:
        raise RuntimeError("private file storage is disabled")
    _store = Boto3PrivateFileStore()
    return _store
