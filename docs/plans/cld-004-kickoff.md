# CLD-004 Conversation and Message Lifecycle

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: workflow default, existing repository kickoff configuration
- Planning worker: configured `sol_planning_worker`
- Planning worker source: `allies-cloud/.agent/kickoff.yaml`
- Review worker: configured `sol_review_worker`
- Review worker source: `allies-cloud/.agent/kickoff.yaml`
- Implementation worker: configured `luna_execution_worker`
- Implementation worker source: `allies-cloud/.agent/kickoff.yaml`
- Planning mode: full; cross-repository conversation contract, persistence, authorization, idempotency, and concurrency work
- Worktree manager: forest
- Branch: ft/cld-004
- Worktree path: E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\cld-004
- Task workspace: E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\cld-004\docs\plans
- Created: 2026-08-24
- Target date: not specified
- Current phase: validation

## Objective

Implement Cloud ownership of one default customer-facing conversation per Ally and a durable, idempotent, Workspace-authorized text-message lifecycle. Accepted messages begin in `queued`, remain durable across disconnects and downstream delay, and expose only Allies product identifiers and language. Conversation IDs are the message-operation boundary so future group or multi-agent conversations can have independent conversation records.

## Context

The canonical Nabu specification is `projects/allies/engineering/specs/cld-004-conversation-and-message-lifecycle.md` and is Ready for Plan. The delivery ticket is `projects/allies/delivery/tickets/cloud/CLD-004.md`. CLD-003 is approved and complete, including the official-onboarding greeting and reply handoff. Affected systems are `allies-cloud` and `allies-interface`; CLD-005 owns Foundry execution acceptance/projection and CLD-006 owns replay, reconnect, stop, retry, and failure recovery.

## Requirements

- Model one default conversation per Ally while keeping conversations first-class and addressed by conversation ID.
- Preserve the CLD-003 onboarding greeting and user reply exactly once and in order.
- Accept text messages exactly once using caller idempotency keys; duplicate requests return the original message/projection and changed-content reuse conflicts.
- Persist accepted messages with one lifecycle enum: `queued`, `in_progress`, `completed`, `failed`, or `stopped`.
- Accept additional valid sends in deterministic order behind the active turn with a bounded pending queue; reject only new sends when full.
- Enforce current Workspace authorization on every read and mutation with privacy-safe foreign-resource denial.
- Load bounded recent history first and older history on demand using an opaque cursor.
- Keep Foundry, Hermes, Fly, runtime, credentials, and private identifiers out of public contracts, logs, and evidence.
- Publish the Interface-facing request/response, lifecycle, error, idempotency, conversation-addressing, and history contract.
- Keep Alpha text-only; attachment support is deferred to Beta.

## Acceptance Criteria

1. Repeated and concurrent Ally access resolves to the same conversation.
2. No Ally has two initial customer-facing conversations.
3. The onboarding greeting and reply appear once, in order.
4. Valid text creates one durable user message with status `queued`.
5. Accepted messages survive refresh, disconnect, downstream delay, and downstream failure.
6. Duplicate send keys return the original result without creating another message.
7. Changed-content reuse of a send key returns a stable conflict without mutation.
8. Invalid or oversized input creates no message or accepted work intent.
9. Concurrent sends have deterministic order; later turns wait and are never lost, merged, or concurrent.
10. Queue saturation rejects only the new send.
11. History is complete and older pages load using an opaque cursor.
12. Every protected read and mutation rechecks Workspace authorization; foreign denial reveals no existence.
13. Public responses and diagnostics expose no private runtime or provider data.
14. Interface consumes Cloud only and can distinguish message state without calling Foundry.
15. Migration, API, authorization, idempotency, concurrency, and history evidence is recorded before completion.

## Evidence And Sources

