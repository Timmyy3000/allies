# Cloud staging readiness plan

## Feature overview

- Problem: Allies Cloud's authentication foundation is merged, but four review gaps remain and the repository cannot yet run its production process types on Railway.
- Target users: Allies engineers operating Cloud staging, Interface engineers consuming its API contract, and future Cloud features that need a reliable worker and scheduler boundary.
- Source docs/specs: AUTH-001, the Allies technical architecture and backend guide, the PR #5 peer review, Railway IaC reference, Railway Django guide, and `ENGINEERING_STYLE.md`.
- Success outcome: one follow-up PR closes the review gaps while local, uncommitted Railway IaC provisions the staging topology. The deployed branch runs a healthy web process, worker, beat scheduler, Postgres, and Redis without committed infrastructure configuration or secrets.

## User stories

1. As an Interface engineer, I want complete response schemas, statuses, and examples in OpenAPI so I can integrate without inferring error behavior.
2. As an operator, I want unexpected failures logged privately and health/readiness exposed safely so I can diagnose staging without leaking internal errors.
3. As an operator, I want expired auth artifacts cleaned automatically through a retry-safe scheduled task.
4. As an Allies operator, I want Railway resources described in local IaC so the staging change can be planned, applied, and checked for drift without committing or pushing Railway configuration.

## Scope

### In scope

- Log unexpected API exceptions before returning the generic 500 envelope.
- Add missing `403` route declarations and explicit complete-envelope OpenAPI examples.
- Update current Cloud and canonical AUTH-001 documentation from account-model `Actor` terminology to `User`.
- Add Gunicorn, WhiteNoise, and Celery dependencies; production static handling; Celery application configuration; a worker entry point; beat schedule; cleanup service; and cleanup task.
- Add a dependency-aware health endpoint for Railway.
- Add an explicit Railway ingress mode with tests that preserve conservative client-IP handling.
- Create `.railway/railway.ts` and generated support files as local operational artifacts excluded through Git's local `info/exclude`; never stage, commit, or push them.
- Create and verify the `cloud` Railway project and `staging` environment with web, worker, beat, Postgres, Redis, and a generated web domain.
- Update Railway/operator deployment and rollback documentation.

### Out of scope

- Live Google OAuth, ChatGPT sign-in, custom domains, Interface deployment, Cloudflare R2 provisioning, and avatar smoke tests.
- Production environment creation or production traffic.
- General Celery task architecture, database-backed schedules, result storage, dashboards, autoscaling, or the `OBS-001` SigNoz deployment.
- Changes to Foundry, Fly, Hermes, conversation flows, or tenant runtime infrastructure.
- PostgreSQL extensions or database tuning.

### Dependencies and assumptions

- Railway workspace `allies` remains the target billing/team boundary.
- The new project is named `cloud`; the first environment is `staging`.
- Web, worker, and beat connect only to the `staging` Git branch. The existing `Promote Dev → Staging` workflow validates `dev`, merges the validated revision into `staging`, and triggers Railway's automatic deployment. Feature and pull-request branches are never persistent staging sources.
- Staging runs one replica per application service in Railway's Europe region where configurable.
- Railway-provided private database variables connect the application to Postgres and Redis.
- Google and R2 feature flags stay false, so their missing credentials do not block staging startup.
- Secret values are generated or supplied through Railway and referenced through shared or preserved variables. They never appear in IaC source or tool output.
- Railway IaC follows the Foundry pattern: `.railway/` remains local and is excluded through `.git/info/exclude`, not a committed repository `.gitignore` rule. The follow-up PR contains application code, tests, and ordinary documentation only.
- The Allies Railway workspace owner owns recurring staging spend. The minimal topology is reviewed monthly while staging is active; increasing replicas or adding paid resources requires separate approval.
- The deployment must prove the exact immutable commit promoted into `staging`. Web, worker, and beat must report that same revision.

## Contract and shape definitions

