# CLD-010 simplicity review

Independent Astra low review, 2026-09-09. Verdict: Lean. No required revisions.

| ID | Classification | Area | Retained mechanism and reason |
| --- | --- | --- | --- |
| SIM-001 | Keep | Returned-file recovery | Publication-owned retry state and the existing scheduled-worker pattern support retry after polling stops or a process restarts. No retry-job table. |
| SIM-002 | Keep | Draft reuse and cleanup | MessageFile/FileDraftFile relations and file locks protect queued reuse and consistent cleanup/accounting. No reference counters. |
| SIM-003 | Keep | Ordered delivery and compatibility | Extend the queue gate, exact-byte outbox and shared Interface projection to preserve ordered, complete delivery and text-only compatibility. |

## Complexity delta
Six phases remain six. Layers, dependencies, configuration and touched surfaces are unchanged. The plan already avoids a generic job system, reference-count table, new public stream event, parallel execution delivery path and competing Foundry workspace lifecycle.

## Protected complexity
- Publication recovery must survive the end of interactive polling. Revision, lease and generation checks protect different stale operations.
- Separate draft storage preserves restoration while the accepted cancellation contract redacts message tombstones. Indexed relations protect ready bytes during reuse and cleanup.
- Preparation failures block later messages, unlike existing execution failures.
- Isolated inspection and inert previews preserve the approved privacy and active-content controls.

## Feedback and evidence
No scope-preserving removal was justified. Keep publication rows as retry owners, file relations as reference protection, scheduler/outbox reuse, and Foundry workspace continuity ownership.

The reviewer inspected policy, brief, state, configuration, revised plan, adversarial findings, source snapshots, and focused queue/gateway/scheduler references. Canonical evidence came from revision-labelled snapshots, not a fresh Nabu read. No files changed or product tests ran. Exact review times were not recorded. Zero simplify/remove findings. The planner was separately correcting ADV-003; this review does not replace the focused correctness verification.
