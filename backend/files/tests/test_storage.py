from io import BytesIO

import pytest

from files.storage import (
    Boto3PrivateFileStore,
    InMemoryFileObjectStore,
)


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


def test_boto_erase_verifies_each_version_page_and_preserves_siblings():
    pages = [
        {
            "Versions": [
                {"Key": "private/mira/file", "VersionId": "v1"},
                {"Key": "private/mira/file-sibling", "VersionId": "s1"},
            ],
            "DeleteMarkers": [
                {"Key": "private/mira/file", "VersionId": "m1"},
            ],
            "IsTruncated": True,
            "NextKeyMarker": "private/mira/file",
            "NextVersionIdMarker": "v1",
        },
        {
            "Versions": [{"Key": "private/mira/file", "VersionId": "v2"}],
            "DeleteMarkers": [],
            "IsTruncated": False,
        },
    ]
    listed = []
    deleted = []

    class MissingObject(Exception):
        def __init__(self):
            self.response = {"Error": {"Code": "404"}}

    class Client:
        def get_bucket_versioning(self, **kwargs):
            return {"Status": "Enabled"}

        def list_object_versions(self, **kwargs):
            listed.append(kwargs)
            return pages.pop(0)

        def delete_object(self, **kwargs):
            deleted.append(kwargs)

        def head_object(self, **kwargs):
            raise MissingObject

    store = object.__new__(Boto3PrivateFileStore)
    store.bucket = "private-files"
    store.client = Client()

    continuation = store.erase_and_verify(key="private/mira/file")
    assert continuation == ("private/mira/file", "v1")
    assert listed[0]["MaxKeys"] == 100
    assert deleted == [
        {"Bucket": "private-files", "Key": "private/mira/file", "VersionId": "v1"},
        {"Bucket": "private-files", "Key": "private/mira/file", "VersionId": "m1"},
    ]

    assert (
        store.erase_and_verify(
            key="private/mira/file",
            key_marker=continuation[0],
            version_id_marker=continuation[1],
        )
        is None
    )
    assert listed[1]["KeyMarker"] == "private/mira/file"
    assert listed[1]["VersionIdMarker"] == "v1"
    assert deleted[-1] == {
        "Bucket": "private-files",
        "Key": "private/mira/file",
        "VersionId": "v2",
    }


def test_boto_erase_requires_success_evidence_for_unversioned_status():
    class Client:
        def get_bucket_versioning(self, **kwargs):
            return {"Status": None}

    store = object.__new__(Boto3PrivateFileStore)
    store.bucket = "private-files"
    store.client = Client()

    with pytest.raises(RuntimeError, match="versioning capability"):
        store.erase_and_verify(key="private/mira/file")