### Function and service shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/auths/services/cleanup.py` | `cleanup_auth_artifacts` | `cleanup_auth_artifacts(*, batch_size: int = 100) -> CleanupResult` | `1 <= batch_size <= 100` | Counts for flows, refresh tokens, avatars, and failures | Deletes bounded expired records and eligible avatar objects; partial avatar failure is explicit |
| `backend/auths/tasks.py` | `cleanup_auth_artifacts_task` | `cleanup_auth_artifacts_task() -> dict[str, int]` | No caller payload | Serializable cleanup counts for safe logging; result is not persisted | Retries one database/infrastructure exception; counted per-object avatar failures reconcile on the next run |
| `backend/config/health.py` | `check_health` | `check_health(*, total_budget: float | None = None) -> HealthResult` | Optional remaining endpoint budget; operation budget is strictly below the total budget | Generic healthy/unavailable state | Applies the remaining endpoint deadline to database connection and Redis socket operations; emits at most one detailed health traceback per process per minute and never returns internal addresses or exceptions |
| `backend/config/api.py` | `_unhandled_error` | existing handler | Any unexpected exception | Standard `ErrorResponse[ErrorData]` with `internal_error` | Logs traceback with request method/path and no request body, cookies, or credentials |

### API and transport contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Railway/operator | `GET /api/v1/health` | Public, contains no private metadata | None | `SuccessResponse[HealthResponse]` | `429 ErrorResponse[ErrorData]` outside Railway mode; `503 ErrorResponse[ErrorData]`; retry after dependency recovery |
| Interface | Existing mutating auth routes | Existing CSRF, origin, session rules | Unchanged | Existing success envelopes | Add documented `403` wherever `_require_origin` can reject the request |
| Celery beat | task `auths.cleanup_auth_artifacts` | Internal Redis broker only | Empty task payload | Cleanup counts are logged safely; the result backend is disabled | One bounded retry; the next beat run provides reconciliation |

Representative health success:

```json
{
  "status": "success",
  "message": "Service healthy",
  "data": {"state": "healthy"}
}
```

Representative health failure:

```json
{
  "status": "error",
  "message": "Service unavailable",
  "data": {"code": "service_unavailable"}
}
```

OpenAPI examples for existing schemas must show the complete envelope rather than only nested data. Example values remain fictional and contain no provider payload, token, cookie, email, object key, or credential.

The implementation first generates an inventory of every operation guarded by `_require_origin` and every public response-envelope schema. The OpenAPI regression test fails if any inventoried operation omits `403` or any public envelope lacks its fixed, reviewed, sanitized complete example. Tests assert the approved example shapes and values directly. This is exhaustive coverage, not a selected-route sample.

### Schema and data shapes

| Schema/config | Location | Fields and types | Required/defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| `HealthResponse` | `backend/config/schemas.py` or existing API schema home | `state: Literal["healthy"]` | Required | Never includes dependency names, URLs, or exception text | Additive endpoint |
| `CleanupResult` | cleanup service | integer counts | All counts present and non-negative | `failures > 0` is operational failure | Internal typed result |
| Celery configuration | `backend/config/settings.py` | broker URL, serializer allowlist, UTC, acknowledgement/retry settings, static beat schedule | Broker uses Redis database 1, separate from cache database 0; task results ignored | JSON-only task payloads; one beat replica | New process capability, no model migration |
| Railway resources | local `.railway/railway.ts` | web, worker, beat, Postgres, Redis | One staging replica each | web has healthcheck and migration command; beat is singleton | Local desired state, never committed or pushed |

### Railway service shape

