# Conversation integrity audit remediation plan

## Feature overview

- **Problem:** The A01–A09 audit shows that a completed Foundry execution can become an incomplete, duplicated, stale, or unrecoverable conversation in Cloud, web, or mobile.
- **Outcome:** Cloud owns a durable reply prefix for every managed turn, explicitly marks replies that cross its 4 MiB hard limit, and always retains the receipts and terminal state; the existing `v1` Cloud/Foundry event contract supports long bounded executions and a valid terminal; uncertain work is reconciled under its original identity; exhausted event delivery is repairable; web and mobile recover without duplicating user intent or rendered replies.
- **Source evidence:** `.agent/audits/2026-09-04-architecture-ux-audit.md`; Nabu `projects/allies/engineering/specs/conversation-and-streaming.md` and `projects/allies/engineering/decisions/decision-log.md`; the four worktrees and bases recorded in `.agent/tasks/audit-remediation-20260905/episode-state.md`.
- **Delivery boundary:** Four PRs, ready for user review and never auto-merged: Cloud against `dev`, Foundry against `dev`, web against `web/feat/chat-frames` at `54b4ea1`, and mobile against `mobile/consolidated-app` at `bc67ce0`.

## Scope

### In scope

- A01: durable assistant reply storage and an additive conversation response that does not change existing message sequence semantics.
- A02: one explicit managed-event sequence budget, support beyond event 513, and a terminal sequence that remains valid at budget exhaustion.
- A03: explicitly safe terminal-only fresh retry; uncertain accepted, stopped, failed, or dispatch-reconciliation outcomes keep the original command/execution identity.
- A04: automatic bounded repair after a delivery cycle is exhausted or its final claim crashes, plus an idempotent operator re-drive from the retained `ExecutionEvent`.
- A05–A07: mobile durable-history hydration, activity replay for a live turn, continued focused updates with backoff, editable drafts while work runs, and exactly-once reply selection.
- A08: SSE remains available behind its existing flag but defaults off; bounded replay/polling is the default path until deployment capacity is proven.
- A09: every web send is persisted with its original idempotency key before the first request and remains recoverable across reload and unknown acceptance.
- Tenant/account checks, authorization, generation fencing, payload sanitation, existing generated UI geometry, and public Foundry content restrictions remain acceptance requirements.

### Out of scope

- New services, queues, transports, or client state frameworks.
- Stop/approval/routine product work, native sign-in release proof, volume backup policy, and other already-known release gaps.
- Direct Interface-to-Foundry access, Hermes contract changes, production deployment, merge, or broad UI redesign.
- Backfilling assistant replies that Cloud never retained before this change; existing activities remain readable as legacy history.

### Dependencies and assumptions

- Cloud already has signed cursor replay and clients already understand the legacy activity projection. The additive reply field and opt-in SSE flag preserve old consumers.
- Foundry's durable `ExecutionEvent` retains the canonical event payload after an outbox envelope is delivered or exhausted, so repair can rebuild the exact envelope without re-running Hermes.
- The Hermes adapter retains its existing 4 MiB stream, 16 KiB safe event text, 256 KiB raw event, and 65,536 buffered-event bounds. Cloud's durable reply has the same 4 MiB hard byte limit: the existing prefix remains valid, a delta that would cross it is suppressed from stored text, and the reply is marked truncated while its receipt is still recorded. The ordinary 64 KiB activity text limit only suppresses visible activity rows; it never gates receipts, terminal state, or the durable reply prefix.
- The audit reproductions are regression evidence. Tests that currently assert suppression/rejection are rewritten to assert the corrected outcome.
- The mobile stacked fix includes the latest base `bc67ce0` and preserves the onboarding glass input tint and restored glass rendering from `92c1077` and `5d3e172`; conversation recovery must not replace those newer changes. The web stacked fix includes the latest `web/feat/chat-frames` base `54b4ea1`.
- Nabu's accepted “Message retry recovery” note currently allows a fresh turn for a demonstrably stale message. A03 intentionally supersedes that timing rule: stale or missing callbacks are uncertain, and only an authenticated `execution.failed` payload with `retryable: true` permits a fresh retry. Update that canonical note after implementation is accepted.

## Shared contracts and invariants

### Cloud/Foundry managed event contract (`schema_version: "v1"`)

The event vocabulary, payload shapes, fingerprints, event IDs, and dedupe keys stay unchanged. Both repositories define named constants for these sequence bounds:

