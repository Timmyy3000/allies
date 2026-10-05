# FND-004 runtime smoke

The default proof is deterministic and local:

```powershell
uv --directory runtime run --locked pytest --cov=allies_runtime --cov-report=term-missing
uv --directory runtime run --locked python -m allies_runtime --smoke fake
```

The fake command exercises the same smoke integration boundary used by the
provider-backed proof. It does not create Fly resources, write `/opt/data`, or
resolve a credential.

## Live gate

Live mode is opt-in and fails closed before App, Volume, or Machine creation
unless all of these are present:

- `FND004_LIVE_SMOKE=1`;
- a backend adapter that calls `FlyProvider.preflight()` before
  `WorkspaceLifecycle.ensure_workspace()`;
- an authenticated Hermes client; and
- a secure, run-scoped temporary profile/key bootstrap whose `available()`
  check passes, whose `prepare(run_id)` sets up the socket/material boundary
  before provisioning, and whose `install(run_id)` activates temporary Hermes
  profiles after provisioning.

The backend adapter is
`runtime.services.hermes_smoke.ProviderLifecycleSmokeIntegration`. It records
only resources proven to belong to this fresh smoke namespace in an owned
ledger, reconciles reserved names to provider IDs before deletion, stops and
destroys the recorded Machine before deleting its Volume and App, and treats a
404 for a recorded resource as an idempotent success. If the deterministic App
already exists, the run fails closed before provisioning. If a required cleanup
operation is unavailable, the evidence is `incomplete`; the run must not adopt
or delete unrelated resources.

Temporary profile keys stay in the bootstrap/client boundary. They are never
placed in Machine config, command arguments, logs, exceptions, or evidence.
The live report includes safe image/source identifiers, named health/process
checks, volume visibility, profile-proof mode, and explicit cleanup status.

For a proof-only run, the bootstrap may use the explicit `test://fnd004/…`
reference scheme. The image derives the matching non-secret fixture credential
from that reference, so the runtime can start without a socket producer. Any
other reference scheme requires the secure workload-local Unix socket described
below. In either case, `bootstrap.prepare()` runs before the lifecycle creates
or waits on the Machine, then `bootstrap.install()` must succeed after the
Machine is alive and before the lifecycle writes the durable Workspace binding.
The hook receives the remaining bounded install budget and must return before
it expires. Profile streams run only after that authenticated activation gate;
cleanup runs even when preparation or installation is partial.

The Machine payload passes only the opaque `HERMES_CREDENTIAL_REF` environment
reference to `allies-runtime`. For normal references, the image-baked `--serve`
process resolves that reference through a workload-local Unix socket (the
default is `/run/allies-runtime/hermes-credential.sock`;
`HERMES_CREDENTIAL_SOCKET` may select another bounded absolute path) and then
performs an authenticated `/health/detailed` probe. For the proof-only
`test://fnd004/…` scheme, PID 1 stays alive but unready for a bounded bootstrap
grace while `install(run_id, timeout_seconds=…)` configures Hermes; it becomes
ready only after the authenticated probe succeeds. The secure bootstrap owns the socket and returns
the short-lived test credential only to the requesting process; no credential
is persisted in Machine config or `/opt/data`. A missing socket/reference or
expired proof grace exits without reporting readiness.
Live profile streams additionally fail closed unless the post-provision
`bootstrap.install(run_id, timeout_seconds=…)` hook succeeds, so a test-only
resolver cannot claim readiness without Hermes being configured.

## Canonical repository checks

`make validate` (or `uv run --locked --project backend python
scripts/validate.py`) runs backend lock/config/migration/tests and the runtime
lock/tests with both `backend/coverage.xml` and `runtime/coverage.xml`. CI
uploads both reports through its existing Codecov step. `make lint` checks the
backend and runtime projects without relaxing either project's lockfile.
