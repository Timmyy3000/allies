# Railway staging operations

Allies Cloud staging runs five Railway resources: `web`, `worker`, `beat`,
Postgres, and Redis. Railway IaC is kept in local `.railway/` files excluded by
Git's local `info/exclude`, matching Foundry. Never stage, commit, or push that
directory.

Run application commands from `backend/`.

## Process commands

Pre-deploy migration:

```text
uv run python manage.py migrate --noinput
```

Web:

```text
uv run python manage.py collectstatic --noinput && uv run gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --worker-class gthread --workers ${WEB_CONCURRENCY:-2} --threads ${WEB_THREADS:-4} --timeout ${WEB_TIMEOUT:-120} --graceful-timeout ${WEB_GRACEFUL_TIMEOUT:-10} --max-requests ${WEB_MAX_REQUESTS:-1000} --max-requests-jitter ${WEB_MAX_REQUESTS_JITTER:-100} --access-logfile - --access-logformat '%(h)s %(l)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s "%(f)s" "%(a)s"' --error-logfile - --capture-output
```

Worker:

```text
uv run celery -A config.celery:app worker --loglevel=INFO --pool=prefork --concurrency=${CELERY_WORKER_CONCURRENCY:-1} --prefetch-multiplier=1 --max-tasks-per-child=${CELERY_WORKER_MAX_TASKS_PER_CHILD:-50} --hostname=worker@%h --queues=cloud
```

Beat:

```text
uv run celery -A config.celery:app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
```

## Deployment order

Railway application services are connected only to the `staging` branch. A
release reaches staging by merging its PR into `dev`, running the manually
dispatched `Promote Dev → Staging` workflow, and allowing that workflow to run
CI against `dev` before merging the validated revision into `staging`.
Railway then auto-deploys the resulting `staging` branch revision. Do not
connect staging services to feature or pull-request branches.

1. Inspect `railway config plan --json`. Stop if it contains a destroy action,
   an unrelated mutation, or a secret value.
2. Verify `.railway/railway.ts` is ignored and untracked.
3. Create resources with worker and beat inactive, then insert sealed/shared
   variables outside Git.
4. Merge the approved PR into `dev`, dispatch `Promote Dev → Staging`, and
   verify its validation and promotion jobs succeed.
5. Allow Railway to deploy web from `staging`. Its migration and
   `/api/v1/health` readiness checks must pass.
6. Deploy worker and verify Redis connection plus the `cloud` queue.
7. Deploy the singleton beat process last and observe one cleanup dispatch.
8. Confirm Railway deployment metadata reports the same `staging` commit for web,
   worker, and beat.

The public health response contains no dependency name, address, or exception.
Health dependency failures use the same neutral `service_unavailable` code whether
the throttle/cache or database probe is unavailable.
Google, fake authentication, and R2 remain disabled for the first staging
deployment.

Railway health probes use an ephemeral internal host. Staging therefore sets
`DJANGO_ALLOWED_HOSTS=*`; trusted origins, forwarded-host trust, CSRF, and
client-IP trust remain independently restricted. Revisit the host policy when
a stable custom domain replaces the generated staging domain.
Railway terminates HTTPS at its managed edge and has no public TCP ingress.
Railway mode preserves only the edge's exact `https` protocol signal, strips
forwarded identity and host headers, and exempts the private health probe from
Django's HTTPS redirect. The proxy middleware normalizes every non-exact
forwarded protocol to `http` before SecurityMiddleware evaluates it, so
comma-separated values still redirect. The trust boundary is recorded below
and must be revisited if the ingress topology changes.

