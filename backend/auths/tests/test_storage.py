from datetime import datetime

import pytest
from django.test import override_settings

from auths.storage.avatars import Boto3AvatarObjectStore, InMemoryAvatarObjectStore


def test_in_memory_avatar_store_is_private_and_bounded():
    store = InMemoryAvatarObjectStore()
    store.put("actors/a/key", b"bytes", "image/png")
    metadata = store.head(key="actors/a/key")
    assert metadata.size == 5
    assert b"".join(store.stream_get(key="actors/a/key", max_bytes=5)) == b"bytes"
    with pytest.raises(ValueError):
        list(store.stream_get(key="actors/a/key", max_bytes=4))
    put_url, headers = store.sign_put(
        key="actors/a/new", content_type="image/png", size=5, expires_in=30
    )
    assert put_url.startswith("memory://put/") and headers["Content-Length"] == "5"
    get_url, expires = store.sign_get(key="actors/a/key", expires_in=30)
    assert get_url.startswith("memory://get/") and isinstance(expires, datetime)
    store.delete(key="actors/a/key")
    with pytest.raises(KeyError):
        store.head(key="actors/a/key")


@pytest.mark.parametrize("method", ["head", "stream_get"])
def test_boto_store_uses_private_bucket_and_bounds(monkeypatch, method):
    class Body:
        def __init__(self):
            self.closed = False
            self.reads = 0

        def read(self, size):
            self.reads += 1
            return b"data" if self.reads == 1 and not self.closed else b""

        def close(self):
            self.closed = True

    class Client:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            return f"https://r2/{operation}/{Params['Key']}"

        def head_object(self, **kwargs):
            return {"ContentType": "image/png", "ContentLength": 4}

        def get_object(self, **kwargs):
            return {"Body": Body()}

        def delete_object(self, **kwargs):
            return {}

    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: Client())
    with override_settings(
        ALLIES_R2_ENDPOINT_URL="https://r2.example",
        ALLIES_R2_BUCKET="private",
        ALLIES_R2_ACCESS_KEY_ID="access",
        ALLIES_R2_SECRET_ACCESS_KEY="secret",
    ):
        store = Boto3AvatarObjectStore()
        if method == "head":
            assert store.head(key="k").size == 4
        else:
            assert b"".join(store.stream_get(key="k", max_bytes=4)) == b"data"
        assert store.sign_get(key="k", expires_in=10)[0].startswith("https://r2/")
        store.delete(key="k")