| Resource | Source/start | Dependencies | Key configuration |
| --- | --- | --- | --- |
| `web` | `staging` branch; collect static files, then `uv run gunicorn config.wsgi:application` from `backend/` | Postgres, Redis | migration pre-deploy, parameterized gthread limits, stdout logs, `/api/v1/health`, restart on failure, generated domain |
| `worker` | Same `staging` source; `uv run celery -A config.celery:app worker` | Postgres, Redis | prefork, fair single-message prefetch, bounded child lifetime, one staging replica, no public domain |
| `beat` | Same `staging` source; `uv run celery -A config.celery:app beat` | Postgres, Redis | exactly one replica, ephemeral schedule file, no public domain |
| `postgres` | Railway managed Postgres | None | private connection reference only |
| `redis` | Railway managed Redis | None | private broker/cache reference only |

The local IaC file references Railway-managed database variables and existing sealed/shared application secrets. Project and environment bootstrap remain CLI operations because Railway IaC applies inside an existing linked project/environment. The `.railway/` directory stays in the operator worktree and Git's local exclude file prevents it from appearing in the PR.

### Runtime dependency assessment

The staging process boundary adds three direct runtime dependencies, each pinned
by the lockfile and bounded by the project version ranges:

| Dependency | Current use | Maintenance/security assessment | Owner |
| --- | --- | --- | --- |
| Celery 5.6.x with Redis extra | Worker and singleton beat process, JSON-only task transport, bounded retries | Mature BSD-licensed project with active upstream releases; `pip-audit --local` reports no known vulnerabilities for the locked environment. Review Celery and its transitive broker packages on every lock refresh. | Cloud platform maintainers |
| Gunicorn 23.x | Production WSGI process with bounded workers, threads, timeouts, and request recycling | Mature MIT-licensed WSGI server with active releases; `pip-audit --local` reports no known vulnerabilities for the locked environment. Keep the worker model and timeout flags reviewed with framework upgrades. | Cloud platform maintainers |
| WhiteNoise 6.12.x | Immutable static-file serving from the Django web process | Mature MIT-licensed project with a small runtime surface; `pip-audit --local` reports no known vulnerabilities for the locked environment. Recheck cache/header behavior when static storage changes. | Cloud platform maintainers |

The assessment covers direct runtime use and the locked transitive tree; it is
not a blanket waiver for future dependency updates. A lockfile refresh must
repeat the advisory/license review before deployment.

### Process commands

The existing deployment provides useful production defaults, but Allies must use its own `config` module, uv-managed environment, smaller staging concurrency, and complete queue name.

Pre-deploy, from `backend/`:

```text
uv run python manage.py migrate --noinput
```

Web start, from `backend/`:

```text
uv run python manage.py collectstatic --noinput && uv run gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --worker-class gthread --workers ${WEB_CONCURRENCY:-2} --threads ${WEB_THREADS:-4} --timeout ${WEB_TIMEOUT:-120} --graceful-timeout ${WEB_GRACEFUL_TIMEOUT:-10} --max-requests ${WEB_MAX_REQUESTS:-1000} --max-requests-jitter ${WEB_MAX_REQUESTS_JITTER:-100} --access-logfile - --access-logformat '%(h)s %(l)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(f)s" "%(a)s"' --error-logfile - --capture-output
```

Worker start, from `backend/`:

```text
uv run celery -A config.celery:app worker --loglevel=INFO --pool=prefork --concurrency=${CELERY_WORKER_CONCURRENCY:-1} --prefetch-multiplier=1 --max-tasks-per-child=${CELERY_WORKER_MAX_TASKS_PER_CHILD:-50} --hostname=worker@%h --queues=cloud
```

Beat start, from `backend/`:

```text
uv run celery -A config.celery:app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
```

Migrations stay in Railway pre-deploy because schema failure must block the release. `collectstatic` stays in the web start command for this first deployment because Railway pre-deploy filesystem changes do not become web-runtime artifacts. Adding `STATIC_ROOT` and WhiteNoise makes the current Django admin and static assets usable. It can move to an immutable image build when Cloud adopts a dedicated build pipeline.

The Gunicorn max-request controls are retained to limit long-lived process growth. Staging starts at two workers and four threads rather than the referenced four-by-eight production shape, which would create unnecessary database and memory pressure. Gunicorn access/error output and Celery logs go to stdout so `OBS-001` can introduce structured, collector-neutral logging next without changing the process topology.