| Producer/consumer rule | Contract |
| --- | --- |
| Foundry runtime event reports | `attempt_sequence` is `1..100000` for nonterminal events. |
| Foundry terminal reports | `attempt_sequence` is `1..100001`; `100001` is reserved so exhaustion at ordinary event `100000` can still produce `execution.failed`. |
| Foundry durable event row | Continues to allow `1..100001`; duplicate event ID/sequence replays must match the stored stream, type, and payload digest. |
| Cloud envelope validation and receipts | Accept `1..100001`, require the next contiguous attempt sequence, retain one immutable receipt per accepted event, and enforce the cap from the validated incoming `attempt_sequence` rather than an aggregate receipt count. The visible activity budget never gates receipts. |
| Budget exhaustion | The runtime closes the Hermes stream, emits one safe `execution.failed` terminal at the next valid sequence with code `event_budget_exhausted`, and never starts a replacement execution. |

If both identical terminal requests lose their responses, the runtime leaves the lease unresolved instead of substituting a stopped mutation. A committed failure already owns terminal truth; otherwise existing lease-expiry reconciliation appends one nonretryable `lease_expired` terminal at the reserved sequence. This preserves recovery without replaying the execution.

Representative widened event; it is still a `v1` additive-compatible event:

```json
{
  "schema_version": "v1",
  "kind": "execution.event",
  "producer": "foundry",
  "service_identity": "foundry-service",
  "event_id": "00000000-0000-4000-8000-000000000514",
  "event_dedupe_key": "attempt-id:514",
  "scope": { "kind": "workspace", "cloud_workspace_id": "00000000-0000-4000-8000-000000000001" },
  "cloud": {
    "ally_id": "00000000-0000-4000-8000-000000000002",
    "conversation_id": "00000000-0000-4000-8000-000000000003",
    "message_id": "00000000-0000-4000-8000-000000000004",
    "cloud_binding_id": "00000000-0000-4000-8000-000000000005"
  },
  "conversation_turn_ordinal": 2,
  "foundry": {
    "execution_id": "00000000-0000-4000-8000-000000000006",
    "attempt_id": "00000000-0000-4000-8000-000000000007",
    "generation": 1,
    "attempt_sequence": 514
  },
  "event_type": "message.delta",
  "payload": { "kind": "assistant_delta", "text": "bounded fragment" },
  "issued_at": "2026-09-05T00:00:00Z",
  "fingerprint": "canonical-json-sha256:v1:<64 lowercase hex characters>"
}
```

Cloud must deploy before Foundry can emit sequence 514 or higher because an older Cloud validator rejects those otherwise-valid events.

### Durable assistant reply contract

Add `chat.AssistantReply`, a one-to-one child of the triggering sent user `Message`. Do not insert assistant rows into the existing `Message.sequence`; that integer remains the unique, continuous ordering and dispatch ordinal used by current clients and Foundry.

| Field | Shape and invariant |
| --- | --- |
| `id` | UUID primary key. |
| `message` | Unique FK/one-to-one to a `sender=user`, `origin=send` message; delete cascades with the conversation. |
| `content` | UTF-8 text accumulated exactly once from contiguous `message.delta` events while under the hard limit, independent of whether an `Activity` is visible; maximum 4 MiB, matching the stricter upstream stream byte bound. A delta that would cross the limit is suppressed from the stored text while its receipt and later terminal remain durable. |
| `has_full_prefix` | `true` immediately when Cloud creates the row while accepting attempt sequence 1; `false` for a rollout-era suffix first observed later. Clients consume live or terminal reply content only when true. |
| `is_truncated` | `false` by default; `true` after a delta would exceed the 4 MiB hard limit. The retained prefix is valid but incomplete, so clients show an explicit truncation notice. This flag never enables fresh retry. |
| timestamps | Created on attempt sequence 1, including `execution.accepted`, and updated in the same projection transaction as its receipt/message status. |

Do not copy lifecycle, attempt identity, generation, or checkpoint fields onto `AssistantReply`. Its parent `Message.status` owns lifecycle and the immutable contiguous `FoundryEventReceipt` rows own attempt identity and sequence coverage. The API derives reply status from the parent message.

`ConversationResponse` gains an optional/additive `assistant_replies` array for replies whose source messages are in that message page. Cloud prefetches them with the selected page to avoid per-message queries. Existing response fields and the legacy activity endpoint stay unchanged.

