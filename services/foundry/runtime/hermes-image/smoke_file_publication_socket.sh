#!/bin/sh
set -eu

image=${1:?Usage: smoke_file_publication_socket.sh IMAGE}
volume="allies-hermes-publication-socket-$$"
container="allies-hermes-publication-socket-$$"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
script="$script_dir/smoke_file_publication_socket.py"

cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

docker volume create "$volume" >/dev/null
docker run --detach --name "$container" --user 0 \
    --entrypoint /opt/hermes/.venv/bin/python \
    --mount "type=volume,src=$volume,dst=/opt/data,volume-nocopy" \
    --volume "$script:/tmp/smoke-file-publication-socket.py:ro" \
    "$image" /tmp/smoke-file-publication-socket.py server >/dev/null

attempt=0
while [ "$attempt" -lt 20 ]; do
    if docker exec "$container" test -S /opt/data/.allies-publication-bridge/socket; then
        break
    fi
    if [ "$(docker inspect --format '{{.State.Running}}' "$container")" != true ]; then
        docker logs "$container"
        exit 1
    fi
    attempt=$((attempt + 1))
    sleep 1
done
test "$attempt" -lt 20

docker run --rm --user 0 --entrypoint /bin/sh \
    --mount "type=volume,src=$volume,dst=/opt/data,volume-nocopy" \
    --volume "$script:/tmp/smoke-file-publication-socket.py:ro" \
    "$image" -ec '
        user=$(getent passwd 10000 | cut -d: -f1)
        test -n "$user"
        exec su -s /bin/sh "$user" -c "/opt/hermes/.venv/bin/python /tmp/smoke-file-publication-socket.py client"
    '

test "$(docker wait "$container")" = 0
echo "Publication bridge socket permissions passed."