Celery prefork, one-message prefetch, worker identity, and bounded child lifetime are retained. `-Ofair` is omitted because fair scheduling is already the modern Celery default, and a bare `-Q` is invalid; Allies explicitly uses the `cloud` queue. Staging concurrency remains one until workload evidence justifies more.

### Railway variable sources

| Variable or setting | Source | Scope | Presence-only verification |
| --- | --- | --- | --- |
| `DATABASE_URL` | Railway Postgres private `DATABASE_URL` reference | web, worker, beat | Variable reference exists and Django settings load in each service |
| `CACHE_URL` | Railway Redis private `REDIS_URL` reference (database 0) | web, worker, beat | Variable reference exists and cache/throttle configuration loads |
| `CELERY_BROKER_URL` | Derived from `CACHE_URL` with Redis database 1, or explicit sealed variable | web, worker, beat | Broker URL uses a database separate from cache state |
| `DJANGO_SECRET_KEY`, JWT signing key, digest key | Generated sealed shared variables | web, worker, beat | Names are present and non-empty; values are never printed |
| `DJANGO_ALLOWED_HOSTS` | Generated Railway web hostname plus required internal host | web, worker, beat | Host list contains the generated hostname by key-level read-back/test |
| trusted origin variables | Generated Railway HTTPS origin | web, worker, beat | Exact generated origin is accepted by production settings |
| feature and production flags | IaC literals | web, worker, beat | debug, fake auth, Google, and R2 are false; Railway proxy mode is true |
| `PORT` | Railway runtime | web | Gunicorn binds the injected port |
| web and worker tuning | IaC literals with environment overrides | owning application service | staging defaults match the reviewed process commands |

The presence-only verification reports variable names, source type, and scope, never values. Railway's per-service deployment metadata proves that each application service uses the same commit. Add an injected non-secret revision only if Railway metadata cannot provide that proof; do not add a revision endpoint or logging feature solely for this check.

### Railway ingress boundary

The generated public domain reaches the application through Railway's managed HTTPS edge; the service has no public TCP proxy. In explicit Railway mode, the application preserves only the edge's exact `https` protocol signal, strips forwarded identity and host fields, and records the deployment-boundary exception in the staging runbook. The application never derives client identity or authorization from `X-Forwarded-For`, `Forwarded`, or caller-supplied host fields. Private-network callers are inside the project deployment boundary and remain subject to allowed-host and application authentication checks. Outside Railway mode, all forwarding headers continue to be stripped unless the existing exact-IP trust configuration permits them.

## Phases

### Phase 1: close the review contract

- Goal: finish the API and terminology feedback without changing public route behavior.
- Work items: add privacy-safe exception logging; build the protected-operation and public-envelope inventory; add missing `403` declarations; add full response examples and exhaustive OpenAPI regression tests; update current `Actor` documentation to `User`.
- Impacted files/systems: `backend/config/api.py`, auth controllers/schemas/tests, Cloud architecture/backend docs, AUTH-001 Nabu note after acceptance.
- Exit criteria: generated OpenAPI matches runtime statuses and examples; exception test proves generic client output plus server traceback; terminology search is clean for account-model uses.

### Phase 2: add the process and health boundary

- Goal: make one codebase run safely as web, worker, and scheduler.
- Work items: add Gunicorn, WhiteNoise, static-root configuration, and Celery; create the Celery app; extract the cleanup service; add a retry-safe task and static 15-minute beat schedule; set a five-minute task time limit; keep the management command; add bounded dependency health checks; add Railway ingress handling and tests; validate every process command from `backend/`.
- Impacted files/systems: `backend/pyproject.toml`, lockfile, `backend/config/`, `backend/auths/services/cleanup.py`, `backend/auths/tasks.py`, command and tests.
- Exit criteria: local worker/beat configuration loads, task tests cover success/retry/failure, health tests cover dependency availability, and production settings pass with Railway-mode values.

