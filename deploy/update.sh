#!/bin/sh
# Update a self-hosted instance to the tip of its branch (default: nightly).
# Usage: deploy/update.sh [branch]
set -eu
cd "${ALLIES_DIR:-$(dirname "$0")/..}"
branch="${1:-nightly}"
git fetch -q origin "$branch"
git checkout -q -B "$branch" "origin/$branch"
cd deploy
docker compose up -d --build --remove-orphans
for _ in $(seq 1 60); do
    if docker compose exec -T cloud python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=3)" >/dev/null 2>&1; then
        echo "deployed $(git rev-parse --short HEAD) on $branch"
        exit 0
    fi
    sleep 5
done
echo "health check failed after deploying $(git rev-parse --short HEAD)" >&2
exit 1
