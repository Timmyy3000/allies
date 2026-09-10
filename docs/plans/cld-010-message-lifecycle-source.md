Source: projects/allies/engineering/specs/cld-004-conversation-and-message-lifecycle.md
Revision: bc5f755e4153313f58a95d6ee4f897278cd7191d0854a233fa14971b94872669

---
id: CLD-004
title: CLD-004 â€” Conversation and message lifecycle
summary: Approved specification for one durable customer-facing conversation per Ally and exactly-once acceptance of user message intent.
status: Implemented
type: feature-spec
ticket: projects/allies/delivery/tickets/cloud/CLD-004.md
owner: Timi
affected_systems: [allies-cloud, allies-interface]
depends_on: [CLD-003]
tags: [allies, cloud, interface, conversation, messaging, CLD-004]
authors: [Allies Engineering]
source: CLD-004 product-owner grooming, accepted Allies product requirements, conversation-and-streaming contract, CLD-001 domain contract, and approved CLD-003 handoff
updated: 2026-08-25
---

# CLD-004 â€” Conversation and message lifecycle

## Specification metadata

- **Status:** Implemented and staged
- **Product-owner confirmation:** Approved by Timi on 2026-08-24
- **Ticket:** [[projects/allies/delivery/tickets/cloud/CLD-004|CLD-004 delivery ticket]]
- **Owner:** Timi
- **Affected repositories or systems:** Allies Cloud and Allies Interface
- **Related decisions and sources:** [[projects/allies/product/allies-first-product-requirements|Allies first product requirements]], [[projects/allies/product/allies-product-design-spec|Allies product design specification]], [[projects/allies/engineering/specs/conversation-and-streaming|Conversation and Streaming]], CLD-001 Cloud domain map and cross-repository contract, [[projects/allies/engineering/specs/cld-003-create-and-manage-real-ally|CLD-003 Create a real Ally through official onboarding]]
- **Last updated:** 2026-08-25

## Problem

The product can now create a durable Workspace-owned Ally and preserve the official onboarding greeting and user reply, but it does not yet own the ongoing customer-facing conversation or message lifecycle. Without that Cloud-owned boundary, Interface cannot safely send, reload, or distinguish messages, and a disconnect or repeated request could lose or duplicate user intent.

The product needs one continuous conversation per Ally whose visible history survives client and runtime changes. Cloud must accept each user message intent exactly once, preserve its truthful state, and expose only Allies product identifiers and language.

## Intended outcome

A signed-in internal tester can open an Ally, see the same continuing conversation created during onboarding, send a text message once, and immediately receive a durable message representation. Repeating the same send returns the original result. Leaving, refreshing, or disconnecting does not remove or duplicate the accepted message.

Cloud owns the conversation and visible message truth. This specification stops at durable message acceptance and the stable Interface contract; Foundry execution projection and replay/event delivery remain owned by CLD-005 and CLD-006.

## Deliverables

| Deliverable | Type | Owning repository or system | Completion evidence |
| --- | --- | --- | --- |
| One durable customer-facing conversation associated with each Ally | Data contract | allies-cloud | External proof shows repeated creation or retrieval resolves to the same conversation and no Ally has two initial conversations. |
| Durable ordered user and assistant message records with customer-facing lifecycle states | Data contract | allies-cloud | Contract evidence and externally observable tests cover creation, ordering, state truth, and invalid transitions. |
| Workspace-authorized conversation retrieval and message-send capabilities | API | allies-cloud | Published contract and API evidence cover success, duplicate send, invalid input, and privacy-safe foreign-resource denial. |
| Caller idempotency and duplicate-response contract | Cross-team contract | allies-cloud + allies-interface | The same key and same content returns the original message result; conflicting reuse is rejected without changing the original. |
| Official-onboarding exchange integration | Conversation integration | allies-cloud | The CLD-003 greeting and reply appear once, in order, at the start of the real conversation. |
| Interface-facing request, response, lifecycle, and error vocabulary | Documentation and schema | allies-cloud + allies-interface | Interface can consume the published contract without Foundry, Hermes, Fly, or runtime identifiers. |
| Focused migration, authorization, concurrency, and API evidence | Tests and documentation | allies-cloud | Completion evidence proves the acceptance criteria and the reviewed contract is published. |