### Phase 3: define and review local Railway IaC

- Goal: make the staging topology reviewable before creating resources.
- Work items: add `.railway/` to the repository's local `.git/info/exclude`; initialize local Railway IaC support; author web/worker/beat/Postgres/Redis resources; reference secrets without embedding values; set build roots, commands, region/replicas, restart policy, healthcheck, watch paths, and migration gate; document bootstrap/apply/drift/rollback without publishing the IaC source.
- Impacted files/systems: local ignored `.railway/`, local `.git/info/exclude`, `.env.example`, README, and Railway/operator documentation.
- Exit criteria: `railway config plan --json` parses successfully against the intended empty Cloud project and contains no destructive actions or secret values; `git check-ignore -v .railway/railway.ts` succeeds; no `.railway` path is tracked or staged.

### Phase 4: deploy and prove staging

- Goal: create the requested staging environment and verify it behaves as designed.
- Work items: complete the pre-apply checklist; create/link project `cloud` in workspace `allies`; create/link `staging`; apply the inspected IaC plan with worker and beat held inactive; set sealed/shared secrets through stdin; create the web domain; connect every app service to `staging`; merge the approved PR into `dev`; run `Promote Dev → Staging`; deploy web from the promoted revision and await its migration plus readiness gate; deploy and verify worker; deploy beat last; confirm the same immutable `staging` revision on all three; run health/API/OpenAPI/task smoke checks; inspect bounded logs and metrics; complete the redacted evidence record.
- Impacted systems: Railway `allies/cloud/staging`, GitHub `dev` and `staging` promotion branches, Nabu deployment decision/status notes.
- Exit criteria: web, worker, beat, Postgres, and Redis are healthy; the public health route returns 200; the cleanup task is dispatched and completed; no secret appears in logs or committed files; exact project/environment/service IDs and deployment evidence are recorded without credentials.

### Phase 5: finish the follow-up PR

- Goal: hand off a reviewable change with staging evidence and rollback instructions.
- Work items: run full validation and coverage; run code review; fix P0-P2 findings; create PR against `dev`; monitor CI and automated reviews; update Nabu with the accepted Railway staging topology and final AUTH-001 terminology/status.
- Impacted systems: GitHub PR, repository docs, Nabu.
- Exit criteria: PR is ready to merge with green checks, no unresolved P0-P2 finding, staging remains healthy, and the PR diff contains no `.railway/` path or Railway IaC content.

## Acceptance criteria

1. The 500 handler logs unexpected exceptions with traceback and returns only the existing generic envelope.
2. An exhaustive generated-OpenAPI test proves every inventoried origin/CSRF-protected operation declares `403`.
3. Every inventoried public response envelope has a fixed, reviewed, sanitized complete example, and a generated-OpenAPI test proves coverage plus the exact approved shapes and values.
4. Account-model terminology is `User` in current code and documentation; unrelated generic security/event uses of “actor” remain untouched.
5. Celery uses Redis, JSON-only payloads, UTC, task-specific late acknowledgement where safe, one bounded retry for raised infrastructure failures, a five-minute task time limit, and no persisted task results. Counted per-object avatar failures do not retry the whole batch.
6. The cleanup command and scheduled task call one bounded, idempotent service.
7. Beat schedules cleanup every 15 minutes and local IaC keeps beat at one replica.
8. The health endpoint returns 200 only when Postgres and Redis respond within their two-second operation budgets; otherwise it returns a generic 503 within a five-second total budget, including the bounded non-Railway throttle check. Both modes apply a process-local admission gate so each web process runs at most one dependency probe per second and reuses the last result for short bursts.
9. Railway ingress handling avoids HTTPS redirect loops by trusting only forwarded protocol inside the explicit managed-edge mode. Forwarded client identity remains ignored, direct public TCP exposure is absent, and staging verifies HTTP redirect and HTTPS success behavior.
10. Local ignored `.railway/railway.ts` defines web, worker, beat, Postgres, and Redis and produces a non-destructive plan, while Git confirms no `.railway` path is tracked, staged, committed, or pushed.
11. Staging secrets are inserted outside Git; Google, fake auth, and R2 remain disabled.
12. Railway reports terminal `SUCCESS` for web migration/readiness before worker and beat start; all application services prove the same immutable revision from the `staging` branch and health/task smoke evidence passes. No service remains connected to a feature or pull-request branch.
13. Admin/static assets resolve through WhiteNoise, Gunicorn and Celery tuning defaults are explicit, the worker consumes only the `cloud` queue, and all process logs reach stdout/stderr.

