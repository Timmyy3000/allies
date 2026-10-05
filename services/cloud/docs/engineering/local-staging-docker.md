# Local staging with Docker

This setup runs the Cloud web process, Celery worker, Celery beat, PostgreSQL,
and Redis locally while loading application configuration from an ignored
`env.staging` file. It is intended for debugging staging-only behavior with
complete local logs; it is not a copy of Railway data.

## Prepare the environment

From the repository worktree root:

```powershell
Copy-Item env.staging.example env.staging
```

Replace the contents with the Backend service variables exported from Railway
staging. Never commit this file. Compose always replaces `DATABASE_URL` and
`CACHE_URL` with the local containers, turns off Railway proxy mode, and
disables native auth and R2. Compose also replaces the copied
`ALLIES_FOUNDRY_URL`, `ALLIES_FOUNDRY_SERVICE_TOKEN`, and
`ALLIES_FOUNDRY_EXECUTION_ENABLED` values with local-safe defaults; copied
Railway Foundry settings cannot silently route this stack to a remote service.
Foundry execution remains disabled unless explicitly opted in below. The greeting provider remains
disabled by default, but Compose honors an explicit
`ALLIES_WAITLIST_PROVIDER_ENABLED=true` in `env.staging` so the real onboarding
greeting can be tested locally. That setting calls the copied provider and may
incur provider usage; it does not connect to Railway product data.

For Google browser auth, keep the copied client ID and secret and add this
authorized redirect URI to the same Google OAuth web client:

```text
http://localhost:8000/api/v1/auths/callback/google
```

Compose supplies that redirect URI to Cloud. Configure the web frontend to use
`http://localhost:8000` as its Cloud API URL. Because both applications use the
`localhost` site, browser session cookies do not require third-party-cookie
exceptions.

Local debug logs include the provider's bounded rejection reason and a
sanitized OAuth error code when Google returns one. They never include the
authorization code, token payload, or provider error description.

## Run and inspect

```powershell
docker compose --env-file env.staging up --build
```

The API is available at `http://localhost:8000`; Compose binds it to loopback
only. Follow individual process logs without losing the other containers:

```powershell
docker compose logs --follow backend
docker compose logs --follow worker
docker compose logs --follow beat
```

Rebuild after dependency or image changes. Python source is bind-mounted, so a
container restart is enough for ordinary source changes:

```powershell
docker compose restart backend worker beat
```

After changing `env.staging` or a Compose environment override, recreate the
affected service instead of restarting it so the new values are loaded:

```powershell
docker compose --env-file env.staging up -d --force-recreate backend
```

## Connect a separately composed local Foundry

Compose does not use the similarly named Foundry URL, service token, or
execution flag from `env.staging`. This prevents a copied Railway environment
from selecting a remote Foundry or enabling execution. To deliberately connect
to a tunneled or separately composed local Foundry, set the `ALLIES_LOCAL_*`
overrides in the shell that starts Compose:

```powershell
$env:ALLIES_LOCAL_FOUNDRY_URL = "http://host.docker.internal:8100"
$env:ALLIES_LOCAL_FOUNDRY_SERVICE_TOKEN = "<same local value as Foundry ALLIES_CLOUD_SERVICE_TOKEN>"
$env:ALLIES_LOCAL_FOUNDRY_EXECUTION_ENABLED = "true"
docker compose --env-file env.staging up --build
```

Keep `ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN` in `env.staging` equal to the same
local-only event-delivery token configured in Foundry before enabling execution.
The example file contains a nonempty local placeholder for this shared token;
replace it with a private value for any real local run. Keep execution false
when only provisioning or handoff behavior is under test.

The debug-only gateway permits plain HTTP only for loopback, the Docker host,
or the `foundry` service name. Non-debug environments continue to require
HTTPS. Turn execution on only after the local Foundry exposes the execution
intent endpoints and its Fly runtime images are configured.

Stop containers while retaining local Postgres and Redis data:

```powershell
docker compose down
```

To deliberately remove only this Compose project's local database and Redis
volumes, run `docker compose down --volumes`.
