import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    "runtime_release", Path(__file__).parents[1] / "runtime_release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
REPO = "example/foundry"
SOURCE = "a" * 40
PAIR = {
    key: f"ghcr.io/example/{name}@sha256:{'b' * 64}"
    for key, name in release.KEYS.items()
}
EVIDENCE = {
    "image_manifest": "sha256:" + "c" * 64,
    "attestation_manifest": "sha256:" + "d" * 64,
}


class GitHub:
    def __init__(self):
        self.tag = None
        self.release = None
        self.records = {}
        self.writes = []
        self.lose_final_response = False

    def __call__(self, *args, body=None, **_kwargs):
        if args[0] == "release":
            path = Path(args[3])
            assert path.name not in self.records, "Assets must never be overwritten"
            self.records[path.name] = path.read_bytes()
            self.writes.append(path.name)
            if path.name == "release.json" and self.lose_final_response:
                raise release.ReleaseError("Upload response lost")
            return b""
        endpoint = args[1]
        if body is not None:
            self.writes.append(endpoint)
            if endpoint.endswith("/git/refs"):
                assert self.tag is None
                self.tag = {"object": {"sha": body["sha"], "type": "commit"}}
            elif endpoint.endswith("/releases"):
                self.release = {"id": 7, "tag_name": body["tag_name"], "draft": True}
            else:
                self.release["draft"] = body["draft"]
            return self.release or self.tag
        if "/git/ref/" in endpoint:
            return self.tag
        if "/assets/" in endpoint:
            return list(self.records.values())[int(endpoint.rsplit("/", 1)[1]) - 1]
        if self.release is None:
            return None
        return {
            **self.release,
            "assets": [
                {"id": index, "name": name, "size": len(raw)}
                for index, (name, raw) in enumerate(self.records.items(), 1)
            ],
        }


