# Allies Foundry

Open-source durable-agent runtime and orchestration service for Allies.

The Django application lives in `backend/`. Repository-wide deployment,
infrastructure, automation, SDKs, examples, and engineering configuration
belong at the repository root.

For a Docker-based local control plane that can use a real Fly account, see
[`docs/operations/local-fly-docker.md`](docs/operations/local-fly-docker.md).

## Development

POSIX shells:

```sh
export DJANGO_DEBUG=true
make sync
make migrate
make server
```

PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
make sync
make migrate
make server
```

Run the full validation command from the repository root. In a POSIX shell:

```sh
DJANGO_DEBUG=true \
uv run --locked --project backend python scripts/validate.py
```

In PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
uv run --locked --project backend python scripts/validate.py
```

The Make convenience target is equivalent. In a POSIX shell:

```sh
DJANGO_DEBUG=true make validate
```

In PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
make validate
```

Create Foundry domain apps from the repository root as they become necessary:

POSIX shells:

```sh
DJANGO_DEBUG=true make app NAME=<domain>
```

PowerShell:

```powershell
$env:DJANGO_DEBUG = "true"
make app NAME=<domain>
```

Run `make help` for the available commands. The underlying Django and uv
commands remain available from `backend/` when a command needs to be run
directly.

File input and publication default on in both the backend and runtime. Set
`ALLIES_RUNTIME_FILE_INPUT_ENABLED=false` or
`ALLIES_RUNTIME_FILE_PUBLICATION_ENABLED=false` only to disable that capability.
The backend reuses `ALLIES_CLOUD_URL` and `ALLIES_CLOUD_EVENT_SERVICE_TOKEN`;
runtime machines use their existing Foundry connection and credential reference.
No storage credentials belong in Hermes or runtime configuration.
Production requires the Cloud connection; debug-only checks may run without it,
but file requests still fail safely until the connection is configured.
The publication socket requires the root runtime service identity; an
unprivileged worker leaves shared bridge state untouched and publication unavailable.
The deployment entrypoint retains root for the trusted runtime and its private
credential files. Hermes runs separately as UID 10000 and cannot modify the
runtime-owned publication state.

## Selected-turn stop compatibility

The authenticated internal conversation stop request requires `workspace_id`
and `message_id` UUIDs in its JSON body. Cloud selects and authorizes the
message before sending this request. Conversation-only requests are rejected.
Apply the `message_stop_fence` migration before upgrading Foundry, then upgrade
Cloud's gateway and the compatible runtime worker before enabling Stop/Steer.
The browser contract is unchanged.

Foundry retains the workspace/conversation/message stop identity for the
workspace lifetime. A delayed or replayed admission creates cancelled work
and its stopped event, rather than runnable work. Terminal executions remain
terminal, and a stop never targets a successor message. Runtime workers close
the producer before acknowledging a stopped lease.
