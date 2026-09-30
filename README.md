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

For a containerized replica of the staging process topology with local
PostgreSQL and Redis, see
[`docs/engineering/local-staging-docker.md`](docs/engineering/local-staging-docker.md).

Run `make help` for the available commands. The underlying Django and uv
commands remain available from `backend/` when a command needs to be run
directly.

## Staging operations

Cloud runs one codebase as web, Celery worker, and Celery beat processes. See
[`docs/operations/railway-staging.md`](docs/operations/railway-staging.md) for
the process commands, deployment order, health checks, and rollback boundary.
Railway IaC is local operator material and must never be committed or pushed.

The content-free Ally runtime-intent endpoint accepts a validated native bearer
session or a browser session with trusted origin and CSRF. Native clients send
the same `composing_started` intent and stable idempotency key as web. Workspace
policy and the runtime-intent feature gate still control whether the hint wakes
compute; sending a message does not depend on hint success.

## Web/PWA push

Push uses the existing Cloud Celery worker/beat and additive notifications tables.
Apply migrations before enabling a compatible web client. Configure a stable
`ALLIES_PUSH_VAPID_PUBLIC_KEY` (unpadded base64url uncompressed P-256 point),
`ALLIES_PUSH_VAPID_PRIVATE_KEY` (base64url DER or raw private key), and
`ALLIES_PUSH_VAPID_CONTACT` (`mailto:` or HTTPS contact) in the deployment secret
store on backend, worker and beat. Existing `ALLIES_VAULT_KEYS` encrypts subscription
capabilities. Missing/invalid VAPID configuration disables push without affecting chat.
`ALLIES_PUSH_ENABLED=false` is the operational rollback switch; retain additive tables.

The narrow `/api/v1/workspaces/{workspace_id}/push` browser API requires workspace
membership, trusted origin and CSRF on mutations. Consent is per browser/workspace;
registration renewal uses a new binding UUID and `replaces_binding_id` CAS. Session
revocation erases private subscription material. Provider acceptance is best effort,
with at most three attempts; it does not prove device display. Endpoints are limited
to the reviewed Google FCM, Mozilla and Apple hosts. New provider hosts require review.

The locked `pywebpush` library owns Web Push encryption and VAPID. Its controlled
session disables proxies/redirects, rechecks public DNS addresses, uses a ten-second
request timeout and closes streamed responses without reading provider bodies.
Beat recovers missed queue nudges every minute. Cached foreground presence delays
rather than permanently suppresses an event; a newer visible heartbeat suppresses it.

Release acceptance still requires real provider/installed-device smoke on iOS Safari,
Android Chromium and desktop, including closed/hidden delivery, foreground behavior,
stale approvals, logout/account changes and safe conversation opening. Deterministic
provider fixtures and SQLite tests do not replace hosted PostgreSQL concurrency tests
or these device checks.
