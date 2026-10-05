# Runtime image reconciliation

Route: fast. HTML is not needed for this backend lifecycle change.

## Scope and approach

Complete the agreed follow-up to PR #25: existing workspace machines must pick
up the configured runtime and Hermes image pair. Reuse the generation-fenced,
same-volume replacement lifecycle, secret staging and runtime readiness gate.
Keep active work running. Check stopped machines on wake and expose an explicit
bounded operator command for canaries and already-idle workspaces.

## Affected surfaces

- Provider machine records expose the observed container image pair.
- Workspace stores applied images and a pinned, resumable replacement target.
- Power maintenance checks images before starting an existing machine and
  resumes interrupted replacements within a bounded attempt budget.
- The lifecycle records applied images at bind and preserves wake identity.
- `reconcile_runtime_images` runs one workspace or scans 1–20 ordered records,
  stopping at failure or a readiness gate. No public API, Cloud or client change.

## Acceptance and validation

1. Unchanged images start the same machine; either changed image replaces it.
2. Replacement preserves the volume, queued prompt and profile identity.
3. Running work, active attempts and unresolved leases prevent an upgrade.
4. Claims stay blocked until current-generation profile reconciliation/readiness.
5. Retries reuse the pinned pair, generation and credential; mismatched provider
   images fail closed. Duplicate operators cannot steal a live operation claim.
6. Legacy machines acquire their image evidence through provider inspection.

Checks: `DJANGO_DEBUG=true uv run --locked --project backend python
scripts/validate.py`; `uv run --locked ruff check .` in backend and runtime;
focused release, power, activation and lifecycle tests; `git diff --check`.
Real deployment acceptance remains an explicit single-workspace canary following
`docs/operations/runtime-image-updates.md`.

## Risk and review

The critical boundary is the workspace lock before fencing, followed by provider
I/O outside transactions. Persisted operation/phase claims prevent concurrent
replacement and fence retired generations. Staged credentials are reused on
retry without storing bearer tokens. A failed operation retains its target and
remains unavailable; terminal provisioning failures require operator repair.

Correctness review covers queued-versus-running work, lease state, partial
provider failure, generation reuse, readiness and wake priority. Simplicity
review keeps the existing lifecycle and publisher, two additive JSON fields,
and one bounded command; no rollout service, scheduler, dependency or CI coupling.
The implementation and its failure-path tests remain one coherent PR.

Pause automatic upgrades with `ALLIES_RUNTIME_IMAGE_UPDATES_ENABLED=false`.
Rollback a completed upgrade by setting the previous compatible image pair and
using the same canary flow. In-flight work retains its pinned target. Never
remove a tenant volume to perform an image rollout.

No unresolved product decision. No staging mutation is part of this code change.
