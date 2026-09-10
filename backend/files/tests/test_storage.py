from io import BytesIO

from files.storage import Boto3PrivateFileStore, InMemoryFileObjectStore


def test_private_store_persists_checksum_during_upload():
    store = InMemoryFileObjectStore()
    store.put_stream(
        key="staging/example",
        stream=BytesIO(b"abc"),
        content_type="application/octet-stream",
        size=3,
        sha256="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    )
    assert store.metadata(key="staging/example") == (
        3,
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    )


def test_boto_port_writes_checksum_metadata_with_streamed_object():
    calls = []

    class Client:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    store = object.__new__(Boto3PrivateFileStore)
    store.bucket = "private-files"
    store.client = Client()
    store.put_stream(
        key="staging/example",
        stream=BytesIO(b"abc"),
        content_type="application/octet-stream",
        size=3,
        sha256="a" * 64,
    )
    assert len(calls) == 1
    assert calls[0]["Bucket"] == "private-files"
    assert calls[0]["Key"] == "staging/example"
    assert calls[0]["ContentType"] == "application/octet-stream"
    assert calls[0]["ContentLength"] == 3
    assert calls[0]["Metadata"] == {"sha256": "a" * 64}
