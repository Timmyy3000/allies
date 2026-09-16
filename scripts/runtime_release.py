"""Write-once runtime release records and exact-digest promotion validation."""

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

VERSION = 1
WORKFLOW = ".github/workflows/runtime-publish.yml"
KEYS = {"HERMES_IMAGE": "allies-hermes", "RUNTIME_IMAGE": "allies-runtime"}
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
RELEASE_ID = re.compile(r"runtime-[1-9][0-9]{0,19}")


class ReleaseError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ReleaseError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def decode(raw, limit=65_536):
    require(len(raw) <= limit, "Release evidence exceeds size limit")
    try:
        value = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as exc:
        raise ReleaseError("Invalid JSON evidence") from exc
    require(isinstance(value, dict), "Expected JSON object")
    return value


def gh(*args, body=None, missing=False, binary=False):
    command = ["gh", *args]
    if body is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(body).encode() if body is not None else None,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        if missing and b"(HTTP 404)" in result.stderr:
            return None
        raise ReleaseError(
            "GitHub operation failed; inspect release state before retrying"
        )
    return result.stdout if binary else decode(result.stdout)


def record_pair(record, repository):
    require(isinstance(record, dict), "Missing image pair")
    require(set(record) == set(KEYS), "Expected exactly two image references")
    owner = repository.split("/")[0].lower()
    for key, name in KEYS.items():
        value = record[key]
        require(
            isinstance(value, str) and value.startswith(f"ghcr.io/{owner}/{name}@"),
            "Unexpected image repository",
        )
        require(
            DIGEST.fullmatch(value.removeprefix(f"ghcr.io/{owner}/{name}@")),
            "Expected immutable image digest",
        )
    return record


def validate(record, repository, release_id, *, final=False, source=None):
    require(
        record.get("schema_version") == VERSION
        and type(record.get("schema_version")) is int,
        "Unsupported release schema",
    )
    require(
        record.get("repository") == repository
        and record.get("release_id") == release_id,
        "Release identity mismatch",
    )
    require(
        isinstance(record.get("source_sha"), str)
        and SHA.fullmatch(record["source_sha"]),
        "Invalid source SHA",
    )
    require(source is None or record["source_sha"] == source, "Release source changed")
    require(
        record.get("workflow") == WORKFLOW
        and record.get("run_id") == release_id.removeprefix("runtime-"),
        "Publisher identity mismatch",
    )
    require(
        type(record.get("run_attempt")) is int and record["run_attempt"] > 0,
        "Invalid publisher attempt",
    )
    require(
        record.get("platform") == "linux/amd64"
        and record.get("validation") == "passed",
        "Release validation missing",
    )
    pair = record_pair(record.get("images"), repository)
    attestations = record.get("attestations")
    require(
        isinstance(attestations, dict) and set(attestations) == set(KEYS),
        "Missing attestation identities",
    )
    for evidence in attestations.values():
        require(
            isinstance(evidence, dict)
            and set(evidence) == {"image_manifest", "attestation_manifest"},
            "Invalid attestation identity",
        )
        require(
            all(isinstance(x, str) and DIGEST.fullmatch(x) for x in evidence.values()),
            "Invalid attestation digest",
        )
    if final:
        staging = record.get("staging")
        require(isinstance(staging, dict), "Missing staging evidence")
        require(
            staging.get("environment") == "staging"
            and staging.get("state") == "desired_config_verified"
            and staging.get("machine_adoption") == "not_verified"
            and staging.get("readback") == pair,
            "Staging evidence does not match release",
        )
        if staging.get("previous") is not None:
            previous = staging["previous"]
            require(
                isinstance(previous, dict)
                and set(previous) == set(KEYS)
                and all(
                    isinstance(v, str)
                    and re.fullmatch(r"[a-z0-9][a-z0-9._:/-]*@sha256:[0-9a-f]{64}", v)
                    for v in previous.values()
                ),
                "Invalid previous pair",
            )
        require(
            isinstance(staging.get("verified_at"), str)
            and 0 < len(staging["verified_at"]) <= 40,
            "Missing staging timestamp",
        )
        require(
            staging.get("run_id") == record["run_id"]
            and type(staging.get("run_attempt")) is int
            and staging["run_attempt"] >= record["run_attempt"],
            "Invalid staging run identity",
        )
    return record