@pytest.fixture
def publishing(monkeypatch, tmp_path):
    for key, value in {
        "GITHUB_REF": "refs/heads/dev",
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_SHA": SOURCE,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "RELEASE_DIRECTORY": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    github = GitHub()
    monkeypatch.setattr(release, "gh", github)
    monkeypatch.setattr(release, "inspect_image", lambda *_args: EVIDENCE)

    def run(command, *args):
        monkeypatch.setattr(release.sys, "argv", ["runtime_release.py", command, *args])
        release.main()

    def candidate():
        run(
            "candidate",
            "--hermes-image",
            PAIR["HERMES_IMAGE"],
            "--runtime-image",
            PAIR["RUNTIME_IMAGE"],
        )

    receipt = {
        "environment": "staging",
        "state": "desired_config_verified",
        "machine_adoption": "not_verified",
        "previous": None,
        "readback": PAIR,
    }
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    return github, run, candidate, tmp_path


def test_saved_pair_retry_and_promotion_ignore_newer_staging(publishing, monkeypatch):
    github, run, candidate, root = publishing
    run("prepare")
    assert "mode=new" in (root / "outputs").read_text()
    candidate()
    original = github.records["candidate.json"]
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    run("prepare")
    candidate()
    assert github.records["candidate.json"] == original
    run("finalize")
    writes = list(github.writes)
    (root / "receipt.json").write_text("staging has advanced")
    run("prepare")
    assert "mode=complete" in (root / "outputs").read_text()
    run("promote", "--release-id", "runtime-123")
    assert PAIR["HERMES_IMAGE"] in (root / "outputs").read_text()
    assert github.writes == writes


def test_finalize_unknown_upload_outcome_reuses_saved_evidence(publishing):
    github, run, candidate, root = publishing
    candidate()
    github.lose_final_response = True
    with pytest.raises(release.ReleaseError, match="lost"):
        run("finalize")
    historical = github.records["release.json"]
    (root / "receipt.json").unlink()
    run("prepare")
    assert "mode=finalize" in (root / "outputs").read_text()
    run("finalize")
    assert github.records["release.json"] == historical
    assert github.release["draft"] is False


def test_draft_wrong_source_and_mismatched_staging_cannot_promote(
    publishing, monkeypatch
):
    github, run, candidate, root = publishing
    candidate()
    with pytest.raises(release.ReleaseError):
        run("promote", "--release-id", "runtime-123")
    receipt = json.loads((root / "receipt.json").read_text())
    receipt["readback"]["RUNTIME_IMAGE"] = PAIR["RUNTIME_IMAGE"].replace(
        "b" * 64, "e" * 64
    )
    (root / "receipt.json").write_text(json.dumps(receipt))
    writes = list(github.writes)
    with pytest.raises(release.ReleaseError, match="Staging"):
        run("finalize")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    with pytest.raises(release.ReleaseError, match="source"):
        run("prepare")
    assert github.writes == writes


def test_duplicate_oversized_json_and_untrusted_refs_fail(publishing, monkeypatch):
    github, run, _candidate, _root = publishing
    for raw in (b'{"key":1,"key":2}', b"x" * 65_537, b"[]"):
        with pytest.raises(release.ReleaseError):
            release.decode(raw)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/untrusted")
    with pytest.raises(release.ReleaseError):
        run("prepare")
    assert not github.writes
    for pair in (
        {},
        {**PAIR, "RUNTIME_IMAGE": "ghcr.io/other/allies-runtime@sha256:" + "b" * 64},
    ):
        with pytest.raises(release.ReleaseError):
            release.record_pair(pair, REPO)


def oci(source=SOURCE, subject=True, sbom=True):
    blobs = {}

    def put(value):
        raw = json.dumps(value).encode()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        blobs[digest] = (raw, value)
        return digest

    platform = put({"config": {}, "layers": []})
    statements = [
        {
            "predicateType": "https://slsa.dev/provenance/v0.2",
            "predicate": {
                "buildType": "https://mobyproject.org/buildkit@v1",
                "metadata": {
                    "https://mobyproject.org/buildkit@v1#metadata": {
                        "vcs": {
                            "revision": source,
                            "source": f"https://github.com/{REPO}",
                        }
                    }
                },
            },
        }
    ]
    if sbom:
        statements.append(
            {
                "predicateType": "https://spdx.dev/Document",
                "predicate": {"spdxVersion": "SPDX-2.3"},
            }
        )
    for statement in statements:
        statement["subject"] = [
            {"digest": {"sha256": platform[7:] if subject else "0" * 64}}
        ]
    attestation = put({"layers": [{"digest": put(s)} for s in statements]})
    index = put(
        {
            "manifests": [
                {
                    "digest": platform,
                    "platform": {"architecture": "amd64", "os": "linux"},
                },
                {
                    "digest": attestation,
                    "annotations": {
                        "vnd.docker.reference.type": "attestation-manifest",
                        "vnd.docker.reference.digest": platform,
                    },
                },
            ]
        }
    )
    return index, blobs


@pytest.mark.parametrize(
    "changes", [{}, {"source": "0" * 40}, {"subject": False}, {"sbom": False}]
)
def test_oci_subject_source_and_required_predicates(monkeypatch, changes):
    index, blobs = oci(**changes)

    def get(path, *_args, **_kwargs):
        return (
            (b"", {"token": "synthetic"})
            if path.startswith("/token?")
            else blobs[path.rsplit("/", 1)[1]]
        )

    monkeypatch.setattr(release, "registry_json", get)
    reference = "ghcr.io/example/allies-runtime@" + index
    if changes:
        with pytest.raises(release.ReleaseError):
            release.inspect_image(reference, SOURCE, REPO)
    else:
        assert set(release.inspect_image(reference, SOURCE, REPO)) == set(EVIDENCE)


def test_blob_redirect_does_not_forward_registry_credentials(monkeypatch):
    registry, storage = Mock(), Mock()
    registry.getresponse.return_value.status = 307
    registry.getresponse.return_value.getheader.return_value = (
        "https://pkg-containers.githubusercontent.com/blob?signature=synthetic"
    )
    storage.getresponse.return_value.status = 200
    storage.getresponse.return_value.read.return_value = b"{}"
    monkeypatch.setattr(
        release.http.client, "HTTPSConnection", Mock(side_effect=[registry, storage])
    )
    release.registry_json("/v2/example/image/blobs/sha256:abc", "Bearer synthetic")
    assert "Authorization" in registry.request.call_args.kwargs["headers"]
    assert "Authorization" not in storage.request.call_args.kwargs["headers"]
    registry.close.assert_called_once()
    storage.close.assert_called_once()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("repository", "other/repo"),
        ("release_id", "runtime-456"),
        ("workflow", ".github/workflows/other.yml"),
        ("validation", "failed"),
        ("attestations", {}),
    ],
)
def test_saved_candidate_identity_cannot_change(publishing, field, value):
    github, run, candidate, _root = publishing
    candidate()
    saved = json.loads(github.records["candidate.json"])
    saved[field] = value
    github.records["candidate.json"] = json.dumps(saved).encode()
    writes = list(github.writes)
    with pytest.raises(release.ReleaseError):
        run("prepare")
    assert github.writes == writes


def test_uncheckpointed_draft_and_changed_tag_fail_before_staging(publishing):
    github, run, candidate, _root = publishing
    candidate()
    saved = github.records.pop("candidate.json")
    with pytest.raises(release.ReleaseError, match="Incomplete draft"):
        run("prepare")
    github.records["candidate.json"] = saved
    github.tag["object"]["sha"] = "f" * 40
    with pytest.raises(release.ReleaseError, match="tag source"):
        run("prepare")


def test_oci_bytes_must_match_referenced_digest(monkeypatch):
    index, blobs = oci()

    def get(path, *_args, **_kwargs):
        if path.startswith("/token?"):
            return b"", {"token": "synthetic"}
        raw, value = blobs[path.rsplit("/", 1)[1]]
        return raw + b" ", value

    monkeypatch.setattr(release, "registry_json", get)
    with pytest.raises(release.ReleaseError, match="content digest"):
        release.inspect_image("ghcr.io/example/allies-runtime@" + index, SOURCE, REPO)
