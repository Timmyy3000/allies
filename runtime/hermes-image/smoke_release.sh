#!/bin/sh
set -eu

hermes=${1:?Usage: smoke_release.sh HERMES_IMAGE RUNTIME_IMAGE}
runtime=${2:?Usage: smoke_release.sh HERMES_IMAGE RUNTIME_IMAGE}

test "$(docker image inspect --format '{{.Config.Entrypoint}}' "$hermes")" = '[/opt/hermes/docker/entrypoint-dispatch.sh]'
docker run --rm --entrypoint /opt/hermes/.venv/bin/python "$hermes" \
    -c 'from plugins.memory import load_memory_provider; p=load_memory_provider("allies_mnemosyne"); assert p is not None; p.initialize("smoke-session", hermes_home="/tmp/ally-smoke", profile_root="/tmp/ally-smoke", agent_identity="ally-v1-00000000000000000000000000000001", agent_context="conversation", memory_mode="context_only", tools=[]); assert p.status()["available"] is True; assert p.get_tool_schemas() == []; assert p._delegate._beam.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000; print(p.status()); p.shutdown()'

for smoke in volume_boot file_publication_socket skills; do
    sh "runtime/hermes-image/smoke_${smoke}.sh" "$hermes"
done
for smoke in memory_routing reasoning_override bootstrap_endpoint activity_stream approval_endpoint; do
    docker run --rm --entrypoint /opt/hermes/.venv/bin/python \
        --volume "$PWD/runtime/hermes-image/smoke_${smoke}.py:/tmp/smoke.py:ro" \
        "$hermes" /tmp/smoke.py
done

test "$(docker image inspect --format '{{json .Config.Entrypoint}}' "$runtime")" = '["python","-m","allies_runtime"]'
docker run --rm --entrypoint python "$runtime" -c 'import allies_runtime'
DJANGO_DEBUG=true uv run --locked --project backend python scripts/check_runtime_identity.py "$runtime"