- Nabu `projects/allies/index.md`, `projects/allies/delivery/now.md`, and `projects/allies/delivery/synchronization.md`
- Nabu `projects/allies/delivery/tickets/cloud/CLD-004.md`
- Nabu `projects/allies/engineering/specs/cld-004-conversation-and-message-lifecycle.md`
- Nabu `projects/allies/engineering/specs/conversation-and-streaming.md`
- Nabu `projects/allies/engineering/specs/auth-account-foundation.md`
- Nabu `projects/allies/engineering/specs/cld-003-create-and-manage-real-ally.md`
- Nabu `projects/allies/product/allies-first-product-requirements.md`
- Nabu `projects/allies/product/allies-product-design-spec.md`
- `AGENTS.md`, `ENGINEERING_STYLE.md`, `docs/templates/PLAN_TEMPLATE.md`, `README.md`, `Makefile`, CI configuration, and current Cloud code/tests

## Decisions

- Use a full implementation plan with Lavish presentation and independent adversarial and simplicity reviews.
- Start from Cloud `dev` in an isolated Forest worktree; leave unrelated worktrees untouched.
- Use conversation ID for message reads and sends; Ally ID resolves the default direct conversation.
- Use one message lifecycle enum beginning at `queued`; do not expose a second `accepted` status.
- Queue valid additional sends in order behind one active Ally turn with a bounded pending queue.
- Retain complete history with bounded newest-page reads and opaque-cursor pagination.
- Keep Alpha text-only; defer image/file semantics to Beta.
- Cloud remains product truth; Foundry is reached only through the later versioned execution boundary.

## Risks

- Race conditions creating duplicate conversations or message order positions.
- Idempotency records leaking across Workspaces or treating changed content as a duplicate.
- Queue saturation, duplicate sends, and downstream failures producing misleading states.
- Contract drift between Cloud and Interface as CLD-005/CLD-006 add execution and replay projections.
- Accidental exposure of provider/runtime identifiers in responses, logs, or tests.
- History pagination that loses ordering or mishandles concurrent inserts.

## Open Questions

- None blocking planning. Exact page size, cursor encoding, route names, schema field names, and internal module boundaries belong in the implementation plan and published API schema.

## Plan

Planning worker to produce the complete implementation plan and matching HTML artifact under `docs/plans/`, following `PLAN_TEMPLATE.md` and the full-plan content standard.

## Execution Notes

- 2026-08-24: CLD-003 approval was confirmed and its Nabu delivery record marked done.
- 2026-08-24: CLD-004 specification was approved by Timi and marked Ready for Plan in Nabu.
- 2026-08-24: Product decisions resolved text-only Alpha scope, conversation-ID addressing, one status enum beginning at `queued`, ordered bounded queueing, and on-demand history pagination.
- 2026-08-24: Implementation delegation remains `always`; Ponytail Full is required in every implementation packet.
- 2026-08-25: Implemented the Cloud chat app, onboarding handoff, text-only API, idempotent queue admission, cursor history, lifecycle primitives, privacy-safe diagnostics, and focused concurrency coverage.
- 2026-08-25: Simplicity review removed redundant indexing and unused/no-op seams without weakening accepted requirements.
- 2026-08-25: Code review found a shared rate-bucket rollback race. Reconciliation now clears the deterministic request marker while retaining attempted quota until normal expiry, a lean fail-closed fix reflected in the plan and regression tests.
- 2026-08-25: Validation passed Django checks, migration consistency, Ruff lint/format, focused chat and throttle suites, and the full backend suite (279 passed, 13 PostgreSQL-only tests skipped locally).

## Adversarial Review Dispositions

- Major accepted and revised: define the pending queue as at most 20 send-origin user rows in `queued`, with one active send-origin row in `in_progress`; CLD-005 owns the locked claim and terminal transitions that release capacity.
- Major accepted and revised: import the CLD-003 greeting and user reply as `origin=onboarding`, completed historical rows that do not consume pending capacity or active-turn ownership.
- Major accepted and revised: sanitize unexpected chat failures to route template, safe exception type/status, and opaque fingerprint; prohibit content, idempotency material, SQL, provider text, and traceback leakage, with caplog coverage.
- Minor accepted and revised: derive Conversation Workspace authority through Ally.workspace instead of duplicating a Workspace foreign key; add malformed-ancestry denial and monitoring evidence.
- Minor accepted for implementation planning: document cursor/HMAC schema version and expiry; key rotation remains an operational configuration concern and must not invalidate active cursors without a compatibility window.