def registry_json(path, token=None, *, limit=33_554_432):
    host = "ghcr.io"
    for hop in range(2):
        connection = http.client.HTTPSConnection(host, timeout=10)
        try:
            connection.connect()
            connection.sock.settimeout(30)
            headers = {
                "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/json"
            }
            if token:
                headers["Authorization"] = token
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status == 307 and hop == 0 and "/blobs/" in path:
                redirect = urlsplit(response.getheader("Location", ""))
                require(
                    redirect.scheme == "https"
                    and redirect.hostname == "pkg-containers.githubusercontent.com"
                    and redirect.port in (None, 443)
                    and not redirect.username
                    and not redirect.password,
                    "Unexpected registry blob redirect",
                )
                host, token = redirect.hostname, None
                path = redirect.path + ("?" + redirect.query if redirect.query else "")
                continue
            raw = response.read(limit + 1)
            require(
                response.status == 200,
                f"Registry evidence unavailable (HTTP {response.status})",
            )
            return raw, decode(raw, limit)
        except (OSError, http.client.HTTPException) as exc:
            raise ReleaseError("Registry request failed") from exc
        finally:
            connection.close()


def inspect_image(reference, source, repository):
    image, digest = reference.removeprefix("ghcr.io/").split("@")
    auth = None
    if os.environ.get("GH_TOKEN"):
        credentials = (
            f"{os.environ.get('GITHUB_ACTOR', 'token')}:{os.environ['GH_TOKEN']}"
        )
        auth = "Basic " + base64.b64encode(credentials.encode()).decode()
    _, token_response = registry_json(
        "/token?"
        + urlencode({"service": "ghcr.io", "scope": f"repository:{image}:pull"}),
        auth,
        limit=65_536,
    )
    token = token_response.get("token")
    require(
        isinstance(token, str) and 0 < len(token) < 16_384,
        "Invalid registry authorization response",
    )

    def get(kind, wanted):
        require(
            isinstance(wanted, str) and DIGEST.fullmatch(wanted), "Invalid OCI digest"
        )
        raw, value = registry_json(f"/v2/{image}/{kind}/{wanted}", "Bearer " + token)
        require(
            "sha256:" + hashlib.sha256(raw).hexdigest() == wanted,
            "OCI content digest mismatch",
        )
        return value

    index = get("manifests", digest)
    manifests = index.get("manifests", [])
    require(isinstance(manifests, list) and len(manifests) <= 8, "Invalid image index")
    platforms = [
        m
        for m in manifests
        if isinstance(m, dict)
        and m.get("platform") == {"architecture": "amd64", "os": "linux"}
    ]
    require(len(platforms) == 1, "Expected one linux/amd64 image")
    platform = platforms[0]["digest"]
    get("manifests", platform)
    attestations = [
        m
        for m in manifests
        if isinstance(m, dict)
        and m.get("annotations", {}).get("vnd.docker.reference.type")
        == "attestation-manifest"
        and m.get("annotations", {}).get("vnd.docker.reference.digest") == platform
    ]
    require(len(attestations) == 1, "Missing index-bound attestations")
    attestation = attestations[0]["digest"]
    layers = get("manifests", attestation).get("layers", [])
    require(isinstance(layers, list) and len(layers) <= 8, "Invalid attestation layers")
    predicates = set()
    provenance = False
    for layer in layers:
        require(isinstance(layer, dict), "Invalid attestation layer")
        statement = get("blobs", layer.get("digest"))
        require(
            any(
                isinstance(s, dict)
                and s.get("digest", {}).get("sha256")
                == platform.removeprefix("sha256:")
                for s in statement.get("subject", [])
            ),
            "Attestation subject mismatch",
        )
        kind = statement.get("predicateType")
        predicate = statement.get("predicate", {})
        if kind == "https://slsa.dev/provenance/v0.2":
            require(
                predicate.get("buildType") == "https://mobyproject.org/buildkit@v1",
                "Unexpected provenance builder",
            )
            vcs = (
                predicate.get("metadata", {})
                .get("https://mobyproject.org/buildkit@v1#metadata", {})
                .get("vcs", {})
            )
            require(
                vcs.get("revision") == source
                and vcs.get("source")
                in (
                    f"https://github.com/{repository}",
                    f"https://github.com/{repository}.git",
                    f"git@github.com:{repository}.git",
                ),
                "Provenance source mismatch",
            )
            provenance = True
        elif kind == "https://slsa.dev/provenance/v1":
            definition = predicate.get("buildDefinition", {})
            require(
                definition.get("buildType")
                == "https://github.com/moby/buildkit/blob/master/docs/attestations/slsa-definitions.md",
                "Unexpected provenance builder",
            )
            vcs = (
                definition.get("externalParameters", {})
                .get("request", {})
                .get("root", {})
                .get("request", {})
                .get("args", {})
            )
            require(
                vcs.get("vcs:revision") == source
                and vcs.get("vcs:source")
                in (
                    f"https://github.com/{repository}",
                    f"https://github.com/{repository}.git",
                    f"git@github.com:{repository}.git",
                ),
                "Provenance source mismatch",
            )
            provenance = True
        elif kind == "https://spdx.dev/Document":
            require(isinstance(predicate.get("spdxVersion"), str), "Invalid SBOM")
        predicates.add(kind)
    require(
        provenance and "https://spdx.dev/Document" in predicates,
        "Provenance or SBOM missing",
    )
    return {"image_manifest": platform, "attestation_manifest": attestation}