Exact execution commands, event projection, streaming replay, stop, execution retry, and UI composition are not deliverables of CLD-004.

## User journey

1. An authenticated person opens a Workspace-owned Ally.
2. Cloud returns the Ally's one continuing conversation, including the official onboarding greeting and reply when present.
3. The person composes a message. An unsent draft remains client/session state.
4. On send, Interface supplies a fresh caller retry identity with the message content.
5. Cloud validates current Workspace authority and message input, durably accepts one user message, and returns its stable product representation.
6. The accepted message remains visible as durable work even when the Ally is waking, later work is queued, the browser disconnects, or downstream execution is not yet accepted.
7. Repeating the same send identity and content returns the original message result without another visible message or work intent.
8. Reusing the identity with different content is rejected without changing the original message.
9. Returning later shows the same ordered conversation and truthful current message states.
10. Another Workspace cannot read, send to, or infer the existence of the Ally, conversation, or messages.

## In scope

- Exactly one initial customer-facing conversation for each Ally.
- Idempotent creation or retrieval of that conversation.
- Importing the current official-onboarding greeting and user reply exactly once and in order.
- Durable ordered user and assistant message product records.
- Text-only message acceptance with bounded validation.
- Caller-provided send idempotency and deterministic duplicate responses.
- A stable distinction between successful send acceptance and the message's single lifecycle status.
- The single message lifecycle vocabulary is `queued`, `in_progress`, `completed`, `failed`, and `stopped`; a successfully accepted send starts at `queued`.
- Current Workspace authorization and privacy-safe denial on every read and mutation.
- An Interface-facing contract using only Allies product language and identifiers.

## Out of scope

- More than one conversation for the same Ally.
- Direct Interface access to Foundry, Hermes, Fly, runtime services, or private identifiers.
- Foundry execution dispatch, execution attempts, activity projection, or runtime event handling; CLD-005 owns these.
- Cursor replay, streaming delivery, reconnect continuation, stop, execution retry, and terminal recovery; CLD-006 owns these.
- Responsibilities, routines, approvals, scheduled work, or cross-Ally activity feeds.
- Editing messages, deleting claimed/executed messages, and deleting conversations. The accepted 2026-09-06 extension below permits only removal of unclaimed queued sends.
- Final visual design, composer layout, activity presentation, animations, notifications, or platform-specific behavior.
- Retrospective import of public waitlist conversations.
- Image and file attachment upload and message semantics; attachment support is deferred to Beta.

## Product constraints

- Every Ally has one default continuing customer-facing conversation in the initial product; conversations are first-class records so future group or multi-agent conversations can have their own conversation IDs.
- The official-onboarding greeting and reply are the beginning of that same conversation, not a separate preview thread.
- An unsent draft is client/session state; a sent and accepted message is durable Cloud-owned work.
- An accepted user message remains visible through waking, queuing, downstream failure, refresh, and browser disconnect.
- Conversation history is complete and durable; Alpha loads the newest bounded page first and fetches older messages on demand with an opaque continuation cursor.
- One Ally processes only one conversation turn at a time; additional valid sends are accepted and queued in order behind the active turn, subject to a bounded pending queue. A full queue rejects only the new send without changing accepted messages.
- Different Allies keep separate identity, conversation, and message history.
- User messages, Ally responses, and activity remain distinguishable product concepts.
- Interface may map the internal status vocabulary (`queued`, `in_progress`, `completed`, `failed`, and `stopped`) to appropriate user-facing copy.
- Alpha message sends are text-only; image and file messages are a Beta capability and must not be implied as supported by this contract.
- Product-visible states and errors must be truthful and must not mention infrastructure.

## Technical constraints