Integration refinement D13: select message/reply character lengths before loading their bodies. A conversation page targets at most 1 MiB aggregate characters and always admits one source message with its reply, even when that one reply exceeds the target; its cursor keeps all earlier turns reachable. The shared controlled JSON transport uses a bounded 48 MiB default only for authenticated chat reads (Ally conversation, conversation-by-ID, and conversation activities), sufficient for the existing 200-activity snapshot plus one 4 MiB reply including JSON escaping. Other endpoints retain the 256 KiB default, and every explicit caller limit remains authoritative. Activity replay aggregate accounting charges activity payloads without charging the same durable reply again for each activity, and a snapshot exposes `assistant_reply` only when it belongs to the latest message; a queued newer turn must not retransmit the preceding turn's reply. Both clients accumulate replies across the current and older message pages. Verify these boundaries through the actual controlled transport with a reply larger than 256 KiB and through cursor paging with multiple large replies.

```json
{
  "id": "00000000-0000-4000-8000-000000000008",
  "source_message_id": "00000000-0000-4000-8000-000000000004",
  "conversation_turn_ordinal": 2,
  "content": "The complete durable reply.",
  "status": "completed",
  "has_full_prefix": true,
  "is_truncated": false,
  "created_at": "2026-09-05T00:00:01Z",
  "updated_at": "2026-09-05T00:00:02Z"
}
```

New clients default a missing `assistant_replies` field to `[]` for an older Cloud. When `has_full_prefix` is true, clients use current durable content during live work and at terminal, and ignore the activity-built copy for the same `source_message_id`. When `is_truncated` is true, clients render the retained prefix with an explicit truncation notice rather than presenting it as complete. A rollout-era suffix with `has_full_prefix: false` never replaces legacy activity text. The activity snapshot response also carries the current reply for its active/latest turn as an optional additive `assistant_reply` field, so polling remains useful after visible activity limits suppress more fragments. This preserves old clients while moving durable truth to Cloud.

Visible `Activity` rows remain a bounded transport/presentation tail. Reaching per-message or conversation text/count limits suppresses another activity but never suppresses the durable reply, event receipt, or activity-snapshot state derived from the latest `Message`. Do not prune existing activities in this remediation: legacy replies still depend on origin replay, and pruning needs no new retention/checkpoint protocol once live and terminal durable reply snapshots carry new-turn content.

During rolling deployment, if Cloud already has a receipt for sequence 1 but no `AssistantReply`, a later event may create a suffix with `has_full_prefix: false`, but it never replaces the legacy activity fallback and no activity for that turn is removed. New attempts beginning after migration create their row at sequence 1 with `has_full_prefix: true`, making their accumulated content usable both live and at terminal.

`Message` gains `retry_allowed: bool = false`. Cloud sets it true only from an authenticated terminal `execution.failed` event whose validated payload explicitly says `retryable: true`; timing, missing callbacks, `stopped`, lease expiry, response loss, reply truncation, and reconciliation uncertainty leave it false. This is server-owned policy and is never inferred by a client.

### Retry and recovery contract

- `POST .../messages/{message_id}/retry` creates a fresh message only when the original user turn is terminal and `retry_allowed` is true. Repeating the retry request with its key remains idempotent.
- `queued`, `in_progress`, accepted-without-callback, and `reconciliation_needed` states return `retryable: false`. Their existing Cloud dispatch reconciler repeats only the original immutable command/fingerprint, and Foundry never opens a second Hermes stream for a dispatched execution.
- Remove the 120-second stale/outbox bypass from `_prior_turn_is_open`; an ambiguous earlier turn continues to block a newer dispatch until the original reaches a reconciled terminal state.
- Web response loss repeats the original send endpoint with the same content and idempotency key; that is acceptance reconciliation, not the fresh-retry endpoint.
- Foundry delivery failures keep the existing `pending`, `delivering`, `delivered`, and `exhausted` states. Add only a bounded `repair_cycle` claim-generation fence. A retryable final failure or expired eighth claim rebuilds/verifies the envelope from `ExecutionEvent`, advances the cycle, resets that cycle's attempt counter, returns the row to `pending`, and schedules it after 300 seconds. Permit three automatic repair cycles of eight attempts; then park it as `exhausted`. Claims and marks carry both `(repair_cycle, attempt)` so a response from an older cycle cannot mutate current state. Permanent validated contract/auth rejections go directly to `exhausted`.
- Add a dry-run-by-default management command that selects explicit delivery/event IDs, validates the retained event and fingerprint, and requires `--confirm` to re-drive an exhausted row. A confirmed re-drive advances `repair_cycle` before resetting attempts, so repeated/stale workers remain fenced; it cannot create a new `ExecutionEvent` or execution.
- Derive `repair_pending` and `recovered` publisher counts from pending/delivered rows with a nonzero repair cycle rather than persisting more states. Output only safe codes/counts and no payload, tenant content, URL, or secret.

