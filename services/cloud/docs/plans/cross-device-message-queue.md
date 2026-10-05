# Cross-device message queue

## Objective and scope

Make Cloud the durable queue for every accepted conversation message. A user may submit while an Ally is waking or executing; the message must appear after reload and on web or mobile, execute FIFO with one active turn per Ally, and remain removable only until Cloud claims it for execution.

This work changes Allies Cloud plus the shared Cloud client and both Interface consumers. Foundry remains unchanged: its existing profile-scoped lease admits one active execution, its execution-intent endpoint is idempotent, and it accepts positive turn ordinals without requiring them to be contiguous. Push delivery, steering, priority, reorder, cancellation of active work, and visual redesign are out of scope. Current `dev` is the implementation baseline; Interface PR #27 is compatibility evidence for the mobile conversation route and must not be imported wholesale.

## Contract and invariants

Cloud continues to own conversation, authorization, message order, and delivery state. The existing `Message.status` values remain unchanged for deployed-client compatibility. Add two nullable timestamps to sent user messages:

- `execution_claimed_at`: the durable point after which the message cannot be deleted and may be dispatched to Foundry.
- `deleted_at`: an unclaimed-message tombstone. A tombstone keeps the message ID, sequence, send-key digest, and content fingerprint, clears its content and outbox command bytes, and uses existing terminal `status: stopped`; `deleted_at`, rather than `stopped`, identifies deletion.

Extend public message JSON with `queue_state: "claimed" | "unclaimed" | null` and `deleted_at: datetime | null`. `queue_state` is `claimed` or `unclaimed` only for live sent user turns; terminal and tombstoned records return `null`. A client derives removability only from `queue_state == "unclaimed"`, `status == "queued"`, and `deleted_at == null`.

Extend `ConversationResponse` with `queue`, ordered by `(sequence, id)`, containing every nonterminal sent user message. Bound it to the configured maximum pending messages plus one non-queued active head (at most 101 under the existing validated settings); this makes the full live queue authoritative even when the normal history page is 50 rows. Normal paged `messages` includes redacted tombstones so a same-ID tombstone wins over stale optimistic or older-page copies; clients omit tombstones from rendering.

Extend the activity snapshot with nullable `active_message_id`. It names the claimed nonterminal head whose activity/state/reply is being reported. A newly claimed head remains visually `queued` until an activity or durable reply correlated to that ID shows backend progress.

Add idempotent `DELETE /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}`. It returns the tombstoned `MessageResponse` on the first and repeated delete, returns `409 message_not_deletable` for a claimed or otherwise non-queued message, and preserves the existing indistinguishable `404` for a foreign workspace/conversation/message. Send, retry, and delete all use `_require_origin(..., allow_native_bearer=True)`: browser calls still require trusted origin and CSRF, while a bearer-only request must resolve a live native-kind session. Mixed cookie/bearer transport, revoked or wrong-kind bearer sessions, and foreign workspace membership fail closed before mutation.

The following ordering rules are mandatory:

1. Acceptance allocates an immutable sequence and outbox as today. Under the existing conversation lock, the claim helper selects the earliest nonterminal send whenever no claimed live turn exists; it never skips an older unclaimed row to claim the new message. Later rows stay unclaimed and deletable.
2. Dispatch workers select only rows whose message has `execution_claimed_at`, is not tombstoned, and is the earliest releasable live turn. Foundry acceptance does not release the next message.
3. A terminal Foundry projection updates the current message, claims the next unclaimed queued message in the same conversation-locked transaction, and schedules its durable outbox only on commit. A failure may terminalize and release the head without a Foundry event only when it is proven before any Foundry create/reconcile call, such as a local invalid command, unavailable/incompatible binding, or invalid onboarding handoff. Once any Foundry call starts, conflict/rejection, malformed or mismatched receipt, retry exhaustion, unknown outcome, and inconclusive reconciliation all keep the message claimed and block release until a valid terminal projection or explicit operator repair. `DispatchState.FAILED` alone never proves release is safe.
4. Delete takes the same conversation-before-message/outbox lock order as claim/release. Whichever transaction wins determines the outcome: deletion terminalizes the outbox before claim, or claim makes delete return `409`. No physical row deletion or resurrection is allowed.
5. An exact resend of a deleted message's idempotency key and content returns its redacted tombstone as a replay and never recreates the outbox; different content with that key remains a conflict.

## Implementation phases

### 1. Persist claim and tombstone state in Cloud

