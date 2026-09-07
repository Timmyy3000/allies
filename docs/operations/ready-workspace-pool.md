# Ready workspace pool

The ready pool is an optional Foundry control-plane optimization. It keeps
complete, unassigned runtime bundles ready for permanent transfer to a new
Cloud workspace. A bundle is never reused after assignment.

The safe default is disabled:

```text
READY_WORKSPACE_POOL_TARGET=0
```

Target zero prevents both pool creation and pool assignment. Set a positive
target only for an explicitly scoped region and release. The target is capped
at eight bundles, and at most one additional bundle may be preparing. The
pool maintainer is a one-shot command; invoke it from an external scheduler
when periodic repair is wanted.

Before enabling a target, set these values in the control-plane environment:

```text
READY_WORKSPACE_POOL_TARGET=2
READY_WORKSPACE_POOL_REGION=<one-provider-region>
READY_WORKSPACE_POOL_RELEASE_FINGERPRINT=<digest-derived-fingerprint>
READY_WORKSPACE_POOL_CONFIG_VERSION=1
READY_WORKSPACE_POOL_MAX_PREPARING=1
READY_WORKSPACE_POOL_MAX_ATTEMPTS=5
READY_WORKSPACE_POOL_READY_TTL_SECONDS=900
READY_WORKSPACE_POOL_HEALTH_FRESHNESS_SECONDS=60
```

The release fingerprint is derived from the exact pinned image digests, the
region, the two-container topology (`hermes` and `allies-runtime`), and the
`/opt/data` mount. Generate it from the same image references used by the
activation proof and copy only the resulting digest into configuration:

```python
from runtime.services.ready_pool_maintenance import pool_config_fingerprint

fingerprint = pool_config_fingerprint(
    region="<one-provider-region>",
    images={
        "hermes": "<immutable-hermes-image>@sha256:<64-hex-digits>",
        "allies-runtime": "<immutable-runtime-image>@sha256:<64-hex-digits>",
    },
    containers=("hermes", "allies-runtime"),
)
print(fingerprint)
```

Run one bounded pass from the backend project:

```powershell
uv --directory backend run --locked python manage.py `
  maintain_ready_workspace_pool --limit 1
```

`--limit` is bounded to eight and controls how many bundles one invocation
may claim. The pass first resumes due preparation or cleanup, then reconciles
stale ready rows, then creates at most the available capacity. Provider calls
run outside database transactions. A 1,200-second phase lease protects the
activation path, and readiness-pending responses keep the row resumable
without consuming the provider failure budget.

Each successful bundle must have a reserved `pool:` tenant reference, exact
App, Volume, and Machine bindings, a newly proven blank mounted Volume, the
current immutable image pair and derived fingerprint, healthy Hermes and
runtime containers, and a current authenticated runtime readiness receipt.
The adapter rechecks provider ownership, Volume attachment, image digests,
and health before the row becomes `READY`.

Assignment remains a separate atomic transfer during normal workspace
registration. It changes only the reserved tenant reference and bundle state;
the provider binding, generation, Volume, credentials, and runtime fences
remain attached to that workspace. A reserved reference can never claim
another bundle.

To disable creation and assignment, restore `READY_WORKSPACE_POOL_TARGET=0`.
Existing owned unassigned rows may be drained deliberately with the same
bounded command:

```powershell
uv --directory backend run --locked python manage.py `
  maintain_ready_workspace_pool --limit 1 --drain
```

Drain is an operator action. Cleanup rechecks the reserved tenant namespace,
absence of profiles and executions, and absence of live activation or
lifecycle claims before touching a provider resource. It revokes owned runtime
credentials, stops and destroys the exact owned Machine, waits for the exact
Volume to detach, deletes the exact Volume, and finally deletes the exact App;
App deletion removes its scoped secrets. Assigned or previously used rows are
refused. Ownership or cleanup failures remain visible for a later bounded
retry.

A staged rollout should start with one bundle in a disposable proof region,
verify two consecutive healthy inspections, and then raise the target to two.
Rollback is the target-zero setting; do not delete provider resources outside
the recorded cleanup path. Proof evidence should show two `READY` bundles,
two concurrent permanent assignments to fresh Cloud workspace references,
deficit replenishment on a later invocation, stale-bundle eviction, and cold
fallback after the ready rows are consumed. Keep provider identifiers and
credentials in the run manifest or environment, never in this document or
command output.