## Implementation phases and lane ownership

### Phase 1 — Cloud shared contract and durable replies (orchestrator, Cloud worktree)

1. Add `AssistantReply(content, has_full_prefix, is_truncated)`, `Message.retry_allowed`, and their additive migration in `backend/chat/models.py` and `backend/chat/migrations/`; preserve existing `Message.sequence` rows and leave legacy turns without fabricated full-prefix replies.
2. Update `backend/activities/services/projection.py` so receipt capacity uses the shared `100001` bound, sequence 1 creates the locked reply with full-prefix coverage, and every contiguous delta updates it before success. When a delta would cross the 4 MiB hard limit, retain the valid bounded prefix, set `is_truncated`, and still commit that receipt, subsequent receipts, and terminal message state. A rollout suffix is marked incomplete; activities remain intact and their ordinary 64 KiB presentation bounds cannot gate reply/receipt/message-state updates.
3. Widen `FoundryIdentity.attempt_sequence` in `backend/allies/gateways/contracts.py`; keep event payload and tenant/correlation validation unchanged.
4. Add `AssistantReplyResponse`, additive `assistant_replies` paging, and the optional latest-message reply on activity snapshots in the chat/activity schemas and controllers; derive status from `Message`, select scalar lengths before loading a bounded page, prefetch only selected replies, and keep the field absent/empty for legacy rows or when the latest message has no reply.
5. Restrict `is_message_retryable`/`retry_message` to terminal rows with `retry_allowed`, set only by authenticated `execution.failed.retryable: true`, and remove the stale 120-second prior-turn bypass. Retain original-identity background reconciliation for every uncertain outcome.
6. Change `ALLIES_ACTIVITY_SSE_ENABLED` to default `False` in `backend/config/settings.py` and inventories/docs that state the default. Keep the existing endpoint, auth checks, flag override, cursor replay, heartbeat, and fallback behavior.

**Exit:** A 762-event attempt projects a durable reply prefix and terminal; ordinary activity/text caps cannot turn missing text into a receipt gap, and a hard-limit crossing is explicitly marked with receipts and terminal state preserved; accepted/no-callback/unknown-terminal work cannot create a fresh retry; an explicit safe terminal can; default settings do not reserve request threads for SSE.

### Phase 2 — Long event and delivery recovery (Foundry worker, Foundry worktree)

1. Centralize `MAX_RUNTIME_EVENT_SEQUENCE = 100000` and `MAX_TERMINAL_SEQUENCE = 100001` across `backend/runtime/contracts.py`, event/attempt validation, runtime client validation, and model constraints. Preserve existing `v1` shapes and public provider-neutral language.
2. In `runtime/allies_runtime/foundry.py`, check the ordinary budget before forwarding an event. At exhaustion, close the producer and report one nonretryable `event_budget_exhausted` terminal at sequence `100001`; response-loss handling continues to resend only identical request bytes.
3. Add only a bounded `repair_cycle` field to `ExecutionEventDelivery` through an additive migration. Update `backend/runtime/services/event_delivery.py` so claims/marks are fenced by cycle and attempt, an expired final claim advances into another pending cycle, and source-event reconstruction verifies the canonical fingerprint.
4. Add the idempotent dry-run/`--confirm` re-drive command under `backend/runtime/management/commands/`; expose safe aggregate repair evidence through the existing publisher command.

**Exit:** sequences 514 and 762 succeed; event 100000 can be followed by terminal 100001; a Cloud outage beyond one eight-attempt cycle heals without re-executing the turn; a crash after claim eight is reclaimed; permanent exhaustion can be re-driven from the original event.

### Phase 3 — Web recoverable sends and durable reply consumption (web worker, web worktree)

