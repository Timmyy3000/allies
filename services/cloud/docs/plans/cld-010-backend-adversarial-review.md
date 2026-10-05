# Adversarial Review

## Verdict

Ready. All three findings are resolved in the revised plan. The findings table preserves the original review evidence; the dispositions below record closure.

This independent review covers the expanded Cloud and Foundry plan. It does not authorize implementation. No product code or plan content was changed.

## Findings

| ID | Severity | Area | Evidence | Impact | Required plan change |
| --- | --- | --- | --- | --- | --- |
| BADV-001 | Major | Recovery before Cloud registration | Plan, “Foundry functions and durable shapes” and “Model-facing publication capability”: freeze and journal commit precede Cloud reservation. “Foundry transport and recovery wiring” discovers work only through Cloud retry claims and due bindings. Active reservation requires a current attempt lease. | If Cloud reservation fails, or the worker dies after freeze and before reservation, Cloud has no publication row or due binding. After the attempt ends, the stated recovery protocol cannot register that frozen version. The tool can report a failed publication ID that the user cannot retrieve or retry. | Define durable discovery and idempotent registration for frozen but unregistered journals, including authority after the source attempt ends and recovery after a sleeping-machine restart. Keep the same publication ID and bytes. Specify how Cloud exposes the recoverable failure. Add crash tests before reservation, after uncertain reservation, and after attempt completion; assert no model rerun. Use existing persistence where possible. |
| BADV-002 | Major | Local volume limits | Plan, “Model-facing publication capability”: freeze copies up to 50 MB before Cloud reservation. “Foundry transport and recovery wiring”: spools remain until ready or explicit deletion. The 10 GB account limit in “Storage, inspection, retention and access” covers Cloud objects. No local spool admission, total byte limit, or partial-copy cleanup is defined. | Repeated failed or quota-rejected publication calls can fill the durable runtime volume. This can stop model work, journal commits and cleanup for other profiles on the volume. Cloud limits do not bound bytes copied before Cloud admission. | Define bounded local spool admission with per-profile and shared-volume accounting, a disk reserve, and a safe capacity error before copying. Preserve accepted retry bytes. Specify bounded recovery and removal of incomplete, uncommitted copies after a crash. Add repeated rejection, concurrent profiles, disk-full and restart tests. Do not silently age-delete a committed retry version. |
| BADV-003 | Major | Concurrent Foundry delivery | “Current evidence” and Phase 6 use Foundry dev `1d03ea557be757f4eca4c6b6478d542291169b14` but omit the fetched `origin/ft/fnd-012-routine-conversations` coordination requirement. The branch diff includes `backend/runtime/contracts.py`, `services/claims.py`, `services/workspaces.py`, `runtime/allies_runtime/foundry.py`, API registration and runtime lifecycle services. | F1/F2/F4 change the same contract, claim and worker paths. Validation against the present dev base alone cannot establish compatibility with the pending routine execution path. A later merge can lose optional fields, alter fingerprints or omit recovery work from a worker path. | Record the overlap and an explicit merge-order/rebase gate before implementation and before Foundry PR merge. Preserve both execution variants. Run relevant routine and file contract/worker tests on the combined revision, including unchanged text/bootstrap fingerprints and empty-text file input. Record both source SHAs. Coordinate this work without adding routine implementation to FND-011. |

## Narrow Recheck Dispositions

- BADV-001: Resolved. The durable PublicationIntent, pre-freeze acknowledgement, current-generation recovery authority, startup discovery and wake discovery address the registration gap. The final correction makes the status endpoint create-only under the same publication identity lock as reserve. Existing matching IDs return current state without mutation; ancestry mismatch returns 409. Delayed, duplicate, concurrent and foreign-ancestry tests are specified. This closes the introduced status-ordering concern.
- BADV-002: Resolved. Per-profile and shared-volume limits, free-space reserve, durable reservation accounting, bounded incomplete-copy cleanup and disk-full/restart tests address the finding. Committed frozen versions remain protected.
- BADV-003: Resolved. The coordination section requires current heads, both source SHAs, merge-order agreement and routine/file tests on the combined revision before affected merges.

The recheck covered only these findings and the new recovery interactions. No unrelated controls were reopened.

## Missing Owner Decisions After Recheck

- Confirm the proposed local spool limits and minimum free disk capacity through the existing operational policy review before enablement. The plan now states concrete defaults.
- The existing deletion-entrypoint, aggregate-capacity and decoder/scanner release decisions remain explicit. They are not new findings.

## Residual Risk

- Filesystem isolation needs image evidence. The plan correctly makes separate runtime/Hermes identities and two-profile denial tests an enablement gate. The inspected runtime Dockerfile does not currently establish a non-root identity. No isolation claim is accepted from source alone.
- Backend acceptance and later Interface/device acceptance are correctly separate. Neither unit tests nor fake-provider continuity tests establish real-device behavior.
- No feature tests ran during this planning review. The source snapshots supplied by the caller were used as canonical evidence pointers; this worker did not refresh Nabu.

## Review Metrics

- Started at: 2026-09-09, independent worker session.
- Completed at: 2026-09-09.
- Evidence opened: adversarial-review skill; Cloud AGENTS.md and ENGINEERING_STYLE.md; episode-state.md; cld-010-brief.md; cld-010-file-sharing.md; cld-010-foundry-source.md; relevant cld-010-sources.md excerpts; Foundry runtime/Dockerfile; relevant runtime/allies_runtime/foundry.py and profile_store.py excerpts; fetched FND-012 branch changed-path diff.
- Findings by severity: Original Major 3; unresolved 0 after narrow rechecks.
- Independent worker: yes.
