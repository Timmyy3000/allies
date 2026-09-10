# CLD-010 adversarial review

Independent Astra low review, 2026-09-09. Final verdict: Ready, subject to the stated release gates. All three findings are resolved.

| ID | Severity | Area | Evidence and impact | Required change | Disposition |
| --- | --- | --- | --- | --- | --- |
| ADV-001 | Major | Returned-file retry | Foundry polling stops after five minutes. A later Cloud retry or process replacement can leave publication in retry_pending indefinitely. The draft does not define discovery or failed-file generation advancement. | Define retry discovery, owner, transport, durable identity, acknowledgement, backoff and restart behavior. Retry failed files without replacing successful files or the frozen version. Test after polling stops and after process replacement, without a new model execution. | Accepted; route to planner. |
| ADV-002 | Major | Draft reuse and cleanup | Draft discard protects retained messages and other drafts, but does not explicitly protect a new accepted, unclaimed message that reuses ready bytes. Cleanup could remove a queued send's file. | Atomically transfer/add protected references on reuse. Protect all live accepted message references, serialize reuse/discard/cancel/cleanup, and define reference/accounting release. Test queued reuse then discard and concurrent operations. | Accepted; route to planner. |

## Missing owner decisions
The draft already identifies aggregate storage ceiling approval, scanner/preview deployment including HEIC decoding, and deletion-entrypoint ownership as release decisions. These findings need engineering changes, not new product decisions.

## Planner reconciliation
- ADV-001: The revised plan adds a scheduled Foundry recovery worker, bounded claim/result endpoints, fenced publication leases and persisted retry state. It preserves ready generations and requires restart and late-retry tests. Independently verified as resolved.
- ADV-002: The revised plan protects live MessageFile and FileDraftFile relations under file locks. It defines reference transfer, cleanup fencing and once-per-object accounting, with concurrent reuse/discard/cleanup tests. Independently verified as resolved.

## Focused independent recheck
ADV-001 and ADV-002 are resolved. The reviewer confirmed scheduled discovery, fenced claims/results, generation preservation, restart tests, live queued-reference protection and once-per-object accounting.

| ID | Severity | Evidence and impact | Required change | Disposition |
| --- | --- | --- | --- | --- |
| ADV-003 | Major | The new live-reference rule forbids cleanup of referenced partial uploads, while the plan requires partial staging cleanup after 24 hours. Abandoned uploads would keep staging and reservations indefinitely. | Distinguish immutable successful bytes from temporary generation staging. Fence and clean expired partial staging, preserve metadata and successful siblings, and define renewed reservation/generation on retry. Test cleanup of a referenced abandoned upload followed by retry. Also align the earlier discard wording with the full live-reference rule. | Accepted; route to planner. |

Final focused verification confirmed ADV-003 is resolved: expired staging cleanup is separate from immutable-file protection, preserves metadata and successful siblings, fences stale writers, and defines reservation release and retry. The plan includes focused tests. No implementation tests ran.

## Residual risk
Integrated Foundry and Interface proof remains required for continuity, mobile recovery and complete return retry. Scanner and preview resource limits need deployment evidence. The reviewer used the supplied revision-labelled Nabu snapshots and did not claim a live canonical re-read.

## Review evidence and metrics
The reviewer read the review skill, repository instructions, engineering policy, brief, episode state, configuration, complete plan, source snapshots, and focused queue/activity projection code. Two Major findings; no Blocker, Minor, or Question. No file edits or tests in the review worker. Exact start/end times were not recorded.