- Cloud owns customer-facing conversation identity, message identity, ordering, content, visible lifecycle state, Workspace authorization, and send idempotency.
- Interface talks only to Cloud and treats Cloud responses as product truth.
- Cloud identifiers are the only public authority. Foundry, Hermes, Fly, profile, runtime, lease, Machine, credential, and address details remain private.
- The same send key and same normalized request must return the original accepted result. The same key with different content is a conflict.
- Durable message acceptance must commit before success is returned.
- Browser connection lifetime must not control message durability or downstream work lifetime.
- Current Workspace authority is checked on every protected operation, including duplicate lookups.
- Ordering must remain deterministic when sends are concurrent or repeated.
- CLD-004 must leave a stable execution handoff seam without defining CLD-005's gateway or projection implementation.
- Existing clients remain compatible through an additive, versioned contract.

## Cross-team API and data contract

- **Conversation lookup:** current authenticated Workspace authority plus an Allies Ally identifier returns the Ally's default customer-facing conversation and its ordered visible messages.
- **Message addressing:** after lookup, Interface reads and sends by conversation ID. A future conversation may have its own conversation ID and participant set without changing message semantics.
- **History retrieval:** conversation reads return a bounded page and an opaque cursor for older messages; clients may continue until the beginning of the conversation.
- **Send input:** current authenticated Workspace authority, Allies conversation or Ally identity, caller-generated send key, text content, and any version required by the published API contract.
- **Accepted send result:** stable conversation identifier, stable user-message identifier, normalized customer-visible content, deterministic conversation order, message state `queued`, and the current execution projection when one exists.
- **Duplicate invariant:** the same caller key and same accepted content returns the original message and current projection rather than creating another message.
- **Conflict invariant:** the same caller key with different content returns a stable conflict and does not change or duplicate the original.
- **Conversation invariant:** one Ally resolves to at most one initial customer-facing conversation; concurrent first access cannot create two.
- **Onboarding invariant:** the retained greeting precedes the retained reply, both appear at most once, and subsequent messages follow them.
- **Turn invariant:** one Ally may have only one actively executing turn; later accepted messages wait in deterministic order, and queue saturation rejects only the new unaccepted send.
- **Authorization failure:** unauthorized and foreign-resource access uses privacy-safe denial that does not reveal resource existence.
- **Validation failure:** invalid or oversized input is rejected before durable acceptance and does not consume the send key as a successful intent.
- Exact route names, fields, serialization, pagination, and internal state-machine design belong to the implementation plan and published API schema unless the grill makes them cross-team requirements.

## Privacy, retention, and abuse requirements

- Every conversation and message read or mutation requires current Workspace authorization.
- Another Workspace must not infer whether an Ally, conversation, message, or send key exists.
- Customer-visible responses, logs, traces, metrics, and evidence must not expose credentials, private URLs, runtime addresses, Hermes session or profile keys, Foundry-private identifiers, raw tool payloads, or provider exceptions.
- Message content is customer data and may flow only across the authorized Allies product/runtime boundary required to perform the request.
- Message input, history retrieval, send rate, concurrent pending work, and response sizes require bounded protections appropriate for internal alpha.
- CLD-004 does not introduce implicit deletion or retention changes; later deletion work must define removal of conversation history explicitly.
- Abuse and cost controls must reject excess new work without corrupting already accepted messages.
- If a database transaction fails after rate-limit admission, Cloud clears the deterministic request marker but retains that attempted aggregate quota until the normal window expires. This fail-closed rule must never decrement a shared bucket that may have been recreated.

## Dependencies

