import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "runtime_image_cleanup", Path(__file__).parents[1] / "runtime_image_cleanup.py"
)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
OLD, YOUNG = "2026-08-01T00:00:00Z", "2026-09-25T00:00:00Z"


def digest(char):
    return "sha256:" + char * 64


def version(char, created, *tags):
    return {
        "id": ord(char),
        "name": digest(char),
        "created_at": created,
        "metadata": {"container": {"tags": list(tags)}},
    }


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setattr(cleanup.release, "registry_token", lambda image: "Bearer t")


def children_of(mapping):
    return lambda image, name, token: mapping.get(name, set())


def names(versions):
    return {v["name"] for v in versions}


def test_pinned_index_keeps_its_children_and_old_unpinned_release_goes():
    versions = [
        version("a", OLD, "runtime-1-1-runtime"),
        version("b", OLD),
        version("c", OLD),
        version("d", OLD, "runtime-2-1-runtime"),
        version("e", OLD),
    ]
    keep, delete = cleanup.plan(
        versions,
        {digest("a")},
        "example/allies-runtime",
        NOW,
        children=children_of(
            {digest("a"): {digest("b"), digest("c")}, digest("d"): {digest("e")}}
        ),
    )
    assert names(keep) == {digest("a"), digest("b"), digest("c")}
    assert names(delete) == {digest("d"), digest("e")}
    assert delete[0]["name"] == digest("d"), "Indexes are deleted before children"


def test_young_versions_and_their_children_are_kept():
    versions = [
        version("a", YOUNG, "runtime-3-1-runtime"),
        version("b", OLD),
        version("c", YOUNG),
    ]
    keep, delete = cleanup.plan(
        versions,
        set(),
        "example/allies-runtime",
        NOW,
        children=children_of({digest("a"): {digest("b")}}),
    )
    assert names(keep) == {digest("a"), digest("b"), digest("c")}
    assert delete == []


def test_registry_failure_stops_planning():
    def broken(image, name, token):
        raise cleanup.release.ReleaseError("Registry request failed")

    with pytest.raises(cleanup.release.ReleaseError):
        cleanup.plan(
            [version("a", OLD, "runtime-1-1-runtime")],
            {digest("a")},
            "example/allies-runtime",
            NOW,
            children=broken,
        )