1. Regenerate/pin the additive Cloud OpenAPI snapshot and extend `packages/cloud-client/src/mappers/allies.ts` so missing reply fields are compatible, replies map by `sourceMessageId`, only `hasFullPrefix` rows replace projected text, `isTruncated` rows render their bounded prefix with an explicit notice, and replies accumulate across older-page loads. Give only authenticated chat reads the 48 MiB controlled-response default; preserve explicit caller limits and the 256 KiB default elsewhere.
2. Route ordinary immediate sends through the existing account/workspace/conversation-scoped bounded local queue in `apps/web/app/home/home-workspace.tsx`: persist content plus idempotency key before network I/O, remove it only after confirmed/replayed acceptance, and resume the same head after reload.
3. Present unknown response loss as “We couldn't confirm your message” and keep the saved command; do not manufacture a new key or call the fresh retry endpoint.
4. Reconcile live and terminal full-prefix reply snapshots from conversation/activity reads, render one reply per source message, and retain current chat-frame geometry.
5. Add `web/feat/chat-frames` to the `pull_request.branches` filters in `.github/workflows/ci.yml` and `.github/workflows/secret-scan.yml` so this stacked PR receives ordinary exact-head checks. Leave Enkii's existing `web/**` coverage and Railway preview behavior unchanged.

**Exit:** reload after request/response loss resends the same key and merges one accepted user message; terminal reply content renders once; existing queue/account isolation and storage-event behavior still pass.

### Phase 4 — Mobile history, liveness, drafts, and exactly-once rendering (mobile worker, mobile worktree)

1. Start from `mobile/consolidated-app` commit `bc67ce0`, preserving its onboarding glass input tint and restored rendering. Apply the same additive Cloud-client reply mapping, including an explicit notice for `isTruncated` bounded prefixes, controlled-response limits, and paged-reply accumulation as web; merge messages and matching full-prefix durable replies by stable IDs.
2. On every cold conversation open, including when no turn is active, hydrate signed activity replay pages from origin/high-water so legacy replies beyond the 200-row tail remain available. Handle cursor expiry with one origin rehydrate and surface a real retention gap instead of looping; no new pruning in this remediation means an existing legacy prefix remains replayable.
3. Replace the two-minute stop with focused, state-bound polling: keep the current cadence initially, back off to a capped interval after two minutes, stop when terminal/unfocused, and retain the explicit manual refresh on request/replay failure.
4. Keep the composer editable while an execution is active (`pendingMessage`/send persistence still fences submission as appropriate), so typed draft text survives updates and navigation state.
5. Reconcile the optional live reply snapshot on each poll, then track the source-message IDs actually rendered inline; only render the remaining IDs afterward. Do not infer this from persisted assistant IDs.
6. Add `mobile/consolidated-app` to the `pull_request.branches` filters in `.github/workflows/ci.yml` and `.github/workflows/secret-scan.yml` so this stacked PR receives ordinary exact-head checks. Leave Enkii's existing `mobile/**` coverage and Railway preview behavior unchanged.

**Exit:** a cold open with more than 200 activities shows prior terminal replies; an active turn beyond two minutes continues updating; its draft remains editable; one greeting, user message, and projected/durable reply render exactly once.

### Phase 5 — Cross-repository proof and PR readiness (orchestrator)

1. Run the focused and complete checks below in each worktree. Use generic fixtures in Foundry and keep all evidence free of private paths, hosts, payload content, and credentials.
2. Run a local contract proof with Cloud first, then Foundry: at least 762 ordered events, disconnect/replay, duplicate callbacks, callback outage beyond one delivery cycle, and recovery without a second execution.
3. Verify Cloud's generated schema and each Interface pinned snapshot agree. Confirm an older-client fixture can ignore `assistant_replies` and still consume legacy activities. Exercise the real controlled JSON transport above and below 256 KiB, prove explicit lower caller limits still reject oversized chat responses, and page through multiple replies larger than the 1 MiB character target without loss.
4. Open the four PRs against their recorded bases and verify the added exact base-branch filters run both Interface CI and secret scanning at each stacked PR head SHA; record `source_sha` where emitted and do not treat a missing check as success.

## Acceptance criteria

