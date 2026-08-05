# Allies Foundry

Open-source durable-agent runtime and orchestration service for Allies.

The Django application lives in `backend/`. Repository-wide deployment,
infrastructure, automation, SDKs, examples, and engineering configuration
belong at the repository root.

## Development

```powershell
make sync
make migrate
make server
```

Create Foundry domain apps from the repository root as they become necessary:

```powershell
make app NAME=<domain>
```

Run `make help` for the available commands. The underlying Django and uv
commands remain available from `backend/` when a command needs to be run
directly.