- **Implemented and approved dependency:** CLD-003 supplies the Workspace-owned Ally plus the ordered official-onboarding greeting and reply handoff.
- **Implemented dependency:** AUTH-001 supplies signed-in identity, secure sessions, personal Workspace, membership, and current capability checks.
- **Accepted contract dependency:** CLD-001 defines Cloud ownership, public/private identifier boundaries, message-to-execution seams, and idempotency expectations.
- **Accepted system contract:** Conversation and Streaming defines one conversation per Ally, Cloud ownership, same-Ally turn serialization, and disconnect durability.
- **Design dependency for release:** DSN-002 owns the alpha conversation and activity experience, including attachment entry and visible states.
- **Downstream dependency:** CLD-005 owns Foundry gateway execution acceptance and projection.
- **Downstream dependency:** CLD-006 owns cursor replay, reconnect continuation, stop, execution retry, and failure recovery.
- **Downstream consumer:** INT-101 consumes the published Cloud message contract together with CLD-006's replay/event contract.

## Open questions

None; the remaining page-size and cursor encoding details belong in the implementation plan and published API schema.

## Acceptance criteria

1. Opening a Workspace-owned Ally returns the same customer-facing conversation on repeated and concurrent access.
2. No Ally can have two initial customer-facing conversations.
3. The official-onboarding greeting and reply appear once, in order, at the start of the real conversation.
4. Sending valid text durably creates one user message and returns its stable customer-facing representation.
5. The accepted message remains visible after browser disconnect, refresh, downstream delay, and downstream failure.
6. Repeating the same send key and content returns the original message and current execution projection without creating a duplicate.
7. Reusing a send key with different content returns a stable conflict without changing the original message.
8. Invalid or rejected input creates no message and no accepted work intent.
9. Concurrent sends for one Ally have deterministic visible order and cannot create duplicate order positions.
10. A later accepted turn waits while the same Ally is active and is not lost, merged, or started concurrently.
11. User messages and assistant messages expose truthful, distinguishable customer-facing states.
12. Every protected read and mutation rechecks current Workspace authority.
13. Foreign-resource denial does not reveal whether the Ally, conversation, message, or send key exists.
14. Public API responses and diagnostic evidence contain no private Foundry, Hermes, Fly, runtime, session, profile, credential, or address data.
15. The published Interface contract distinguishes durable message acceptance from execution acceptance without requiring Interface to call Foundry.
16. The final reviewed API/data contract records the decided attachment, addressing, single-status, queue-bound, and history-window behavior.
17. Migration, service/API, authorization, idempotency, and concurrency evidence is recorded before the ticket can complete.

## Engineer handoff

After claiming the ticket, the engineer and their agent must:

1. inspect the current repository and applicable repository instructions;
2. reconcile the specification with implemented behavior and accepted Nabu decisions;
3. create a reviewable implementation plan covering approach, files, sequencing, migrations, tests, risks, and verification;
4. obtain the required plan review or approval before implementation;
5. update the specification only if implementation reveals a genuine contract or product decision change.


## Implementation evidence