class Releases:
    def __init__(self, repository, release_id):
        require(
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository),
            "Invalid repository",
        )
        require(RELEASE_ID.fullmatch(release_id), "Invalid release ID")
        self.repository, self.release_id = repository, release_id
        self.api = f"repos/{repository}"

    def load(self):
        release = gh("api", f"{self.api}/releases/tags/{self.release_id}", missing=True)
        if release is None:
            return None, None, None
        require(release.get("tag_name") == self.release_id, "Release tag mismatch")
        records = []
        for name in ("candidate.json", "release.json"):
            assets = [a for a in release.get("assets", []) if a.get("name") == name]
            require(len(assets) <= 1, "Duplicate release asset")
            if not assets:
                records.append(None)
                continue
            asset = assets[0]
            require(
                type(asset.get("id")) is int
                and type(asset.get("size")) is int
                and 0 < asset["size"] <= 65_536,
                "Invalid release asset",
            )
            raw = gh(
                "api",
                f"{self.api}/releases/assets/{asset['id']}",
                "-H",
                "Accept: application/octet-stream",
                binary=True,
            )
            records.append(
                validate(
                    decode(raw),
                    self.repository,
                    self.release_id,
                    final=name == "release.json",
                )
            )
        candidate, final = records
        require(
            candidate is not None,
            "Incomplete draft: no saved candidate; use a new publish run",
        )
        tag = gh("api", f"{self.api}/git/ref/tags/{self.release_id}")
        require(
            tag.get("object", {}).get("sha") == candidate["source_sha"]
            and tag.get("object", {}).get("type") == "commit",
            "Release tag source mismatch",
        )
        if final:
            require(
                {k: v for k, v in final.items() if k != "staging"} == candidate,
                "Final release changed candidate",
            )
        require(
            release.get("draft") is True or final is not None,
            "Published release is incomplete",
        )
        return release, candidate, final

    def save_asset(self, name, record):
        directory = Path(os.environ["RELEASE_DIRECTORY"])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        require(len(raw) <= 65_536, "Release record too large")
        path.write_bytes(raw)
        gh(
            "release",
            "upload",
            self.release_id,
            str(path),
            "--repo",
            self.repository,
            binary=True,
        )


def verify_images(record):
    actual = {
        key: inspect_image(ref, record["source_sha"], record["repository"])
        for key, ref in record["images"].items()
    }
    require(actual == record["attestations"], "Saved attestation identity mismatch")


