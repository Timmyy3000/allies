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