- Update `backend/chat/models.py` and a new `backend/chat/migrations/0006_*.py` with the timestamps, indexes for live FIFO selection, and checks limiting deletion/claim state to coherent sent-user records. Do not add a new message lifecycle or queue model.
- In the migration, conservatively mark as claimed every live message whose outbox was attempted (`last_attempt_at` set) or is no longer pristine `pending`, then mark the earliest live message that already has an outbox when no claimed head exists. If the earliest live row has no outbox, leave it and every later row unclaimed so the normal claim path can rebuild the missing outbox without skipping FIFO. Multiple already-dispatched legacy rows may remain claimed and nondeletable; they drain in sequence and must not be reclassified as safe to delete.
- Keep queue admission bounded by the existing `ALLIES_CHAT_MAX_PENDING_MESSAGES`; exclude tombstones from pending counts while allowing one separately active non-queued head.
- Add a deployment setting that can pause admission of a new tail behind any nonterminal send while preserving exact idempotent replays and first-message acceptance. This is the rollback compatibility guard; disabling queue admission must not disable claim, projection, deletion, or draining existing rows.

### 2. Serialize Cloud release and protect deletion

- Refactor the existing helpers in `backend/chat/services/dispatch.py` and `backend/chat/services/messages.py` rather than creating another queue service. One conversation-locked helper should claim the earliest eligible message, be idempotent, and schedule only after commit.
- Make `_claim_due` ignore unclaimed/tombstoned outboxes. Replace `_prior_turn_ready`'s current `DispatchState.ACCEPTED/FAILED` admission with the message-terminal/deleted invariant; an accepted outbox whose message has no terminal projection still owns the serial slot.
- Invoke release from `backend/activities/services/projection.py` only after a valid terminal event is durably applied or from the narrowly enumerated pre-call failures. Centralize the pre-call/post-call boundary so no generic `FAILED` branch releases work. Keep duplicate terminal events as no-ops and preserve projection's prior-turn gap checks.
- Add the authorized tombstone mutation and stable errors in `backend/chat/services/messages.py`, `backend/chat/api/{schemas,controllers}.py`, and `backend/chat/exceptions.py`. Apply the existing native-bearer origin exemption consistently to send, retry, and delete, then let `resolve_request_session` reject mixed, revoked, or wrong-kind transports. Clear content and command bytes only after the same lock proves the message is unclaimed; do not cancel or call Foundry.
- Adjust conversation and activity projections so `queue` is complete and bounded, tombstones reconcile by ID, and state/reply selection follows `active_message_id` instead of the newest queued tail.

### 3. Publish and consume the shared contract

- Regenerate Cloud OpenAPI and update `packages/cloud-client/src/generated/openapi.ts`, `packages/cloud-client/src/mappers/allies.ts`, and `packages/cloud-client/src/client.ts` for `queue`, `queue_state`, `deleted_at`, `active_message_id`, and the delete method. Add retry and DELETE to `apps/mobile/src/lib/cloud/native-cloud-client.ts`'s authenticated-request matcher; keep send covered.
- Make mapper/cache merges treat `deleted_at` as authoritative mutable state, remove tombstones from rendered history, and use `conversation.queue` for claimed/unclaimed queue presentation. Correlate activity and replies with `active_message_id`; do not infer claim state from `status: queued`.

### 4. Migrate web acceptance to Cloud-first queueing

- In `apps/web/app/home/home-workspace.tsx` and its focused helpers/tests, persist a new send locally first, POST it immediately even while another turn is waking/running, then remove the local copy only after a definitive Cloud acceptance or tombstone replay. Unknown/offline results retain the exact content and idempotency key for retry.
- Drain existing user-scoped `v2` local entries in `queuedAt` order using their stable intent keys, without waiting for the active turn to finish. Preserve the account-ambiguous `v1` raw value untouched and show recovery guidance; never delete it or auto-attribute it to the current account.
- Reconcile Cloud `queue` with the local unknown-acceptance outbox by idempotency attempts and message/tombstone IDs. Use the existing `QueueStack`: claimed items remain visible without a remove action, unclaimed items call Cloud DELETE, and local-only items use the existing local tombstone path. Remove the `turnInProgress` submission/dispatch gate while retaining bounded local storage and same-tab/cross-tab serialization.
- Update active-turn selection so the claimed head drives thinking/polling; later queued messages stay queued and cannot steal the current activity/reply.

### 5. Apply the same contract to mobile and verify PR #27 compatibility

