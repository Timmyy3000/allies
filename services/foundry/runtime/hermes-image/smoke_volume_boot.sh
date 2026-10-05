#!/bin/sh
set -eu

image=${1:?Usage: smoke_volume_boot.sh IMAGE}
volume="allies-hermes-boot-$$"
container="allies-hermes-boot-$$"
cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

docker volume create "$volume" >/dev/null
# Disable Docker's image-to-volume copy so this models a fresh provider disk.
docker run --rm --user 0 --entrypoint /bin/sh \
    --mount "type=volume,src=$volume,dst=/opt/data,volume-nocopy" \
    "$image" -ec 'chown 0:0 /opt/data; chmod 0755 /opt/data'

docker run --detach --name "$container" \
    --mount "type=volume,src=$volume,dst=/opt/data,volume-nocopy" \
    "$image" sh -ec '
        test "$(id -u)" = 10000
        test "$(stat -c %u /opt/data)" = 0
        test "$(stat -c %a /opt/data)" = 1777
        mkdir -p /opt/data/logs /opt/data/sessions /opt/data/.allies-secrets
        printf ready > /opt/data/.allies-boot-smoke
        sleep 120
    ' >/dev/null

attempt=0
while [ "$attempt" -lt 60 ]; do
    if docker exec --user 10000 "$container" \
        sh -ec 'test "$(cat /opt/data/.allies-boot-smoke)" = ready' 2>/dev/null; then
        break
    fi
    if [ "$(docker inspect --format '{{.State.Running}}' "$container")" != true ]; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 1
done

if [ "$attempt" -lt 60 ]; then
    docker exec --user 0 "$container" sh -ec '
        : > /opt/data/.allies-volume-boundary-probe
        chown 0:0 /opt/data/.allies-volume-boundary-probe
        chmod 0600 /opt/data/.allies-volume-boundary-probe
    '
    docker exec --user 10000 "$container" sh -ec '
        test "$(stat -c %u /opt/data)" = 0
        test "$(stat -c %a /opt/data)" = 1777
        printf writable > /opt/data/.allies-user-write-probe
        if rm -f /opt/data/.allies-volume-boundary-probe; then
            exit 1
        fi
        if mv /opt/data/.allies-volume-boundary-probe /opt/data/.allies-volume-boundary-probe-moved; then
            exit 1
        fi
    '
    echo "Fresh-volume initialization and root-owned metadata boundary passed."
    exit 0
fi
docker logs "$container"
echo "Hermes did not initialize the fresh volume as a non-root service." >&2
exit 1