## Backend considerations

### Query optimization plan

- The health probe performs one `SELECT 1` and one cache set/get round trip with a unique five-second probe key, a two-second operation budget that must remain below the five-second total endpoint budget, and per-operation timeouts derived from the remaining deadline. It does not query product tables or delete a shared key, avoiding concurrent probe races. The health Redis cache keeps Django's binary serializer and must not enable `decode_responses`, because the probe sentinel is serialized before it is written to Redis. Direct-mode throttling reuses one worker-scoped Redis client with bounded health-operation socket timeouts, and a process-local one-second result gate bounds connection churn after the prefix throttle.
- Railway's shared edge peer address is never used as a global auth throttle bucket: sign-in and IP-level refresh admission use a server-issued, signed HttpOnly browser cookie as the fairness key when Railway mode is enabled, while requests without a valid binding use a bounded process-local bootstrap bucket (30-admission burst, refilling at one admission per second). Deleting and reissuing the cookie cannot create unbounded auth work. Session, refresh-family, and user-specific limits remain unchanged. Any unavailable health throttle/cache and database failure use the same neutral `service_unavailable` response.
- Cleanup retains the existing batch maximum of 100 and ordered indexed queries. Extraction into a service must not add per-record database queries.
- No response endpoint gains relation traversal or list behavior, so no new N+1 path is expected.

### N+1 prevention

- Not applicable to the new health endpoint.
- Preserve the cleanup implementation's set-based flow/refresh deletion and bounded avatar service behavior.
- Existing `/me` and Workspace access query shapes remain unchanged.

### Detailed unit test cases

- Generic 500: exception logged with traceback; response body remains generic. Health dependency failures log one detailed traceback per process per minute, then emit sanitized warnings to bound outage log volume.
- OpenAPI: the generated protected-operation inventory is fully covered by `403`; every inventoried public envelope contains its exact approved sanitized example.
- Cleanup service: valid bounds, expired-row deletion, partial avatar failure, repeat invocation, and no-op behavior.
- Celery task: calls service once, serializes safe counts, retries one injected infrastructure failure, exhausts predictably, does not retry counted avatar failures, tolerates redelivery, and stays within its time limit. Singleton beat plus worker concurrency one prevents scheduled overlap in staging; repeat-safe service behavior covers redelivery.
- Beat: task name and 900-second schedule load from production settings.
- Health: Postgres and Redis success; connection and operation timeouts return generic 503 within five seconds and log safely.
- Railway proxy mode: forwarded HTTPS is accepted only under explicit managed-edge mode; the proxy middleware normalizes non-exact protocol values before SecurityMiddleware evaluates them; untrusted forwarding remains stripped otherwise; forwarded client identity remains ignored; the process-local health admission gate bounds public dependency work; staging proves one HTTP redirect and direct HTTPS success. Deployment evidence confirms the Web service has no TCP proxy/direct public port before this mode is enabled.
- Production settings: complete staging variables pass; missing secrets/database/cache/origin fail closed; Google/R2 disabled configuration passes.

## Migration plan

- No Django model change is planned.
- Railway web pre-deploy runs `uv run python manage.py migrate --noinput` against staging Postgres.
- `uv run python manage.py makemigrations --check --dry-run` must remain clean.
- Rollback disables worker/beat or reverts their deployment before reverting application code. Database migrations remain additive and are not destructively reversed.