def outputs(mode, record=None):
    values = {"mode": mode}
    if record:
        values.update({key.lower(): value for key, value in record["images"].items()})
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as target:
        target.write("".join(f"{key}={value}\n" for key, value in values.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "candidate", "finalize", "promote")
    )
    parser.add_argument("--release-id")
    parser.add_argument("--hermes-image")
    parser.add_argument("--runtime-image")
    args = parser.parse_args()
    require(
        os.environ.get("GITHUB_REF") == "refs/heads/dev",
        "Only dev may publish or promote runtime releases",
    )
    repository = os.environ["GITHUB_REPOSITORY"]
    release_id = (
        args.release_id
        if args.command == "promote"
        else "runtime-" + os.environ["GITHUB_RUN_ID"]
    )
    store = Releases(repository, release_id or "")
    release, candidate, final = store.load()
    if args.command == "promote":
        require(
            release is not None and release.get("draft") is False and final is not None,
            "Choose a finalized runtime release",
        )
        verify_images(final)
        outputs("promote", final)
    elif args.command == "prepare":
        if candidate:
            validate(candidate, repository, release_id, source=os.environ["GITHUB_SHA"])
            verify_images(candidate)
        outputs(
            "complete"
            if final and not release["draft"]
            else "finalize"
            if final
            else "candidate"
            if candidate
            else "new",
            candidate,
        )
    elif args.command == "candidate":
        pair = record_pair(
            dict(zip(KEYS, (args.hermes_image, args.runtime_image))), repository
        )
        source = os.environ["GITHUB_SHA"]
        require(SHA.fullmatch(source), "Invalid source SHA")
        evidence = {
            key: inspect_image(ref, source, repository) for key, ref in pair.items()
        }
        if candidate:
            require(
                candidate["source_sha"] == source
                and candidate["images"] == pair
                and candidate["attestations"] == evidence,
                "Cannot overwrite candidate",
            )
            return
        record = {
            "schema_version": VERSION,
            "release_id": release_id,
            "repository": repository,
            "source_sha": source,
            "workflow": WORKFLOW,
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
            "platform": "linux/amd64",
            "images": pair,
            "attestations": evidence,
            "validation": "passed",
        }
        tag = gh("api", f"{store.api}/git/ref/tags/{release_id}", missing=True)
        require(tag is None, "Release tag already exists")
        gh(
            "api",
            f"{store.api}/git/refs",
            "--method",
            "POST",
            body={"ref": f"refs/tags/{release_id}", "sha": source},
        )
        gh(
            "api",
            f"{store.api}/releases",
            "--method",
            "POST",
            body={
                "tag_name": release_id,
                "target_commitish": source,
                "name": release_id,
                "draft": True,
                "prerelease": True,
                "make_latest": "false",
                "body": f"Runtime image pair from {source}. Staging configuration evidence only; machine adoption is separate.",
            },
        )
        store.save_asset("candidate.json", record)
        require(store.load()[1] == record, "Candidate readback mismatch")
    elif args.command == "finalize":
        require(candidate is not None, "Missing validated candidate")
        validate(candidate, repository, release_id, source=os.environ["GITHUB_SHA"])
        if not final:
            receipt = decode(
                (Path(os.environ["RELEASE_DIRECTORY"]) / "receipt.json").read_bytes()
            )
            receipt["verified_at"] = datetime.now(timezone.utc).isoformat()
            receipt["run_id"] = os.environ["GITHUB_RUN_ID"]
            receipt["run_attempt"] = int(os.environ["GITHUB_RUN_ATTEMPT"])
            final = {**candidate, "staging": receipt}
            validate(final, repository, release_id, final=True)
            store.save_asset("release.json", final)
            require(store.load()[2] == final, "Final release readback mismatch")
        if release["draft"]:
            gh(
                "api",
                f"{store.api}/releases/{release['id']}",
                "--method",
                "PATCH",
                body={"draft": False, "make_latest": "false"},
            )
        verified, _, saved = store.load()
        require(
            verified["draft"] is False and saved == final,
            "Release publication not verified",
        )
    if args.command in ("finalize", "promote"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(
                f"\nRuntime release: [{release_id}](https://github.com/{repository}/releases/tag/{release_id})\n"
            )


if __name__ == "__main__":
    try:
        main()
    except (
        ReleaseError,
        OSError,
        subprocess.SubprocessError,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
    ) as error:
        print(
            str(error)
            if isinstance(error, ReleaseError)
            else "Runtime release operation failed safely",
            file=sys.stderr,
        )
        sys.exit(1)