1. A01: a new attempt creates its full-prefix reply at sequence 1; content exceeding the ordinary visible 64 KiB activity text budget remains available live and terminal, while content crossing the separate 4 MiB durable hard limit keeps its valid prefix, exposes `is_truncated`, and retains receipts/terminal state; a rollout-era suffix is never presented as complete history.
2. A02: the same `v1` fixture accepts nonterminal sequence 514 and completes beyond 513; the ordinary maximum has one valid reserved terminal; values above 100001 fail validation.
3. A03: accepted/stale/reconciliation-needed/unknown-terminal turns keep `retry_allowed=false` and never expose or accept a fresh retry, while authenticated `execution.failed.retryable: true` permits idempotent retry lineage.
4. A04: retryable exhaustion and an expired final claim enter repair, deliver after Cloud returns, and preserve one execution/event identity; confirmed permanent failures are operator re-drivable from `ExecutionEvent`.
5. A05: mobile cold-origin hydration runs for active and inactive conversations, succeeds when the bounded tail starts above sequence one, and preserves legacy replies across multiple message/reply pages.
6. A06: focused mobile updates continue with capped backoff beyond two minutes, stop on terminal/unfocus, and never lock draft editing solely because an Ally is working.
7. A07: each activity or durable reply is selected once in inline/fallback rendering.
8. A08: a default Cloud process opens no SSE requests; opt-in SSE retains authorization/replay tests and web falls back to polling when unavailable.
9. A09: web persistence precedes the first send; reload, another tab, timeout, and replay all reuse the original key and clear it only after confirmed acceptance.
10. Cross-cutting: negative tenant/account tests, out-of-order/conflicting duplicate tests, migration-mid-attempt coverage, migrations, schema generation, existing chat frames and mobile onboarding glass, CI, secret scanning, and repository full checks pass at the recorded PR head SHAs.
11. D13 integration: Cloud selects a page from scalar message/reply lengths with a 1 MiB character target while always returning one turn; cursors retain every earlier large reply; activity snapshots never attach an older reply to a newer latest message; authenticated chat reads accept valid responses above 256 KiB under their 48 MiB default, explicit caller limits still win, other endpoints remain capped at 256 KiB, replay accounting excludes repeated durable-reply bytes, and web/mobile retain replies from every loaded page.

## Validation plan

### Cloud

- Focused: `make test APP="activities/tests/test_cld005.py chat/tests/test_services.py chat/tests/test_api.py chat/tests/test_models.py chat/tests/test_dispatch.py config/tests/test_settings.py"`.
- Add cases for reply creation/full-prefix coverage at sequence 1, 64 KiB activity suppression with complete live/terminal reply snapshots, a pre-migration mid-attempt suffix with `has_full_prefix=false`, 762 ordered deltas plus terminal, duplicate/conflicting envelopes, event-cap validation from `attempt_sequence` rather than receipt totals, the 4 MiB durable hard limit with `is_truncated` API/snapshot propagation and later-turn reachability, unchanged legacy activity replay, snapshot reply ownership by the latest message, scalar-first 1 MiB page selection, cursor reachability across multiple replies above that target, paged reply query count, `retry_allowed` true versus false, stale-prior-turn blocking, cross-tenant reads, and SSE default/explicit opt-in.
- Full: `make check`, `make lint`, `make test`; with PostgreSQL, `cd backend && uv run pytest -m postgresql` and migrate forward/check on a fresh database.

### Foundry

- Focused backend: `make test APP="runtime/tests/test_cld005_contract.py runtime/tests/test_fnd005_backend.py runtime/tests/test_migrations.py"`.
- Focused runtime: add long-event/budget-terminal cases beside the existing runtime Foundry/Hermes tests, then run `make runtime-test`.
- Add cases for 514/762/100000/100001 boundaries, 100002 rejection, identical replay, event-budget terminal, stale `(cycle, attempt)` marks, exhausted retry cycle, expired eighth claim, permanent rejection, operator cycle advance/dry-run/confirm, source fingerprint mismatch, and recovery without a new execution.
- Full: set `DJANGO_DEBUG=true`, then run `make check`, `make lint`, and `make validate`; apply and verify migrations as CI does.

### Web Interface