## Coverage target

- Preserve at least 90% line coverage for `auths` and `workspaces` and add focused coverage for new `config` health/proxy behavior.
- Use the existing CI coverage command plus focused tests for task, health, OpenAPI, and settings behavior.

## Test plan

- Unit tests: logging, cleanup service/task, beat and queue configuration, health, proxy behavior, response example schemas, and production static settings.
- Integration/API tests: generated OpenAPI status/example inspection, standardized 500/503 envelopes, live Django health request.
- Regression checks: auth/API suite, Workspace isolation, migration check, Ruff, `git diff --check`.
- Railway validation: IaC plan; presence-only variable/source read-back; web migration and readiness gate; ordered worker then beat deployment; shared immutable revision from deployment metadata; terminal states; public health/redirect requests; bounded logs; one explicit cleanup task dispatch.
- Process validation: each exact web/worker/beat command starts with staging variables; static collection succeeds; Gunicorn exposes access/error output; the worker reports only the `cloud` queue.
- Commands:

```text
cd backend
uv sync --locked
uv run python manage.py check --deploy
uv run python manage.py makemigrations --check --dry-run
uv run pytest
uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90
uv run ruff check .
uv run ruff format --check .
railway config plan --json
git check-ignore -v .railway/railway.ts
git ls-files --error-unmatch .railway/railway.ts  # expected to fail because IaC is untracked
git diff --check
```

## Risks and mitigations

| Risk | Mitigation | Rollback/fallback |
| --- | --- | --- |
| Unexpected exceptions disappear behind the response envelope | Log once at the global handler with traceback and sanitized request context | Revert logging change without changing the client contract |
| Railway proxy headers are over-trusted | Use an explicit Railway deployment mode and trust only required platform facts; test spoofed headers outside that mode | Disable the mode and temporarily disable SSL redirect only during diagnosis |
| Beat duplicates scheduled work | One beat replica in IaC; cleanup remains idempotent and bounded | Stop beat; run the management command manually |
| Worker retries amplify failures | One retry with bounded backoff and no result backend; cleanup remains safe to repeat | Disable the beat schedule or worker service |
| Local IaC is accidentally included in the PR | Exclude `.railway/` through local Git info, verify it is ignored and untracked before every commit/push | Unstage it immediately and stop PR creation until the diff is clean |
| IaC apply creates unintended resources or deletes state | Always inspect `railway config plan`; stop on any destroy or unrelated change | Do not apply; edit the local desired state and re-plan |
| An initial source deploy starts before secrets and configuration are ready | Do not treat an early deployment as success. Set sealed/shared variables, deploy explicitly, and verify the terminal state | Remove the public domain or stop app services; retain databases for retry |
| Staging costs grow unexpectedly | One replica per app service, low worker concurrency, no custom storage or production environment | Scale app services to zero or remove the staging project only with explicit approval |
| Missing Google/R2 credentials block useful staging | Keep both integrations disabled and validate infrastructure/auth-disabled operation | Enable each integration later through a separate credentialed smoke task |

### Pre-apply checklist and deployment evidence

Before apply, record the workspace/project/environment names, exact commit revision, planned resource names, variable names and sources, expected monthly-review owner, confirmation that the IaC diff has no destroy or secret material, and proof that `.railway/` is ignored and untracked. After apply, record resource IDs, the same revision for all app services, variable presence and scope, migration result, deployment terminal states, health/redirect results, task dispatch evidence, and bounded log references. The record is redacted by construction and does not embed the IaC source.

Staging is retained while it supports active Allies development and is reviewed monthly by the Railway workspace owner. Scaling application services down is reversible. Removing Postgres, Redis, or the project is destructive and always requires a fresh explicit approval plus a decision about retained data; the runbook must resolve exact resource IDs before any teardown command.