- On current `dev`, update `apps/mobile/src/app/allies/[allyId]/index.tsx`, its shared conversation-state/tests, and the native authorization matcher. In the real Cloud route behind the current mock-mode conditional, preserve its current activity-independent send eligibility, render the authoritative Cloud queue, call Cloud DELETE only for unclaimed rows, and correlate polling/replies to `active_message_id` while retaining existing session-generation/abort guards.
- Retain mobile's encrypted single unknown send per conversation. It already persists before I/O and POSTs immediately; after one acceptance it may submit another while the prior turn runs. Do not introduce an offline batch queue. Keep an ambiguous send for exact replay, reconcile tombstones without resurrecting content, and preserve cross-account clearing.
- Inspect the same route at PR #27 merge `7aa1aa04` and leave focused integration notes for its differing session/polling composition, including removal of that branch's `!active` send gate. Do not copy PR #27's unrelated auth, onboarding, assets, web tree, CI, or documentation into the `dev` worktree.

## Acceptance criteria

- Two web/mobile/browser sessions show the same accepted FIFO queue after refetch or reload; a later submission is durably accepted while the head is waking or running.
- At most the claimed head is released by new Cloud behavior. The next message is not posted to Foundry until the prior message has a terminal projected outcome; Foundry still allows only one active profile lease.
- The claimed head has no remove action and DELETE returns `409`. An unclaimed tail can be deleted from either client; concurrent claim/delete has one durable winner and never executes deleted content.
- A deleted tail disappears on both clients, remains a redacted tombstone for idempotency/cache reconciliation, and exact retry cannot resurrect it. Tenant-crossing reads/deletes remain indistinguishable `404`s.
- Lost acceptance responses, process restarts, duplicate tasks/events, and reconciliation retry do not duplicate execution or advance the queue early. Unknown Foundry outcomes keep the serial slot claimed.
- Native bearer sessions can send, retry, and delete through the same Cloud contract. Revoked, wrong-kind, and mixed cookie/bearer transports fail without mutation; browser mutations still require valid origin and CSRF.
- Web restores and drains scoped `v2` work without discarding it; legacy `v1` raw storage remains intact and is never sent under an unverified account. Mobile retains its encrypted pending command across offline/reload and never attributes it across accounts.
- The accepted head remains labelled `Queued` until activity/reply for its own `active_message_id`; later messages remain queued and cannot receive the head's progress.

## Validation

Cloud focused checks, from the Cloud repository root:

```powershell
make test APP=chat/tests/test_services.py
make test APP=chat/tests/test_dispatch.py
make test APP=chat/tests/test_api.py
make test APP=chat/tests/test_queue_api.py
make test APP=activities/tests/test_cld005.py
make test APP=chat/tests/test_postgresql_concurrency.py
make check
make lint
```

Add risk-based tests for queue admission and ordered claim/release, terminal versus accepted outbox behavior, replay after tombstone, redaction, duplicate delete, cross-tenant delete, and delete/claim plus concurrent-send races. Prove that each enumerated pre-call failure releases the next turn, while every ambiguous post-call `FAILED`/conflict/receipt/reconciliation path retains the claim. Exercise browser origin/CSRF success and rejection plus live native-kind, revoked, wrong-kind, and mixed cookie/bearer cases for send, retry, and delete. Test the rollback admission guard: it rejects only a new tail, permits exact replay and a first turn, and existing queues continue draining. Run PostgreSQL concurrency evidence in CI with `uv run pytest -m postgresql`; the local Docker daemon is unavailable, so local SQLite results cannot establish row-lock behavior.

Interface focused checks, from the Interface repository root:

```powershell
bun run cloud:check
bun run test:run -- packages/cloud-client/test/allies.test.ts packages/cloud-client/test/client.test.ts packages/cloud-client/test/activity-projection.test.ts
bun run test:run -- apps/web/app/home/home-workspace.test.tsx apps/web/app/home/conversation-frame-model.test.ts apps/mobile/src/features/conversation/conversation-state.test.ts apps/mobile/src/lib/pending-command-store.test.ts apps/mobile/src/lib/cloud/native-cloud-client.test.ts
bun run typecheck
bun run lint
bun run build:web
bun run bundle:mobile
```

Cover web active-turn submission, v2 ordered recovery, untouched v1 storage, cross-tab dedupe, Cloud deletion rollback/error, tombstone-wins cache merges, and head-correlated progress. Cover the PR #27 mobile integration patch with its conversation-route tests before merging into that line. The hosted suites remain the final evidence for PostgreSQL concurrency, all Interface tests, browser frame regressions, and iOS export.

## Risks, rollback, and open decisions

