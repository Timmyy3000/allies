# Cross-device message queue integration

Cloud owns accepted messages and FIFO execution. Both the web HomeWorkspace and the actual Expo Cloud conversation route submit immediately while an earlier turn wakes or runs. A queued head stays in the queue until progress identifies that message. Only a Cloud-declared unclaimed tail has a remove action.

The accepted backend plan lives in [Allies Cloud PR #29](https://github.com/alliesai/allies-cloud/pull/29) at `docs/plans/cross-device-message-queue.md`. This shared Interface branch targets `dev`; it does not transplant mobile PR #27 or the separate web visual branch.

## Contract

- `ConversationResponse.queue` contains the complete live queue, independent of the history page.
- `MessageResponse.queue_state` distinguishes `claimed`, `unclaimed`, and terminal `null`; `deleted_at` identifies redacted tombstones with existing `status: stopped`.
- `ActivitySnapshotResponse.active_message_id` identifies the head represented by the snapshot state.
- `DELETE /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}` returns the same tombstone on repeated deletion; a claim winner returns `409 message_not_deletable`.
- The native transport authenticates send, retry, and delete with a native bearer. Cloud preserves browser origin/CSRF validation and tenant isolation.

The pinned schema was generated from the companion Cloud feature worktree's local OpenAPI endpoint, not from a deployed feature. Metadata retains the canonical Cloud source URL by the existing fetch-script convention. It includes the already-implemented Cloud `dev` manual-code auth contract and regenerated operation IDs. Deploy Cloud before relying on the new remove controls; older responses without queue metadata expose no new Cloud delete action.

## Recovery and compatibility

Web persists unknown sends before I/O and drains account-scoped intents without waiting for execution. Account-ambiguous legacy storage remains untouched. Mobile retains its existing single encrypted unknown command and retries its exact idempotency key after reopening. Neither client treats a lost response as proof that Cloud rejected a send. Tombstones and terminal/claim state win over stale cached message copies.

The native route refreshes the newest page while visible, backs off failures, and slows activity polling after two minutes. It preserves loaded history and aborts mutations on route/account replacement. Queue removal errors preserve content and refresh authoritative state.

Mobile PR #27 merged at `7aa1aa04f74fd4dfa7d220d6103e28c27cd6372b` into `mobile/consolidated-app`, not `dev`. When reconciling that line:

1. Preserve its session identity/generation guards, replay catch-up, reply selection, and visual composition.
2. Remove `!active` from its send eligibility while retaining persistence, synchronous mutation exclusion, auth, and error checks.
3. Port the complete queue projection and remove action; select the claimed head using `active_message_id`, not the latest tail.
4. Carry over tombstone merges, keyed pending-command clearing, native retry/delete authentication, and the route tests. Run that branch's conversation/replay tests before merging it.

## Validation and rollout

Run `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint`, `bun run build:web`, and `bun run bundle:mobile`. Hosted CI additionally checks browser chat frames and Ally motion. Focused route tests cover sends behind a waking head, tail-only removal, cross-device refresh, ambiguous retry, restored encrypted work, and storage read failure; shared tests cover tombstone replay and exact head correlation.

No provider message, deployment, merge, or change to the root visual checkout is part of validation. Rollback must preserve Cloud's serial dispatcher until existing queues drain; disabling client queue controls alone does not safely permit restoring the old dispatcher.
