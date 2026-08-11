# AUTH-001 Operations And Readiness

## Scope

This runbook covers the Cloud authentication, personal Workspace, session, and
avatar boundary. ChatGPT is not an implemented provider. Google is enabled only
after its complete client configuration is supplied; deterministic fake auth is
limited to local development and tests.

## Required Production Configuration

- `DJANGO_DEBUG=false`, a deployment-owned `DJANGO_SECRET_KEY`, exact
  `DJANGO_ALLOWED_HOSTS`, and exact HTTPS `ALLIES_TRUSTED_ORIGINS`.
- Independent random values of at least 32 bytes for `ALLIES_AUTH_JWT_KEY` and
  `ALLIES_AUTH_DIGEST_KEY`. Never reuse the Django secret.
- `DATABASE_URL` for PostgreSQL and `CACHE_URL` for the shared Redis-compatible
  auth throttle cache.
- Keep `ALLIES_AUTH_FAKE_PROVIDER_ENABLED=false`. Production startup rejects
  fake auth even if the rest of the configuration is complete.
- Trust forwarded host/protocol/client-IP headers only when the deployment is
  behind a known proxy. Enable the corresponding `ALLIES_TRUST_FORWARDED_*`
  flags and list every direct proxy peer in `ALLIES_TRUSTED_PROXY_IPS`; all
  forwarded headers from other peers are discarded.
- When Google is enabled: client ID, client secret, and the exact registered
  HTTPS callback URI through the `ALLIES_AUTH_GOOGLE_*` variables.
- When avatars are enabled: a private bucket and the complete `ALLIES_R2_*`
  HTTPS endpoint, bucket, and scoped credential set.

Startup rejects an incomplete enabled provider/storage configuration and an
unsafe production auth/cache/origin configuration. Disabled integrations fail
closed at their API boundary.

## Release Validation

From `backend/`:

```powershell
python -m uv sync --locked
python -m uv run python manage.py check --deploy
python -m uv run python manage.py makemigrations --check --dry-run
python -m uv run python manage.py migrate --noinput
python -m uv run pytest
python -m uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90
python -m uv run ruff check .
python -m uv run ruff format --check .
```

The PostgreSQL CI lane is the required evidence for row locks, concurrent
bootstrap, same-token refresh rotation/reuse, same-state callback consumption,
and migration behavior. SQLite results are local compatibility evidence only.

Before enabling Google, complete a staging callback smoke test with a normal
consumer account and verify issuer, audience, nonce, PKCE, redirect, replay,
timeout, malformed-response, and provider-outage behavior. Before enabling R2,
verify private-bucket CORS and the signed PUT/metadata/read/delete lifecycle.
Uploads use a client-writable staging key; completion copies verified bytes to
a distinct server-written key before it becomes current. Bucket lifecycle rules
must remove abandoned objects under the `staging/` prefix after the pending
upload window. Pending rows deterministically identify both keys so cleanup can
remove a final object left by a crash before the database promotion commits.

## Routine Operations

- Schedule `cleanup_auth_artifacts --batch-size 100` every 15 minutes. Alert on
  nonzero exit, repeated object deletion failures, or a persistent backlog.
- Revoke compromised access with
  `revoke_auth_sessions --actor-id ACTOR --reason REASON` or
  `revoke_auth_sessions --family-id FAMILY --reason REASON`.
- Monitor callback rejection spikes, refresh reuse, provider latency/failure,
  throttle/cache failure, cleanup backlog, and avatar verification rejection.
- Keep structured security events privacy-safe. Never log codes, tokens,
  cookies, raw claims, private object keys/URLs, display names, email addresses,
  full IP addresses, or request bodies.

## Incident Rollback

1. Disable new provider starts/callbacks at configuration or ingress.
2. Revoke affected session families and clear browser cookies at the Interface.
3. Disable new signed avatar URLs when object storage is implicated.
4. Preserve additive identity/session tables and redacted operational evidence
   for investigation and forward repair.
5. Do not destructively reverse or merge identity records during rollback.

Already issued avatar read URLs remain bearer capabilities until their maximum
five-minute expiry. Already issued access JWTs stop authorizing as soon as their
session family is revoked because every authenticated request rechecks family
state.
