# Updating existing workspace images

Publishing an image does not change an existing machine. Foundry now compares
the stopped machine's runtime and Hermes images with `RUNTIME_IMAGE` and
`HERMES_IMAGE` before waking it. Both settings must use immutable
`repository@sha256:<64 lowercase hex digits>` references.

If either differs, Foundry replaces the machine through its existing lifecycle:
fence the old generation, stop and remove the old compute, retain the app and
volume, create the replacement with both desired images, and remount the same
volume. It verifies the provider's image pair and container health. Claims stay
blocked until the new runtime reconciles profiles and reports current-generation
readiness. Queued prompts and conversation bindings remain unchanged.

A running machine keeps serving its current release. It upgrades on its next
sleep/wake cycle, or through the operator command once its keep-warm deadline
has expired and the entire workspace has no queued/running executions, active
attempts, or unresolved leases. Expired but unresolved leases still block an
upgrade. A stopped machine can retain queued prompts while upgrading; it cannot
have an unresolved attempt or lease.

## Configuration and canary

Apply migration `0018_workspace_runtime_release` before running the new backend
or publisher. Configure the same desired image pair on Foundry's web and event
publisher processes. The publisher also needs the existing `FLY_API_TOKEN`,
`FOUNDRY_ORIGIN`, and `FLY_ORG` configuration. It uses the bundled CLI to stage
a new generation credential; existing Hermes/provider secrets are retained.
Secret staging does not deploy or restart other machines.

Automatic checks on wake default to enabled when image settings are supplied.
Set `ALLIES_RUNTIME_IMAGE_UPDATES_ENABLED=false` on the event publisher to pause
new automatic upgrades while preparing a canary. The explicit operator command
still works. With neither image setting present, the power lifecycle retains
its existing behavior; a partial or malformed pair fails closed.

First, publish the images and set the desired pair. Then use the **Cloud
workspace UUID** for a single idle/stopped canary:

```sh
uv run --no-sync python manage.py reconcile_runtime_images --workspace <workspace-uuid>
```

Commands run from `backend/` locally or the application directory in deployment.
The command reports `current`, `busy`, or `awaiting_readiness`, plus the bound
generation. It stops at a readiness gate or the first failure. Repeat the same
canary command after readiness, verify a normal conversation, then enable
automatic checks on wake.

For an explicit rollout of already-idle machines:

```sh
uv run --no-sync python manage.py reconcile_runtime_images --batch --limit 1
uv run --no-sync python manage.py reconcile_runtime_images --batch --limit 5 --after <foundry-workspace-uuid>
```

The scan is ordered by Foundry workspace UUID and limited to 1–20 records per
invocation. It prints a continuation cursor after a completed batch; at a
readiness gate, use the reported workspace UUID only after verifying that
canary. Busy workspaces are skipped and must be revisited in a later pass or
left to their next wake. No CI deployment integration or background fleet-wide
rollout is introduced.

## Recovery, evidence, and rollback

`Workspace.applied_images` records the bound pair. Legacy rows start empty;
live provider inspection establishes their actual pair. `release_target` pins
the pair, source generation, credential identity, region, organization, origin,
and attempt count before any replacement side effect. It contains no bearer
tokens. The target clears only after the replacement is bound; readiness is a
separate gate.

The publisher resumes abandoned or retryable replacements, with at most five
release attempts using the lifecycle's existing bounded provider retries.
The same target, generation and staged credential are reused even if deployment
settings change during recovery. A failed replacement never falls back to
executing work on the old image. Terminal provisioning failures stay parked
for operator inspection; they are not silently reset. After addressing a
retryable failure, the single-workspace command can explicitly resume a parked
attempt. Retired credentials remain generation-fenced under the existing
credential-retention policy.

Pause new upgrades with the flag above. To roll back a completed release, set
both desired image references to the previous compatible pair and use the same
canary/replacement flow. An in-flight replacement retains its pinned target
until it completes or is repaired; changing environment variables does not
rewrite a half-completed operation. Confirm backend/runtime protocol
compatibility before rolling back. Never delete a volume as part of a rollout.

## Verification

The release tests exercise real lifecycle transitions against a deterministic
provider: either image changing, a no-op wake, legacy image discovery, queued
message preservation, active-work/lease guards, credential/generation reuse on
failure, provider image mismatch, duplicate claims, and the readiness gate.
They do not substitute for the deployment canary above.
