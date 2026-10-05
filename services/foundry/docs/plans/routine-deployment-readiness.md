# Automatic routine deployment readiness

## Scope and approach

Use the existing published `RUNTIME_IMAGE` and `HERMES_IMAGE` references as the
desired routine release. Remove `ALLIES_RUNTIME_ROUTINE_RELEASE_DIGEST` and the
requirement to enable each workspace manually. Derive the image-pair identity
using the existing release helper, compare it with provider-applied images, and
require current runtime readiness when claiming work. Missing or mutable image
references and mismatched releases remain ineligible. Existing explicit admission
pauses remain effective; historical enabled records need no renewal after a restart.

A sleeping machine with matching images can accept a queued routine and request
the normal execution wake. It cannot claim the routine before readiness returns.
Image replacement remains owned by the existing runtime release lifecycle.

## Approval expiry

Cloud owns scheduling. Its existing Beat task `routines.expire_approvals` runs
every minute and persists `routine.cancel_wait` with reason `expiry`. The existing
Cloud Worker delivers the durable command through the approval outbox. Foundry
handles it through its authenticated cancellation endpoint and publishes one
terminal result through the existing Event Publisher. No Foundry Beat or periodic
expiry service is required. The local Foundry expiry command remains available
for maintenance; it is not a deployment prerequisite.

## Validation and review

Run Foundry routine, release, readiness and full backend tests; scoped Ruff;
Django system/migration checks; and Cloud settings/approval tests. Verify automatic
admission, image mismatch, stale readiness, sleeping-machine wake, explicit pause,
legacy enabled records, and replay of Cloud expiry cancellation. Review runtime
fencing separately from simplification and operational scope. No external contract,
database migration, client change, or provider action is introduced.

## Rollout and rollback

Deploy Cloud's enabled-by-default routine settings, then this Foundry revision
alongside the existing image-publishing workflow. Backend/publisher processes must
share the published image references. Existing machines become eligible when the
normal upgrade/readiness flow confirms that pair. No new secret or service is needed.
An explicit workspace admission pause still blocks new claims without stopping
active work. To roll back code, disable Cloud scheduling/dispatch first; the older
Foundry revision again requires its former manual gate. Deployed real-agent testing
remains necessary after merge; local tests do not claim staging acceptance.
