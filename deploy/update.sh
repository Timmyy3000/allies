#!/bin/sh
# Update a self-hosted instance to the tip of its branch (default: nightly).
# Usage: deploy/update.sh [branch]
set -eu
cd "${ALLIES_DIR:-$(dirname "$0")/..}"
branch="${1:-nightly}"
git fetch -q origin "$branch"
git checkout -q -B "$branch" "origin/$branch"
hermes=services/foundry/runtime/hermes-image
rm -rf "$hermes/wheelhouse"
docker run --rm -v "$PWD/$hermes:/ctx" python:3.13-slim pip download -q \
    --only-binary=:all: --no-deps --require-hashes \
    --platform manylinux_2_28_x86_64 --python-version 313 --implementation cp --abi cp313 \
    --dest /ctx/wheelhouse -r /ctx/requirements.lock
cd deploy
sed -i "s|^HERMES_IMAGE=ghcr.io/alliesai/allies-hermes@.*|HERMES_IMAGE=allies/hermes:local|" .env
docker compose up -d --build --remove-orphans
for _ in $(seq 1 60); do
    if docker compose exec -T cloud python -c "import urllib.request; urllib.request.urlopen('http://cloud:8000/api/v1/health', timeout=3)" >/dev/null 2>&1; then
        echo "deployed $(git rev-parse --short HEAD) on $branch"
        exit 0
    fi
    sleep 5
done
echo "health check failed after deploying $(git rev-parse --short HEAD)" >&2
exit 1
