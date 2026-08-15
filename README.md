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

`.env.example` contains only the small local-development surface. Deployment
owners can use `.env.deploy.example` as a variable inventory for Railway staging
or production; real values belong in the deployment secret/configuration store.

Create Allies domain apps from the repository root as they become necessary:

```powershell
make app NAME=<domain>
```

Run `make help` for the available commands. The underlying Django and uv
commands remain available from `backend/` when a command needs to be run
directly.

## Staging operations

Cloud runs one codebase as web, Celery worker, and Celery beat processes. See
[`docs/operations/railway-staging.md`](docs/operations/railway-staging.md) for
the process commands, deployment order, health checks, and rollback boundary.
Railway IaC is local operator material and must never be committed or pushed.
