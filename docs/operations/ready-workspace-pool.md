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
pool maintainer supports a one-shot command for diagnosis. The persistent
`run_foundry_worker` command schedules it without restarting Django each pass.

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

For sleeping onboarding capacity, deploy compatible code and migrations to
both API and worker before enabling `READY_WORKSPACE_POOL_SLEEP_ENABLED=true`.
Use the same target, release, version and capacity settings in both services:

```text
READY_WORKSPACE_POOL_TARGET=5
READY_WORKSPACE_POOL_SLEEP_ENABLED=true
READY_WORKSPACE_POOL_CONFIG_VERSION=2
WORKSPACE_CPU_KIND=shared
WORKSPACE_CPUS=2
WORKSPACE_MEMORY_MB=2048
WORKSPACE_VOLUME_SIZE_GB=10
ALLIES_RUNTIME_IDLE_STOP_ENABLED=true
ALLIES_RUNTIME_KEEP_WARM_SECONDS=1800
```

Capacity defaults are 2 shared CPUs, 2048 MB memory and 10 GB volumes for the
deployed activation and replacement paths. Existing larger volumes are adopted
without shrinking. Undersized existing volumes require explicit operator
growth; changing configuration does not resize a bound volume or machine.
Standalone lifecycle specs retain their previous defaults for caller
compatibility. Pool provider inspection validates actual resource sizes.

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
registration. The provider binding, generation, Volume and credentials remain
attached to that workspace. A reserved reference can never claim another bundle.

In sleeping mode, authenticated readiness and blank-volume proof precede a
durable `PARKING` phase. Only an observed stopped machine becomes `SLEEPING`.
Maintenance inspects sleeping provider resources without starting them or
requiring fresh runtime heartbeats. Stale inspection evidence temporarily
prevents assignment; it is not permission to recycle or wake a spare.

Assignment is permanent and durably requests an onboarding wake in the same
transaction. The wake advances the runtime start epoch and waits for a fresh
authenticated readiness receipt. An old readiness receipt or a successful
provider start response is insufficient. Transient onboarding wake failures
retry without requiring a queued user execution. Exhaustion remains visible
on the assigned bundle; registration replay cannot allocate a second spare or
reset the retry budget. Explicit activation recovery can retry the same
workspace. Pool preparation restores the configured number of sleeping spares.

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
Disable pool assignment/creation with target zero; do not delete provider resources outside
the recorded cleanup path. Proof evidence should show two eligible bundles,
two concurrent permanent assignments to fresh Cloud workspace references,
deficit replenishment on a later invocation, stale-bundle eviction, and cold
fallback after the ready rows are consumed. Keep provider identifiers and
credentials in the run manifest or environment, never in this document or
command output.

For the persistent worker and service handoff, see [Foundry worker](foundry-worker.md).

## Migrating an existing warm pool

1. Inventory assigned and unassigned resources and preserve rollback settings.
2. Set target zero in API and existing maintainers. Explicitly retain the
   current capacity settings and keep sleeping disabled while deploying the
   compatible schema/API/worker; verify all loops before changing capacity.
3. Wait for active claims to settle, then drain only confirmed unused spares
   through the bounded drain command.
4. Set matching capacity, version and sleeping settings; enable one canary.
   Verify preparation, stopped-state inspection, assignment, wake and readiness.
5. Restore target five and verify sleeping spares survive health/TTL windows
   without wake or replacement churn. Verify user idle and scheduled wake paths.

Upgrade assigned machines separately at a quiescent boundary, retaining exact
volume identity and a verified recovery snapshot. Extend smaller volumes in
place with the provider's supported procedure and check mounted capacity.
Preserve larger volumes. Verify data continuity and current readiness before
resuming work; never use pool drain for assigned resources.

Once `PARKING` or `SLEEPING` rows exist, retain compatible code and schema on
rollback. Disable pool creation/assignment first and stop pool scheduling;
revert scheduling separately if needed. Do not feed sleeping rows to older
warm-only code or reverse the additive schema while those rows exist. Volume
growth remains in place on rollback.
