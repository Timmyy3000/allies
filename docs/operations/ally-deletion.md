# Ally deletion and recovery

Cloud accepts deletion only for the authenticated workspace owner after exact
confirmation with the current Ally name followed by ` - deletes me`. Acceptance
fences new work. Completion requires a matching Foundry quiescence receipt,
verified object/version absence, released storage accounting and removal of the
Ally's protected product graph. Only a content-free workspace/Ally-ID marker
remains. Other allies and shared workspace infrastructure remain available.

Deploy compatible Foundry backend and runtime/Hermes capability first, Cloud
second, Interface last. The matching internal contract is
[`foundry-profile-deletion-v1.json`](../contracts/foundry-profile-deletion-v1.json).
The implementation plan lives in the Interface repository at
`docs/plans/beta-labels-deletion.md`.

## Inspect a repair

Use the existing authorized Cloud operator shell. Resolve the exact workspace
and Ally IDs from the incident, then inspect only the matching
`allies.models.DeletionOperation`: `id`, `workspace_id`, `ally_id`, `state`,
`stage`, `attempt_id`, `foundry_attempt_id`, `safe_error_code` and `expires_at`.
The public UI exposes progress but does not expose an operator resume endpoint.
Do not log the Ally's name, job, file keys or other content in incident summaries.

The operation retains its references until cleanup succeeds. A failed HTTP
response, expired lease or elapsed deadline does not prove that remote work
stopped. Inspect the indicated runtime/storage failure before resuming:

- Runtime closure failure: repair the target-owned resource or capability and
  obtain checked closure. Unknown process/browser ownership must remain blocked;
  never terminate a shared runtime merely to manufacture a target receipt.
- Storage retry exhaustion: restore supported versioning/retention inspection and
  exact-key erase/absence verification. A delete acknowledgment or current-object
  404 does not prove historical versions are absent.
- Ambiguous or in-flight storage I/O: establish definitive provider-side completion
  or abort for the exact registered write before changing its outcome. HEAD absence,
  a client timeout, stopping a local worker or waiting longer is insufficient proof.
  If definitive evidence is unavailable, retain the candidate and keep repair open.

For a verified write outcome, record the provider evidence in the incident
system, then run the guarded command from `backend/`:

```sh
uv run --locked python manage.py settle_ally_deletion_file_write \
  --workspace-id WORKSPACE_UUID --ally-id ALLY_UUID --file-id FILE_UUID \
  --write-fence INSPECTED_WRITE_FENCE_UUID --key EXACT_RECORDED_KEY \
  --outcome completed
```

Use `aborted` instead of `completed` only for a definitively aborted write. The
command checks the deleting Ally's workspace, file, fence and exact key under
locks, accepts only these two outcomes, and updates exactly one unresolved
candidate. It rejects active allies, stale identities and already-settled writes.
It does not print the object key. It preserves the candidate: ordinary cleanup
must still erase and verify all recorded objects/versions afterward. There is no
automatic conversion of ambiguous writes to settled writes.

## Resume a repaired attempt

From `backend/`, using the deployment's existing operator environment:

```sh
uv run --locked python manage.py resume_ally_deletion \
  --workspace-id WORKSPACE_UUID \
  --ally-id ALLY_UUID \
  --expected-attempt-id INSPECTED_ATTEMPT_UUID
```

All three arguments require canonical UUIDs. Use the inspected current repair
attempt. The command verifies target scope, creates one successor epoch, resets
only the target's exhausted cleanup retries and enqueues reconciliation after
commit. It preserves unresolved write outcomes. Repeating the same resume while
the successor is pending is idempotent; a different stale attempt is rejected.
The command prints opaque identifiers and state, not content.

Reinspect the operation and the public deletion status after reconciliation. An
accepted resume is not completion. If another failure occurs, inspect and repair
that failure before resuming its new attempt. Never clear admission fences or
restore the Ally to active to work around a failed deletion.

## Retention and rollback

This protocol verifies active application stores. It does not alter infrastructure
backup/log retention or external providers' retention. Do not promise all-copy
erasure without separate evidence for those stores.

To pause rollout, disable new deletion acceptance while preserving recovery and
all existing fences/markers. Completed deletion is irreversible. A code rollback
must not restore deleted content or allow stale work to recreate the Ally.
