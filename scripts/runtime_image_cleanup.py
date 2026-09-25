"""Delete runtime image versions that no environment, recent release, or young build needs."""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "integrations" / "railway"))

import runtime_release as release
import update_runtime_images as live_config

KEEP_RELEASES = 5
KEEP_DAYS = 14
MAX_PAGES = 20
MAX_DELETIONS = 300
require = release.require


def package_api(owner, package):
    kind = "orgs" if release.gh("api", f"orgs/{owner}", missing=True) else "users"
    return f"{kind}/{owner}/packages/container/{package}/versions"


def list_versions(api):
    versions = []
    for page in range(1, MAX_PAGES + 1):
        batch = release.gh(
            "api",
            f"{api}?per_page=100&page={page}",
            collection=True,
            limit=4_194_304,
        )
        versions += batch
        if len(batch) < 100:
            return versions
    raise release.ReleaseError("Too many package versions to inspect in one run")


def recent_release_pairs(repository):
    releases = release.gh(
        "api",
        f"repos/{repository}/releases?per_page=100",
        collection=True,
        limit=4_194_304,
    )
    finalized = sorted(
        (
            item
            for item in releases
            if not item.get("draft")
            and release.RELEASE_ID.fullmatch(str(item.get("tag_name", "")))
        ),
        key=lambda item: item["created_at"],
        reverse=True,
    )[:KEEP_RELEASES]
    pairs = []
    for item in finalized:
        _, _, final = release.Releases(repository, item["tag_name"]).load()
        require(final is not None, "Finalized release has no release record")
        pairs.append(final["images"])
    return pairs


def live_pairs(repository):
    project = str(UUID(os.environ["RAILWAY_PROJECT_ID"]))
    pairs = []
    for environment in ("staging", "production"):
        pair = live_config.read_pair(project, environment)
        require(pair is not None, f"No live image pair for {environment}")
        pairs.append(release.record_pair(pair, repository))
    return pairs


def child_digests(image, digest, token):
    index = release.registry_manifest(image, digest, token)
    manifests = index.get("manifests", [])
    require(isinstance(manifests, list) and len(manifests) <= 16, "Invalid image index")
    return {m["digest"] for m in manifests if isinstance(m, dict) and "digest" in m}


def plan(versions, pinned, image, now, *, children=child_digests):
    """Split versions into (keep, delete); untagged children follow their index."""
    cutoff = now - timedelta(days=KEEP_DAYS)
    keep, delete = [], []

    def created(version):
        return datetime.fromisoformat(version["created_at"].replace("Z", "+00:00"))

    tagged = [v for v in versions if v["metadata"]["container"]["tags"]]
    untagged = [v for v in versions if not v["metadata"]["container"]["tags"]]
    token = release.registry_token(image) if tagged else None
    referenced = set()
    for version in tagged:
        if version["name"] in pinned or created(version) >= cutoff:
            keep.append(version)
            referenced |= children(image, version["name"], token)
        else:
            delete.append(version)
    for version in untagged:
        if (
            version["name"] in pinned
            or version["name"] in referenced
            or created(version) >= cutoff
        ):
            keep.append(version)
        else:
            delete.append(version)
    return keep, delete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="Delete; default lists")
    args = parser.parse_args()
    repository = os.environ["GITHUB_REPOSITORY"]
    owner = repository.split("/")[0].lower()
    pairs = live_pairs(repository) + recent_release_pairs(repository)
    now = datetime.now(timezone.utc)
    summary = []
    plans = []
    for package in release.KEYS.values():
        image = f"{owner}/{package}"
        pinned = {
            ref.split("@")[1]
            for pair in pairs
            for ref in pair.values()
            if ref.startswith(f"ghcr.io/{image}@")
        }
        require(pinned, f"Nothing pinned for {package}; refusing to clean")
        api = package_api(owner, package)
        keep, delete = plan(list_versions(api), pinned, image, now)
        require(
            not pinned - {v["name"] for v in keep},
            f"A pinned {package} digest is missing from the registry",
        )
        plans.append((api, delete))
        summary.append(
            {
                "package": package,
                "keep": len(keep),
                "delete": [
                    {"name": v["name"], "tags": v["metadata"]["container"]["tags"]}
                    for v in delete
                ],
            }
        )
    total = sum(len(delete) for _, delete in plans)
    require(total <= MAX_DELETIONS, f"Refusing to delete {total} versions in one run")
    mode = "delete" if args.delete else "dry-run"
    print(json.dumps({"mode": mode, "packages": summary}, indent=2))
    if args.delete:
        for api, delete in plans:
            for version in delete:
                release.gh("api", "-X", "DELETE", f"{api}/{version['id']}", binary=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (
        release.ReleaseError,
        live_config.PairUpdateError,
        KeyError,
        ValueError,
    ) as exc:
        print(f"Cleanup stopped: {exc}", file=sys.stderr)
        sys.exit(1)