- Focused: `bun run test:run apps/web/app/home/home-workspace.test.tsx packages/cloud-client/test/client.test.ts packages/cloud-client/test/mappers.test.ts packages/cloud-client/test/activity-projection.test.ts`.
- Cover persist-before-send, storage failure, timeout then reload, same-key replay, cross-tab convergence, account/workspace scoping, durable-reply precedence, paged-reply retention, an older Cloud response without the new array, a valid chat response above 256 KiB through the controlled transport, an explicit lower chat limit, and a non-chat response that still uses the 256 KiB default.
- Full: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint:web`, `bun run build:web`, and `bun run test:chat-frames`.

### Mobile Interface

- Focused: `bun run test:run apps/mobile/src/features/conversation/conversation-state.test.ts apps/mobile/src/lib/pending-command-store.test.ts packages/cloud-client/test/activity-projection.test.ts packages/cloud-client/test/mappers.test.ts` plus a screen-selection test for `apps/mobile/src/app/allies/[allyId]/index.tsx` extracted into the existing conversation helper boundary if needed.
- Cover active and inactive >200-activity cold starts, multi-page legacy replay and durable-reply retention, cursor expiry/gap, live full-prefix reply snapshots after activity suppression, no preceding reply on a queued latest turn, shared controlled-transport limits, backoff beyond two minutes, focus/terminal cancellation, draft edits during work, rollout suffix fallback, exactly-once inline/fallback selection, and preservation of the `bc67ce0` onboarding glass behavior.
- Full: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint:mobile`, and `bun run bundle:mobile`.

### Integrated/manual evidence

- Record execution ID/event count only: send a deterministic long reply producing at least 762 events, interrupt the client, reconnect, and compare the durable Cloud reply with the concatenated Foundry deltas.
- Hold Cloud callback delivery unavailable beyond the first eight-attempt cycle, restore it, and prove all events become delivered contiguously while the Foundry execution count stays one.
- Cold-open web and mobile after completion, confirm one reply, then keep a mobile turn active beyond two minutes and verify continuing updates and editable draft text.

## Rollout and rollback

1. Merge/deploy Cloud contract support first with SSE default off. Run migrations before serving the new code; the new table is additive and legacy rows/clients continue to use activities.
2. Merge/deploy Foundry second. Its additive delivery migration precedes the publisher/runtime rollout. Confirm repair counts and long-sequence callbacks in staging before allowing normal traffic.
3. Merge/deploy web and mobile after their pinned schema matches Cloud. Each stacked Interface PR adds its exact base to CI and secret-scan pull-request filters and must show those checks at its current head.
4. Update the Nabu conversation/streaming spec, decision log, and audit disposition with accepted behavior and proof after implementation; do not rewrite unrelated delivery gaps.

Rollback Interface independently because Cloud fields are additive and legacy activities remain. To roll back Foundry after it may have emitted sequences above 513, first stop new execution claims, return Foundry/runtime to the old producer, and let the widened Cloud consumer drain or repair every high-sequence event. Keep Cloud widened until that drain is proven; rolling Cloud back first can strand valid events. A Cloud application rollback may leave the additive reply table in place, but pause new execution while old code is active because it will not maintain durable replies. Re-enable SSE only through the existing environment flag after capacity/reconnect evidence; disabling it is the immediate fallback.

## Risks and open decisions

| Risk/open item | Mitigation or decision |
| --- | --- |
| Widened `v1` sequences are not accepted by old Cloud. | Cloud-first rollout and widened-consumer drain rule are mandatory. |
| A reply can cross its 4 MiB durable hard limit while ordered events are still arriving. | Retain the valid prefix, set `is_truncated`, suppress later text appends, and continue committing receipts and terminal state. Clients show an explicit truncation notice; truncation never enables fresh retry. Keep each incoming event bounded by the 16 KiB contract and do not add an unbounded buffer or a new service. |
| A rollout starts while an attempt already has receipts but no reply row. | Mark any later-created row `has_full_prefix=false`, retain its legacy activities, and never present the suffix as complete history. |
| Automatic delivery repair could retry a permanent error. | Only retry transient/unavailable outcomes automatically, use three eight-attempt pending cycles separated by 300 seconds, fence marks by cycle and attempt, and park validated auth/contract conflicts for explicit re-drive after correction. |
| Legacy conversations have no durable reply row. | Do not fabricate or backfill missing content, do not prune their activities, and run origin replay even when no turn is active. |
| A broad response-limit increase could allow oversized payloads on unrelated endpoints. | Keep 48 MiB scoped to the three authenticated chat-read routes, preserve explicit caller limits, retain 256 KiB elsewhere, and exercise each branch through the controlled transport. |
| The accepted Nabu stale-retry statement conflicts with A03. | User authorization to fix all audit findings selects terminal-only fresh retry; record the superseding decision after validated implementation. |