- **Status:** Complete as of 2026-08-25.
- **Pull request:** [allies-cloud PR #15](https://github.com/Timmyy3000/allies-cloud/pull/15) merged into `dev` on 2026-08-25 (merge commit `db3f590e18b1949d9dac1c952b1688f762617fe9`).
- **Reviewed implementation plan:** `docs/plans/cld-004-conversation-and-message-lifecycle.md` with synchronized HTML presentation.
- **Local validation:** Django checks and migration consistency passed; Ruff lint/format passed; full backend suite passed with 280 tests and 13 PostgreSQL-only tests skipped locally.
- **Review evidence:** simplicity review completed; independent P0-P2 review findings were fixed; final re-review reported no findings; Enkii policy review P2 on rate-limit event volume was fixed by burst-limiting aggregate emissions and removing duplicate controller logging.
- **Concurrency evidence:** PostgreSQL-only tests are included for identical-key one-row/one-increment replay and distinct-key sequence allocation; CI passed them.\n- **Staging evidence:** Railway cloud/staging Backend, Worker, Beat, Postgres, and Redis deployments are terminal `SUCCESS`; Backend deployment `32c0bf68-9dea-4834-af2d-16e0d56eb2df` serves `/api/v1/health` with HTTP 200 and `{\"state\":\"healthy\"}`.

## Onboarding reply as first accepted turn

**Status:** Accepted by product-owner direction and locally validated on 2026-08-28.

The official-onboarding reply occupies conversation sequence 2 and becomes the first accepted user turn once Ally provisioning succeeds. Cloud changes that existing row from completed onboarding history to a queued send with stable idempotency and content fingerprints, then creates exactly one Foundry dispatch outbox. Repeating activation returns the same message and outbox. The Interface therefore shows one copy of the user's reply followed by the Ally's real response; it must not leave the reply looking sent while no execution exists.


## Cross-device queue and unclaimed removal â€” 6 September 2026

**Status:** Accepted contract; implemented in Cloud and Interface Forest branches `ft/cross-device-message-queue` against `dev`. Interface PR #30 was externally merged on 6 September 2026; Cloud PR #29 is ready to merge at `67017da350db86f4aa5a1e6e1bc847b8ee55b5ce`, with all current-head checks and Enkii lanes clear. Earlier progress entries below describe their historical heads. No Cloud merge or agent deployment.

Both actual web and mobile clients submit durably to Cloud while an earlier turn wakes or runs. Cloud claims the earliest live send under the conversation lock; acceptance by Foundry does not release the next turn. A valid terminal projection, or a failure proven before any Foundry call, releases the slot. An uncertain post-call outcome remains claimed until terminal evidence or operator repair. Previously attempted legacy sends are conservatively nondeletable.

Messages add `queue_state: claimed | unclaimed | null` and `deleted_at`; conversation reads add the complete bounded live `queue` independently of the selected history page. Activity snapshots identify their claimed head with `active_message_id`. The accepted head remains visually queued until progress for that exact message; later tails never inherit its progress. `awaiting_action` retains the execution slot and may resume.

An authorized idempotent DELETE at `/api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}` removes only an unclaimed queued send. Delete and claim use the same lock order, so claim wins with `409 message_not_deletable` or deletion wins before dispatch. A successful deletion retains ID, sequence, send-key digest and content fingerprint, blanks content and command bytes, sets `deleted_at`, and uses existing `status: stopped`. Repeated deletion and exact send-key replay return the redacted tombstone; differing content remains a conflict. Tenant-crossing requests retain indistinguishable 404 denial. Native send/retry/delete require live native-kind bearer sessions; browser mutations keep trusted-origin and CSRF checks.

Clients hide tombstones and reconcile them across retained history pages, stale acceptance responses, and refreshes. Web retains scoped unknown intents with stable keys; account-ambiguous legacy storage is preserved without automatic attribution. Mobile retains its single encrypted unknown command and safely replays it after reopening. Neither client gates sends on wake hints or current execution. This extension does not add Push, editing, reordering, priority, steering, or active cancellation.

Rollback disables new tail admission and client controls first, retaining serial claim/release and tombstone handling until all existing queues and uncertain claims drain. Restoring the older early-dispatch behavior while tails remain is prohibited.

Cloud implementation review: [PR #29](https://github.com/alliesai/allies-cloud/pull/29) targets `dev` at `f77ec8e301f3c5d60b595c8dd40da8169d07514b`. Local full suite: 503 passed, 21 skipped; independent correctness review found no remaining P0â€“P2 issues and separate simplicity review was Lean. Hosted Django, PostgreSQL concurrency, and Gitleaks checks passed for that head. Enkii review and paired Interface delivery remain pending; this is not merge or deployment evidence.

Paired client implementation: [Interface PR #30](https://github.com/alliesai/allies-interface/pull/30), head `4f6c8c7c6e361d1e4dbd3854309e091ebf36771d`, implements both the actual web HomeWorkspace and Expo conversation route. Full Interface suite: 579 passed across 85 files (75 HomeWorkspace and 6 native route tests). Contract/type checks, web production build, mobile iOS export, and lint passed; web lint retains 33 existing warnings. Hosted browser regressions and Enkii remain pending. Separate final correctness review found no remaining P0â€“P2 issues; simplicity was Lean. Recovery regressions cover delayed reads after acceptance, remote tombstone eviction, and forward head advancement after missed terminal events. Five-minute monitoring owns scoped review/CI fixes; neither PR is merged or deployed.

Enkii follow-up on 6 September: the original Cloud PostgreSQL job passed but deselected the chat race module because its `postgresql` marker was missing. The follow-up adds the marker and requires fresh hosted execution of all four chat races; the earlier green job alone is not queue-lock evidence. Onboarding activation must transfer a proven unstarted later claim back to the promoted sequence-2 reply, including an attempt-zero binding wait. Migration terminalization requires positive pre-call evidence plus no receipt digest or event, not merely missing receipts. Ambiguous legacy failed heads retain claims and block rollout pending reconciliation. Quiesce all old dispatch workers/schedulers and settle in-flight calls before migration; keep them stopped until the entire fleet uses the new claimed-only dispatcher, then require the unresolved-legacy-failed-head check to be zero before resuming dispatch/admission and clients. Follow-up implementation and review are in progress; neither PR is merged.

Follow-up completed at Cloud head `f7c393675b23a61200c87f3be9b4b03a46e64856`: onboarding and conservative migration fixes independently reviewed with no remaining P0â€“P2 issues; simplicity Lean. Full local backend suite 515 passed, 21 skipped. [Hosted PostgreSQL job](https://github.com/alliesai/allies-cloud/actions/runs/34051064532/job/101534664886) explicitly executed all four chat race tests: 30 selected tests passed overall. Django and Gitleaks also passed on this head. This supersedes the insufficient earlier PostgreSQL evidence. Current-head Enkii re-review is pending; Interface remains fully checked and reviewed at `4f6c8c7c6e361d1e4dbd3854309e091ebf36771d`. No merge or manual deployment.


Latest review status, 6 September: Interface PR #30 was merged by Timmyy3000 at 18:53:53 UTC, merge commit `f5a9d6310e2eeda13909120f2e458a53b8191b94`, after all client checks and three Enkii review lanes cleared. Cloud `5e31a6597c35beb61340f2603b6cb915e4295115` fixes deleted-tail activity fallback with 29 passing activity regressions. Hosted checks pass, including all four chat PostgreSQL races (30 selected tests passed in job 101537153387). Enkii security and policy clear this head, but general review identifies another migration liveness issue: outbox-less live legacy sends must not become non-dispatchable claimed heads or be omitted from rollout preflight. A conservative FIFO-preserving correction is in progress; Cloud is not merge-ready. Both Forest worktrees are retained and five-minute scoped monitoring continues.


Orphan correction pushed at `67017da350db86f4aa5a1e6e1bc847b8ee55b5ce`: migration claims the exact earliest live row only when its outbox exists, never skipping an orphan to claim a later pending turn. Rollout preflight now requires zero live missing commands, unresolved FAILED claims and later claims with earlier unclaimed predecessors. Preserve ambiguous attempted claims; repair original identities without fabricating fresh execution. Regression coverage verifies real acceptance recovery and detects incorrect claim order even after a missing outbox is repaired. Full backend 516 passed, 21 skipped; focused service/dispatch tests 49 passed; Django, migration drift and Ruff pass. Independent correctness clear, separate simplicity Lean. Fresh hosted CI and Enkii remain required; Cloud is still unmerged.


Final delivery evidence, 6 September 2026: Cloud PR #29 head `67017da350db86f4aa5a1e6e1bc847b8ee55b5ce` is open, mergeable into `dev`, and ready for owner merge. Hosted Django, Gitleaks, PostgreSQL and Enkii checks passed. PostgreSQL job 101543825639 explicitly executed all four chat race tests; all 30 selected tests passed. Enkii general review 5126392926, security 5126392930 and policy 5126392932 have no remaining findings and verify earlier corrections. Interface PR #30 is already externally merged. Both clean Forest worktrees remain owned by the delivery task; monitoring stops at readiness. Cloud has not been merged or deployed by the agent. Production rollout still requires the documented legacy-worker quiescence, migration and zero-count preflight before resuming the new dispatcher and admission.