Health probe budgets are independent from normal application connection
timeouts. `ALLIES_HEALTH_OPERATION_TIMEOUT_SECONDS` and
`ALLIES_HEALTH_TOTAL_TIMEOUT_SECONDS` bound readiness checks, and the operation
budget must remain strictly below the total budget. Each database connection
and Redis operation receives no more than the remaining endpoint deadline; use
the derived health-cache socket timeout rather than the normal cache timeout.
Use
`DATABASE_CONNECT_TIMEOUT_SECONDS`, `CACHE_CONNECT_TIMEOUT_SECONDS`, and
`CACHE_SOCKET_TIMEOUT_SECONDS` for normal service connection behavior.
Outside Railway mode, the public health route is limited to 60 requests per
client network prefix per minute and returns the standard `429` envelope when
that limit is exceeded. Railway mode uses a process-local health admission gate:
each web process runs at most one dependency probe per second and serves its
last result to bursts during that interval. This prevents public traffic from
multiplying Postgres/Redis work while keeping readiness independent of the
shared edge peer address. Keep the service behind Railway's managed edge; the
gate is an application safeguard, not a substitute for private networking.
The same short-lived gate applies outside Railway mode after the per-prefix
throttle, so distributed callers cannot turn every allowed request into a new
Postgres connection. Health dependency failures emit one detailed traceback per
process at most once per minute; subsequent failures retain only a sanitized
warning so an outage cannot flood logs with repeated infrastructure details.
The direct-mode throttle reuses one worker-scoped Redis client with bounded
health-operation socket timeouts; it must not construct a new Redis pool per
request.

Railway hides the original peer address behind its shared edge. Auth throttles
therefore use a server-issued, signed HttpOnly browser cookie as the fairness
key for sign-in and IP-level refresh admission. Requests without a valid
binding use a bounded process-local bootstrap bucket; deleting and reissuing the
cookie cannot create unbounded auth work. The bootstrap bucket permits a burst
of 30 admissions per web process and refills at one admission per second.
Session, family, and user-specific limits remain unchanged. If the service is
scaled across more web processes, the bootstrap cap applies per process and the
managed edge remains the primary abuse-control boundary.

Cache and broker state use separate Redis logical databases. `CACHE_URL` uses
database 0 for Django cache/throttle data; `CELERY_BROKER_URL` is derived as
database 1 when it is not supplied explicitly. Never run `FLUSHDB` against the
broker database as a cache operation.
The health probe cache keeps Django's binary serializer; do not enable Redis
`decode_responses` for that backend, because the probe sentinel is serialized
before it is written to Redis.

### Recorded deployment exceptions

- **Rule:** AL-02, forwarded-protocol trust.
- **Scope:** `ALLIES_RAILWAY_PROXY_MODE` and the `X-Forwarded-Proto` header
  received by the web service.
- **Reason:** Railway's managed HTTPS edge is the only supported ingress for
  staging, but the app does not have a stable edge-IP allowlist to validate.
- **Risk:** A future direct TCP exposure or edge behavior change could let a
  caller spoof the protocol signal and bypass Django's redirect decision.
- **Mitigation:** Railway mode strips `X-Forwarded-For` and
  `X-Forwarded-Host`, normalizes non-exact protocol values to `http` before
  SecurityMiddleware, and has no public TCP proxy. Any non-Railway deployment
  retains the existing exact-IP proxy allowlist requirement.
- **Owner:** Cloud platform maintainers.
- **Revisit:** Before enabling a custom production domain or changing Railway
  ingress, whichever happens first.

- **Rule:** AL-02, wildcard staging host allowlist.
- **Scope:** `DJANGO_ALLOWED_HOSTS=*` in the Railway staging environment only.
- **Reason:** Railway's private readiness probe uses an ephemeral internal host
  that cannot be enumerated before the service is created.
- **Risk:** An unrestricted Host header can affect absolute URLs, redirects, or
  host-based integrations if a future endpoint uses it.
- **Mitigation:** Staging health responses contain no private metadata,
  forwarded-host trust is disabled, CSRF/trusted origins remain exact, the
  generated public domain is the only documented public entry point, and this
  exception is forbidden for production or credentialed traffic.
- **Owner:** Cloud platform maintainers.
- **Revisit:** Replace the wildcard with the generated/custom hostname before
  production or before adding any host-derived behavior, whichever happens
  first.

Before enabling Railway proxy mode, verify the deployed Web service has only
Railway's generated HTTPS domain and no TCP proxy or direct public port. The
local desired state intentionally declares no `tcp` or `tcpProxies` entry. If
the ingress topology changes, disable Railway mode until an edge allowlist or
equivalent authenticated protocol signal is configured.

## Rollback and teardown

Stop beat first, then worker, before reverting the web deployment. Scaling an
application service down is reversible. Removing Postgres, Redis, or the
project deletes managed state and always requires fresh explicit approval plus
a decision about retained data.
