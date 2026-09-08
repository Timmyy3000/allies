#!/bin/sh
set -eu

image=${1:?Usage: smoke_skills.sh IMAGE}
volume="allies-skills-smoke-$$"
script="$(cd "$(dirname "$0")" && pwd)/smoke_skills.py"
trap 'docker volume rm "$volume" >/dev/null 2>&1 || true' EXIT HUP INT TERM
docker volume create "$volume" >/dev/null
docker run --rm --user 0 --entrypoint /bin/sh \
    --mount "type=volume,src=$volume,dst=/opt/data,volume-nocopy" \
    "$image" -ec 'chown 10000:10000 /opt/data'
for phase in create verify; do
    docker run --rm --user 10000:10000 \
        --mount "type=volume,src=$volume,dst=/opt/data,volume-nocopy" \
        --volume "$script:/tmp/smoke-skills.py:ro" \
        --entrypoint /opt/hermes/.venv/bin/python "$image" \
        /tmp/smoke-skills.py --root /opt/data/skills-smoke --phase "$phase"
done