- **Legacy ambiguity:** older deployments may already have several accepted Foundry executions. The migration treats attempted rows as claimed and nondeletable. It terminalizes only failed outboxes with no receipt/event evidence and either no acquired dispatch fence or a first-fence error unique to the pre-call path (`binding_incompatible` or either onboarding handoff error). Missing receipts alone never prove no execution: `binding_unavailable` is written both before and after a call, and later-fence failures may follow an unknown call. Remaining failed live heads require reconciliation before rollout; they cannot be assumed to drain automatically.
- **Projection loss:** Cloud cannot prove an accepted execution terminal from outbox state. Reconciliation exhaustion therefore blocks serial release and needs existing operational repair; it must never silently advance the queue.
- **Client skew:** old clients ignore additive fields and continue to show `stopped` tombstones as stopped messages if they receive them. Keep tombstones redacted and additive, deploy Cloud/shared contract before enabling new remove controls, and rely on new clients to hide `deleted_at` rows.
- **PR #27 drift:** `dev` and PR #27 both contain the mobile route but have different surrounding composition. Implement and test `dev` directly, then reapply only the listed queue changes when reconciling PR #27; resolve against its session and polling guards rather than transplanting files.

Rollback is staged for compatibility. First disable new queue/remove controls in actual web and mobile clients and turn off Cloud tail admission, while leaving serial claim/release, tombstone interpretation, and activity correlation deployed. Then verify the drain condition: no nonterminal unclaimed messages, no conversation with more than one nonterminal claimed message, and no claimed head with a pending, in-progress, accepted, reconciliation-needed, or failed outbox lacking terminal projection. Record a tested read-only ORM check for those counts and require all to be zero before restoring an older dispatcher. Retain the additive columns and tombstones through the compatibility window. Never roll back by clearing claim timestamps, physically deleting tombstones, replaying outboxes, or converting unknown outcomes to unclaimed work.

No material product decision remains open. Operationally, the implementation PR must call out that local PostgreSQL race validation is unavailable and require the hosted PostgreSQL job before merge readiness.

Before applying the queue migration, quiesce every old dispatch worker and scheduler and wait for its in-flight dispatch calls to settle. Disabling `ALLIES_FOUNDRY_EXECUTION_ENABLED` on the old fleet is an alternative only after that configuration has reached every instance and no old invocation remains in flight. Admission pause alone is insufficient: the old dispatcher does not honor claims and could send an existing tail during or after the migration. Keep dispatch quiesced until every app/worker instance runs the new claimed-only dispatcher; start that version with `ALLIES_CHAT_QUEUE_ADMISSION_ENABLED=False`.

After migration and fleet replacement, run this read-only preflight before enabling admission or rolling out the clients. Every count must be zero. Repair missing commands through the existing acceptance path using the original message identity. For attempted rows, reconcile the existing message ID and command fingerprint with Foundry or obtain valid terminal projection; do not infer rejection from missing receipts, clear claims, or resend with a new identity. A later claimed turn behind an earlier unclaimed turn also blocks rollout, even after its missing command is repaired. Once the preflight passes, resume only the new dispatcher, then enable tail admission and roll out the clients.

```python
from django.db.models import Exists, OuterRef
from chat.models import Message, NONTERMINAL_MESSAGE_STATUSES

live = Message.objects.filter(
    sender="user", origin="send", status__in=NONTERMINAL_MESSAGE_STATUSES,
    deleted_at__isnull=True,
)
claimed_live = live.filter(execution_claimed_at__isnull=False)
earlier_unclaimed = live.filter(
    conversation_id=OuterRef("conversation_id"),
    sequence__lt=OuterRef("sequence"), execution_claimed_at__isnull=True,
)
print({
    "unresolved_legacy_failed_heads": claimed_live.filter(
        dispatch_outbox__status="failed",
    ).count(),
    "unresolved_legacy_missing_outbox": live.filter(
        dispatch_outbox__isnull=True,
    ).count(),
    "out_of_order_legacy_claims": claimed_live.filter(
        Exists(earlier_unclaimed),
    ).count(),
})
```

The PostgreSQL test module is explicitly marked `postgresql`; verify collection selects its claim/delete and stale-fence tests under the same `pytest -m postgresql` selector used by CI.

After disabling tail admission, the following read-only Django shell check conservatively requires every live send to drain, including claims whose outbox is missing or uncertain. Both counts must be zero before restoring an older dispatcher; never print message content or clear claims to make this check pass.

```python
from chat.models import Message, NONTERMINAL_MESSAGE_STATUSES

live = Message.objects.filter(
    sender="user", origin="send", status__in=NONTERMINAL_MESSAGE_STATUSES,
    deleted_at__isnull=True,
)
print({
    "unclaimed_live": live.filter(execution_claimed_at__isnull=True).count(),
    "claimed_live": live.filter(execution_claimed_at__isnull=False).count(),
})
```
