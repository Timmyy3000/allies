# Local Foundry with Fly

This setup runs the Foundry control plane and its PostgreSQL database locally.
Foundry may still create or inspect runtime resources in the configured Fly
account. Cloud and Interface remain local.

## Prerequisites

- Docker Desktop with Compose and BuildKit enabled.
- A Fly account and permission to create an app, one volume, and one Machine.
- Immutable, multi-container-compatible Hermes and runtime images. Use
  `@sha256:` image references; mutable tags make a local proof hard to repeat.
- A tunnel client such as `cloudflared` or `ngrok`. Fly Machines cannot reach
  `localhost` or `host.docker.internal` on the developer machine.

## Prepare the ignored environment

```powershell
Copy-Item env.fly.local.example env.fly.local
fly tokens create org --org <slug> --expiry 168h --name "Foundry local Docker"
```

Paste the returned short-lived token into `FLY_API_TOKEN` in `env.fly.local`.
Replace the example `DJANGO_SECRET_KEY` with a strong random local value before starting Compose.
If using a temporary HTTPS tunnel, append its hostname (without the scheme) to
`DJANGO_ALLOWED_HOSTS` in `env.fly.local`; the default above covers local
health checks only.
Set `FLY_ORG`, `FLY_REGION`, `RUNTIME_IMAGE`, and `HERMES_IMAGE`. The Fly
multi-container and file-secret capabilities default to enabled; set
`FLY_MULTI_CONTAINER_ENABLED=false` or `FLY_FILE_SECRETS_ENABLED=false` only
when deliberately disabling those capabilities. Set a
strong `ALLIES_CLOUD_SERVICE_TOKEN` and the profile provider API key used only
to stage the local proof secrets. Never commit this file.

The remote Machine must call the local control plane through a public HTTPS
origin. Start a temporary tunnel from the host to the loopback-only Compose
port:

```powershell
cloudflared tunnel --url http://127.0.0.1:8100
```

Copy the resulting `https://...` origin (without a path, query, or fragment)
to `FOUNDRY_ORIGIN` in `env.fly.local`. Do not use `http://localhost`,
`127.0.0.1`, `host.docker.internal`, or an origin that includes a route.
Keep the tunnel running for the entire activation and verification session.

## Start the control plane

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8100/healthz
```

Foundry is available to the host at `http://127.0.0.1:8100`. The loopback
binding prevents another machine on the LAN from reaching the control port.
A separately composed Cloud container reaches it at
`http://host.docker.internal:8100`; that address is for local Cloud only, not
for a Fly Machine.

If values in `env.fly.local` change after the containers were created, recreate
the services so Compose reloads the file:

```powershell
docker compose up -d --force-recreate foundry event-publisher
```

## Register and activate one workspace

`workspace_id` is the Cloud workspace UUID (the UUID shown in Cloud), not the
Foundry `Workspace.id`, Fly app name, Fly organization, or Ally ID. Cloud
normally registers this row when it connects to Foundry. For a local-only run,
register it explicitly:

```powershell
$workspaceId = "<Cloud workspace UUID>"
docker compose exec foundry uv run --no-sync python manage.py shell -c "from runtime.services.workspaces import register_workspace; print(register_workspace('$workspaceId').tenant_ref)"
```

The command accepts that Cloud UUID as the tenant reference, then Foundry
assigns its own internal `Workspace.id`; Fly names are derived from the latter.
Use the recorded `fly_app_ref`, `volume_ref`, and `machine_ref` below when
inspecting or cleaning up. Do not recompute a Fly name from `$workspaceId`.

Run the activation command with that same UUID:

```powershell
docker compose exec foundry uv run --no-sync python manage.py activate_fly_workspace $workspaceId
```

Activation creates or resumes the exact deterministic Fly app, volume, and
Machine for this workspace. A transient failure may leave a resumable phase;
fix the prerequisite (often the tunnel or image), then rerun the same command.
The command retains credentials when a Machine may already exist.

## Verify readiness and origin

The command only reports an already-active generation after it inspects the
recorded Machine and confirms it is started with both `hermes` and
`allies-runtime` containers started. Verify the durable record and provider
state as well:

