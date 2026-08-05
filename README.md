# Allies Cloud

Private managed-product control plane for Allies.

The Django application lives in `backend/`. Repository-wide deployment,
infrastructure, automation, and engineering configuration belongs at the
repository root.

## Development

```powershell
make sync
make migrate
make server
```

Create Allies domain apps from the repository root as they become necessary:

```powershell
make app NAME=<domain>
```

Run `make help` for the available commands. The underlying Django and uv
commands remain available from `backend/` when a command needs to be run
directly.