```powershell
docker compose exec foundry uv run --no-sync python manage.py shell -c "from runtime.models import Workspace; w=Workspace.objects.get(tenant_ref='$workspaceId'); print({'phase': w.provisioning_phase, 'generation': w.machine_generation, 'machine': w.machine_ref})"
$app = docker compose exec foundry uv run --no-sync python manage.py shell -c "from runtime.models import Workspace; print(Workspace.objects.get(tenant_ref='$workspaceId').fly_app_ref)"
fly machine list --app $app
fly machine status <recorded-machine-id> --app $app
Invoke-RestMethod http://127.0.0.1:8100/healthz
Invoke-RestMethod "$env:FOUNDRY_ORIGIN/healthz"
```

The last request must succeed through the tunnel. A local health check alone
does not prove that a Fly Machine can authenticate to or reach Foundry.

## Deactivate or roll back an abandoned activation

Activation deliberately does not destroy a resumable partial workspace. Rerun
activation first. If the run is intentionally abandoned, stop local delivery,
then use this single-workspace rollback in order. It revokes only credentials
belonging to the recorded workspace and uses only provider IDs read from that
workspace; it does not perform wildcard or organization-wide cleanup.

First capture the durable record before stopping local delivery:

```powershell
$workspaceState = docker compose exec -T foundry uv run --no-sync python manage.py shell -c "from runtime.models import Workspace; w=Workspace.objects.get(tenant_ref='$workspaceId'); print({'workspace': str(w.id), 'phase': w.provisioning_phase, 'generation': w.machine_generation, 'app': w.fly_app_ref, 'volume': w.volume_ref, 'machine': w.machine_ref})"
$workspaceState
docker compose stop event-publisher
```

If a Machine ID is recorded, stop that exact Machine and verify that the
provider reports it stopped before revoking its runtime credentials:

```powershell
fly machine list --app <recorded-app>
fly machine stop <recorded-machine-id> --app <recorded-app>
fly machine status <recorded-machine-id> --app <recorded-app>
```

If any recorded reference is missing, or the provider returns an unexpected
resource, stop here: do not guess an ID or run a destroy command. Keep the App
and Workspace row for investigation or rerun activation after correcting the
provider state.

Once the Machine is stopped (or the exact Machine is already absent), revoke
the workspace's active runtime credentials through Foundry's existing service
function. This is deliberately scoped by the Cloud workspace UUID:

```powershell
docker compose exec -T foundry uv run --no-sync python manage.py shell -c "from runtime.models import RuntimeCredential, Workspace; from runtime.services.runtime_auth import revoke_runtime_credential; w=Workspace.objects.get(tenant_ref='$workspaceId'); credentials=list(RuntimeCredential.objects.filter(workspace=w, revoked_at__isnull=True)); [revoke_runtime_credential(c.id) for c in credentials]; print(f'Revoked {len(credentials)} credential(s)')"
```

If the app is being retained for investigation, inspect its secrets and unset
only exact names confirmed to be owned by this workspace:

```powershell
fly secrets list --app <recorded-app>
fly secrets unset <exact-owned-ALLIES_FND008-secret-name> --app <recorded-app>
```

For a complete rollback, destroy only the stopped recorded Machine, wait for
it to disappear and its recorded Volume to detach, then delete that Volume
and finally the recorded App. Confirm each target immediately before running
the destructive command. Before deleting the App, its lists must contain no
other Machine or Volume; if they do, stop. `fly apps destroy` is intentionally
left interactive:

```powershell
fly machine destroy <recorded-machine-id> --app <recorded-app>
fly machine list --app <recorded-app>
fly volume list --app <recorded-app>
fly volume destroy <recorded-volume-id> --app <recorded-app>
fly apps destroy <recorded-app>
```

Keep the local Workspace row after rollback so its phase and generation remain
available for investigation. Do not delete it as part of this procedure.
Stopping Docker alone does not revoke credentials or delete Fly resources.

## Cloud settings

Set these in Cloud's ignored `env.staging`, then recreate the Cloud services:

```dotenv
ALLIES_FOUNDRY_URL=http://host.docker.internal:8100
ALLIES_FOUNDRY_SERVICE_TOKEN=<same value as Foundry ALLIES_CLOUD_SERVICE_TOKEN>
ALLIES_FOUNDRY_EXECUTION_ENABLED=true
```

```powershell
docker compose up -d --force-recreate backend worker beat
```

## Safety boundary

- PostgreSQL data stays in the local Compose volume. Do not substitute a
  staging or production `DATABASE_URL`.
- `FLY_API_TOKEN` authorizes real account operations. Creating an Ally or
  running lifecycle proof commands can create billable Apps, Volumes, and
  Machines.
- Stopping Docker does not delete Fly resources. Follow the bounded cleanup
  procedure above and inspect the Fly dashboard after a failed test.
