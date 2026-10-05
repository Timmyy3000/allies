# Web Ally Home Workspace Plan

## Feature Overview

- **Problem:** Google sign-in now establishes a Cloud session, but the web client still lands on the debugging-oriented `/account` route. There is no signed-in product surface that lists a person's real Allies or opens the continuing conversation for a selected Ally.
- **Target users:** Signed-in Allies web users, beginning with internal MVP testers whose personal Workspace may have zero or a small number of Allies.
- **Source docs and evidence:** `docs/plans/web-ally-home-workspace-brief.md`; the supplied split-chat, Substack Chat, and WhatsApp Web visual references; Nabu `projects/allies/product/allies-prd-response.md`, `projects/allies/engineering/specs/cld-004-conversation-and-message-lifecycle.md`, `projects/allies/engineering/specs/cld-005-foundry-gateway-and-activity-projection.md`, and `projects/allies/engineering/specs/waitlist/INT-009-frontend-handoff.md`; the Interface onboarding, session, Query, avatar, and generated-client code; and the Cloud Ally, chat, activity, authorization, schema, and tests listed under validation basis.
- **Success outcome:** `/home` becomes the default signed-in destination and an immediately recognizable messaging client. It shows a real Workspace-scoped Ally conversation list and one selected Ally's continuous thread, or a truthful first-Ally empty state inside the same messaging shell. Ally creation happens in the thread pane itself at `/home/new` on desktop and mobile; after the first reply creates the durable Ally, the route is replaced with `/home/{allyId}` and the real conversation continues in place.

### Messaging-First Product Frame

Allies is fundamentally a messaging platform in which the contacts on the other side are highly capable AI agents. Each Ally behaves like a contact, and each Ally owns one continuous thread. `/home` is therefore a conversation client first, not a dashboard, agent control centre, settings switcher, or card gallery.

AI capability should become legible inside that familiar messaging model. An Ally's character, name, and Job establish identity; provisioning establishes whether the contact is ready; presence and activity explain current work; result messages and agent states belong in the thread as Cloud exposes them. This slice renders the current provisioning and activity contracts honestly. It does not invent a separate Overview panel or pretend that out-of-scope Results controls already exist.

### Product and Visual Decision

The page is a **quiet companion messaging client**, not a dashboard. The structural references contribute only the proven conversation-list and selected-thread relationship. Allies owns the appearance:

- warm white canvas, `#121212` text, `#f3f3f3` supporting surfaces, and `#ff5800` primary action;
- Open Runde typography already loaded by the web root;
- real `AllyAvatar` shapes and colours as the main identity cue;
- rounded rows and composer geometry that echo onboarding without turning every region into a card;
- generous negative space, particularly in the empty state and message column;
- restrained entry and selection motion with complete reduced-motion behavior.

Do not add gradients, glass, shadows used as decoration, metric cards, card grids, fake status data, a generic AI sparkle aesthetic, or search. Assistant replies remain open text on the canvas, like the onboarding greeting. User messages use one quiet rounded surface. This makes Home clearly messaging-first while retaining a specific Allies character.

### MVP Polling Exception

- **Owner:** Web Interface.

For the local MVP demonstration, the implementation intentionally polls activity every 500 ms for up to 240 foreground attempts (two minutes). This is an explicit exception to the baseline 1.5-second/80-poll cadence documented below; the shorter interval is temporary demo ergonomics, remains mechanically bounded, and must not be described as streaming. Production tuning remains deferred until the durable activity contract is available.

## User Stories

1. As a signed-in user with no Allies, I want `/home` to tell me plainly that my Ally space is empty and let me meet my first Ally, so I can enter the existing onboarding flow.
2. As a signed-in user with Allies, I want to see each real Ally's avatar, name, and Job and open one continuing conversation, so I can move between distinct working relationships.
3. As a user creating an Ally, I want the Home thread to ask the shaping questions and become my Ally's real conversation, so creation feels like the beginning of the relationship rather than a separate modal workflow.
4. As a user returning to a conversation, I want persisted onboarding and later messages to retain their order and older pages to load without duplication.
5. As a user sending a message, I want to see whether Cloud accepted it, is still working, completed, or failed, so the Interface never presents generated text before Cloud supplies it.
6. As a user whose session or network fails, I want an explicit recovery path that preserves my unsent draft, so retrying does not lose or duplicate my intent.
7. As an operator, I want the new Ally collection endpoint and every existing conversation read to remain Workspace-authorized and bounded, so one account cannot observe another account's Allies or work.

## Scope

### In Scope

- Add `GET /api/v1/workspaces/{workspace_id}/allies` to Cloud with current-membership authorization, deterministic newest-created ordering, provisioning data, one efficient relation-loaded query, and negative tenant tests.
- Publish the endpoint in Cloud OpenAPI, then sync the complete current Ally, onboarding, conversation, message, and activity contract into `@allies/cloud-client`.
- Add validated cloud-client view models and methods for onboarding attempts, Ally creation/list/retrieval, conversation reads, idempotent text sends, and activity snapshots.
- Make `/home` the successful sign-in target and session-protected signed-in shell.
- Add URL-addressable Ally selection with `/home/[allyId]` while preserving `/home` as the empty/list entry route.
- Build the desktop two-pane shell, mobile list and focused-chat layouts, empty state, real Ally rows, selected conversation, older-history control, composer, and explicit request states.
- Reuse `AllyAvatar`, the established `Meet your first ally` action, onboarding configuration screens, and preview inside the Home thread pane rather than recreating them or opening a modal.
- Add an authenticated onboarding completion adapter that starts an official onboarding attempt and creates the real Ally after the reply. Keep the public waitlist path and its two-request behavior unchanged.
- Refresh the Ally collection after creation and select the returned Ally.
- Use current activity snapshots for bounded polling only while the latest turn is active. Assemble `assistant_delta` text in activity sequence and stop on a terminal state, route change, unmount, or polling budget.
- Add focused unit, integration, responsive browser, accessibility, and contract checks in both repositories.

### Out of Scope

- Search, consumer-social or global-navigation clutter, chat filters, group categories, folders, pinned chats, calls, reactions, read receipts, forwarding, fake unread counts, fabricated timestamps or last-message previews, and recency sorting that Cloud does not expose.
- The global Overview attention surface, approvals, Results, Routines, Responsibilities, Access, settings, voice, attachments, stop, retry-execution, or repair actions.
- SSE, WebSocket, replay cursors, reconnect continuation, background sync, or claims of live streaming. CLD-006 owns those contracts.
- Editing or deleting Allies, multi-conversation Allies, renaming Jobs, or changing appearance from Home.
- A dark product theme, a copy of any supplied reference, a new design system, or a component library dependency.
- Redesigning `/account`; it remains available as a debugging/account surface.
- A database migration. The collection endpoint reads existing indexed Ally rows.

### Dependencies and Assumptions

- Cloud remains the only product source of truth. Interface calls only versioned Cloud APIs through `@allies/cloud-client`.
- CLD-003, CLD-004, and CLD-005 remain the implemented baseline. CLD-006 is not pulled into this work.
- Each Ally has one default continuous conversation. Runtime assistant text is currently stored as bounded activity deltas rather than durable assistant `Message` rows.
- The first release expects a small number of Allies per personal Workspace. The collection response is intentionally unpaginated for this slice. The query is one ordered, relation-loaded read; pagination is added only when real account counts require it. This is the only accepted unbounded-row assumption in the plan.
- The activity API returns only the latest 200 visible activities. The client can preserve deltas it has already observed during one mounted turn, but it cannot promise full replay after a long disconnect or an activity window overflow. The UI must state that it is showing the latest available response and must not call polling streaming or reconnect. CLD-006 remains the durable fix.
- Exact pixel tuning occurs through implementation screenshots at the existing `1024px` desktop breakpoint. The geometry below is a reviewable layout contract, not permission to invent a parallel token system.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects and errors |
| --- | --- | --- | --- | --- | --- |
| Cloud `backend/allies/services/creation.py` | `list_allies` | `def list_allies(*, user: User, workspace_id: UUID | str) -> tuple[Ally, ...]` | Canonical Workspace UUID; current `PROFILE_READ` capability | Newest-created Allies with binding and provisioning operation already selected | Read-only; `WorkspaceAccessDenied` or invalid Workspace is mapped to privacy-safe `404`. |
| Cloud `backend/allies/api/controllers.py` | `AllyController.list` | `def list(self, request, workspace_id) -> HttpResponse` | Valid session and Workspace scope | `SuccessResponse[AllyListResponse]` | `401 session_invalid`, `404 ally_unavailable`, `500 internal_error`. |
| Client `packages/cloud-client/src/client.ts` | `listAllies` | `listAllies(workspaceId: string, signal?: AbortSignal): Promise<AllyViewModel[]>` | Non-empty Workspace ID | Validated camel-case array | Normalized Cloud error or `contract` on malformed success. |
| Client `packages/cloud-client/src/client.ts` | `beginOnboarding` | `beginOnboarding(input: AllySeedInput, signal?: AbortSignal): Promise<OnboardingAttemptViewModel>` | Name 1..80, Job 1..200, personality 1..4000, appearance fields | Opaque attempt token and greeting | Origin/CSRF-bound browser request; no session requirement. |
| Client `packages/cloud-client/src/client.ts` | `createAlly` | `createAlly(workspaceId: string, input: CreateAllyInput, idempotencyKey: string, signal?: AbortSignal): Promise<AllyViewModel>` | Stable key 16..128; exact onboarding token, seed, and reply | `201` bound or `202` provisioning Ally, normalized to one view model | CSRF mutation; exact-key replay returns the same Ally, conflicting reuse is `409`. |
| Client `packages/cloud-client/src/client.ts` | `getConversationByAlly` | `getConversationByAlly(workspaceId: string, allyId: string, options?: { limit?: number; cursor?: string; signal?: AbortSignal }): Promise<ConversationViewModel>` | Limit 1..100, opaque cursor | Ordered page plus `nextCursor` | Privacy-safe `404`; invalid cursor `422`. |
| Client `packages/cloud-client/src/client.ts` | `sendMessage` | `sendMessage(workspaceId: string, conversationId: string, content: string, idempotencyKey: string, signal?: AbortSignal): Promise<MessageAcceptanceViewModel>` | Text 1..16,000 after Cloud normalization; key 16..128 | Durable user message, conversation ID, replay flag | CSRF mutation; `409` key conflict, `429` queue/rate limit, retry same intent with same key. |
| Client `packages/cloud-client/src/client.ts` | `getActivitySnapshot` | `getActivitySnapshot(workspaceId: string, conversationId: string, limit?: number, signal?: AbortSignal): Promise<ActivitySnapshotViewModel>` | Limit 1..200 | Ordered latest activity window, overall latest-turn state, last contiguous attempt sequence | Read-only; privacy-safe `404`, invalid limit `422`. |
| Interface `apps/web/lib/allies/home-queries.ts` | `alliesQueryOptions` | `alliesQueryOptions(client, runCloudOperation, workspaceId)` | Signed-in Workspace | Query option keyed by Workspace | Uses normal Cloud retry policy; cancelled on unmount/session invalidation. |
| Interface `apps/web/lib/allies/home-queries.ts` | `conversationInfiniteQueryOptions` | `conversationInfiniteQueryOptions(client, runCloudOperation, workspaceId, allyId)` | Authorized Ally selection | Deduplicated, sequence-ordered pages | Fetches older pages only from explicit user action. |
| Interface `apps/web/lib/allies/activity-assembly.ts` | `reduceActivitySnapshot` | `reduceActivitySnapshot(previous, snapshot, turnSequence): AssistantTurnProjection` | Product activity sequence, unique activity IDs, matching `conversation_turn_ordinal` | Accumulated available text and truthful state | Pure function; ignores duplicates and never invents missing fragments. |
| Interface `apps/web/lib/onboarding/authenticated-flow.tsx` | `AuthenticatedAllyFlowProvider` | `AuthenticatedAllyFlowProvider({ workspaceId, onCreated, children })` | Signed-in Workspace and current onboarding configuration | Common preview-flow context | Owns attempt token, stable create key, retry, creation result, and cache invalidation. |

### API and Transport Contracts

| Consumer | Method and path | Authentication and authorization | Request schema | Success response schema | Errors and retry semantics |
| --- | --- | --- | --- | --- | --- |
| Web | `GET /api/v1/workspaces/{workspace_id}/allies` | Browser session; current Workspace `PROFILE_READ` | No body | `SuccessResponse<AllyListResponse>` | `401`, privacy-safe `404`, `500`. Query retry follows existing network/timeout/server policy only. |
| Web | `POST /api/v1/onboarding/attempts` | Trusted origin and browser CSRF binding | `AllySeedInput` | `SuccessResponse<OnboardingAttemptResponse>` | `403`, `422`, `429`, `503`; retry preserves the exact configuration intent. |
| Web | `POST /api/v1/workspaces/{workspace_id}/allies` | Browser session, trusted origin, CSRF, current Workspace write capability | `CreateAllyRequest` plus `Idempotency-Key` | `201` or `202 SuccessResponse<AllyResponse>` | Exact retry uses same key; content change gets a new key; `409` conflict is not auto-retried. |
| Web | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation` | Browser session and Workspace read capability | Query `limit`, optional `cursor` | `SuccessResponse<ConversationResponse>` | `404` hides foreign resources; `422` invalid cursor; transient reads use existing query retry. |
| Web | `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages` | Browser session, trusted origin, CSRF, Workspace write capability | `{ content }` plus `Idempotency-Key` | `200` replay or `201 SuccessResponse<MessageAcceptanceResponse>` | Same key/same text returns original; changed text with same key conflicts; no mutation auto-retry with a new key. |
| Web | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities?limit=200` | Browser session and Workspace read capability | No body | `SuccessResponse<ActivitySnapshotResponse>` | Poll only while active, abort on navigation, and stop at budget or terminal state. |

Representative new collection response:

```json
{
  "status": "success",
  "message": "Allies loaded",
  "data": {
    "allies": [
      {
        "id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d76",
        "binding_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d77",
        "operation_id": "018f77d8-6e61-7ca0-8c36-1ba4f1fd9d78",
        "name": "Mira",
        "job": "Study partner",
        "personality": "Calm, curious, and specific.",
        "appearance": { "catalog_version": "v1", "key": "ghosty:ff5800" },
        "provisioning_state": "bound",
        "retryable": false
      }
    ]
  }
}
```

The list endpoint has no request body, filter, search, or cursor in this slice. It remains additive to API `0.1.0`; existing consumers are unchanged.

### Schema and Data Shapes

| Schema or model | Location | Fields | Required, nullable, defaults | Validation and invariants | Compatibility and migration |
| --- | --- | --- | --- | --- | --- |
| `AllyListResponse` | Cloud `backend/allies/api/schemas.py` | `allies: list[AllyResponse]` | Required, empty list allowed | Every row belongs to the requested authorized Workspace; newest `created_at`, then UUID descending | Additive schema, no migration. |
| `AllyViewModel` | `packages/cloud-client/src/client.ts` or focused mapper | IDs, name, Job, personality, appearance, provisioning state, retryable | All current Cloud fields required | Zod validates UUID-like non-empty identifiers, bounded text, appearance strings, and known provisioning states | New exported type. Unknown malformed successes fail as `contract`; unsupported appearance catalog renders a neutral unavailable asset, not a fake identity. |
| `ConversationViewModel` | cloud-client | `id`, `allyId`, `messages`, `nextCursor` | `nextCursor` nullable | Message sender and lifecycle use closed current vocabularies; messages sorted by sequence | Maps current published contract. |
| `ActivitySnapshotViewModel` | cloud-client | conversation ID, activities, state, last contiguous sequence | Activity text may be empty | Sequences positive, latest window at most 200, state from Cloud | Maps current published contract; not a replay stream. |
| `AssistantTurnProjection` | Interface local view model | turn sequence, seen activity IDs, available text, lifecycle, last activity sequence | Text starts empty | Append only unseen `assistant_delta` records in ascending product sequence; terminal state is monotonic | Ephemeral, removed on private-query/session cleanup. |
| Query cache | TanStack Query | account, Allies, conversation pages, activity snapshot | Workspace and resource IDs in every private key | Cloud response is source of truth; no fake seed rows | No persisted browser cache. Logout removes `account` and Workspace product keys. |

### Frontend Interaction Shapes (if applicable)

| UI entry point | Hook or action | State transitions | API mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| `/home` | `restore()` then Allies query | `restoring -> signed-in -> loading -> empty | ready | error` | account Workspace ID to collection GET | Signed out redirects; unavailable session retries; empty shows onboarding action. |
| Ally row | `router.push('/home/' + ally.id)` | list selection to selected conversation | selected ID to conversation-by-Ally GET | Foreign/missing ID shows privacy-safe unavailable state. |
| Load older | `fetchNextPage()` | `idle -> fetching -> merged | error` | opaque `nextCursor` to conversation GET | Keeps current history visible; retry only the older-page request. |
| Composer submit | `sendDraft()` | `editing -> submitting -> accepted -> working -> terminal` or `editing -> error` | draft and stable key to message POST; accepted message inserted from response | Draft is preserved until acceptance. Queue/rate errors are explicit. |
| Activity poll | query `refetchInterval` and reducer | `queued/in_progress -> completed | failed | stopped | awaiting_action | snapshot activities to turn projection | Poll every 1.5 seconds, foreground only, maximum 80 polls per submitted turn; stop and offer a manual status refresh after budget. |
| Create Ally | link to `/home/new` | empty or selected thread to provisional creation thread to `/home/{allyId}` | onboarding attempt then idempotent create Ally | Error keeps configuration/reply and exposes retry; successful creation invalidates the roster and replaces the provisional URL. |

## Phases

### Phase 1 - Publish the Missing Cloud Collection Contract

- **Goal:** Make the authorized Workspace's Allies discoverable without fabricating IDs or issuing per-Ally requests.
- **Work items:**
  - Add `AllyListResponse`, `_response` reuse, `list_allies`, and `AllyController.list`.
  - Use `require_workspace_capability(...PROFILE_READ)` before querying.
  - Query with `select_related('binding', 'binding__provisioning_operation')` and `order_by('-created_at', '-id')` so serialization remains one query and ordering is deterministic.
  - Add empty, multiple-row ordering, missing session, foreign Workspace, inactive membership/capability, and query-count tests.
  - Add a full-envelope OpenAPI example and contract assertion for the new path.
- **Impacted systems:** `allies-cloud/backend/allies/api/{controllers,schemas}.py`, `allies-cloud/backend/allies/services/creation.py`, `allies-cloud/backend/allies/tests/test_api.py`, `allies-cloud/backend/config/openapi.py`, and focused API contract tests.
- **Exit criteria:** The endpoint returns only authorized Allies in deterministic order; empty returns `allies: []`; query count is constant; no migration exists; Cloud checks and focused tests pass.

### Phase 2 - Sync and Expose the Complete Browser Client Contract

- **Goal:** Keep Interface on the generated, validated public Cloud boundary.
- **Work items:**
  - Deploy or otherwise publish the updated Cloud schema to the canonical staging endpoint before committing the pinned Interface snapshot. Use a local schema only for temporary development validation.
  - Run `bun run cloud:fetch` and `bun run cloud:generate`; verify the generated paths include list/create/retrieve Ally, onboarding attempt, both conversation reads, send, and activities.
  - Add focused Zod schemas, mappers, exported view models, and the client methods defined above.
  - Extend fixtures and tests for every successful operation, malformed success, declared error, cancellation, CSRF mutation preparation, and stable idempotency headers.
- **Impacted systems:** `packages/cloud-client/openapi/*`, `src/generated/openapi.ts`, `src/client.ts`, optional focused `src/mappers/allies.ts`, `src/index.ts`, and client tests.
- **Exit criteria:** `cloud:check` is clean, no app bypasses the client, and typed fixtures cover every consumed route.

### Phase 3 - Separate Reusable Onboarding Presentation from Completion Mode

- **Goal:** Reuse the accepted onboarding design for real signed-in Ally creation while preserving public waitlist behavior.
- **Work items:**
  - Extract the `MeetAllyButton` and preview presentation boundaries from the large onboarding module without changing their rendered public appearance.
  - Define one small preview-flow contract implemented by the current `WaitlistFlowProvider` and the new authenticated provider. Do not create a generic workflow framework.
  - Authenticated `saveConfiguration` calls `/onboarding/attempts`; authenticated reply submission calls create Ally with one stable key per unchanged intent.
  - Add `returnTo` and `onCreated` handling. Desktop closes and selects the Ally; mobile replaces the completed onboarding route with `/home/{id}`.
  - Preserve waitlist email modal, analytics privacy exclusions, accepted public copy, and exact two-request waitlist behavior.
- **Impacted systems:** onboarding components/store, `apps/web/lib/waitlist/flow.tsx`, new focused authenticated onboarding flow files, route page, and tests.
- **Exit criteria:** Public waitlist regression tests pass; authenticated desktop and mobile creation use the same visible screens; retries do not duplicate Allies; a created Ally's onboarding greeting and reply are immediately available from its conversation.

### Phase 4 - Build the Session-Protected Messaging Shell and Responsive Ally Navigation

- **Goal:** Ship the empty and selected layouts with real account data and the established Allies design language.
- **Work items:**
  - Add `/home` and `/home/[allyId]` route wrappers around one `HomeWorkspace` client boundary.
  - Add query options keyed by Workspace and resource IDs, session redirect behavior, logout/private-cache cleanup, and deterministic default selection. Desktop `/home` replaces to the first newest Ally when one exists; mobile `/home` stays on the list until the user chooses.
  - Implement the compact Ally conversation list, continuous rows, minimal thread header, empty state inside the messaging shell, loading/error/provisioning surfaces, and quiet `/account` link.
  - Host the existing shaping and preview screens in the `/home/new` thread pane on desktop and mobile, with normal mobile list-to-thread navigation.
  - Use CSS modules and existing globals/tokens; do not add a UI dependency.
- **Impacted systems:** new `apps/web/app/home/**`, `apps/web/lib/allies/**`, extracted shared onboarding action, session private-query cleanup, auth/sign-in defaults, and CSS modules.
- **Exit criteria:** Acceptance criteria 1 through 5 and 9 pass at desktop and mobile widths, with no fake rows or search.

### Phase 5 - Add Continuous History, Text Send, and Bounded Activity Projection

- **Goal:** Make the selected Ally useful with the current honest Cloud contract.
- **Work items:**
  - Load the latest 50 conversation messages, merge older pages by ID and sequence, and render the official onboarding exchange once.
  - Keep one local draft per selected conversation for the mounted session. Create the send key at submit and retain it across exact retries.
  - Insert only the accepted Cloud message into the query cache. Never insert a speculative assistant message.
  - Poll the 200-row activity snapshot every 1.5 seconds only for `queued` or `in_progress`, only while the document is visible, with an 80-poll ceiling. Stop for terminal, awaiting action, navigation, unmount, or abort.
  - Group activities by `conversation_turn_ordinal`, deduplicate by activity ID/sequence, and append `assistant_delta` text in order. Present lifecycle records with approved plain product copy.
  - On terminal state, refetch conversation and activity once. Preserve partial available text on failure or stop.
- **Impacted systems:** Home conversation components, cloud query helpers, activity reducer and tests, composer tests, and responsive browser coverage.
- **Exit criteria:** Acceptance criteria 6 through 8 pass within the current snapshot contract; polling is visibly and mechanically bounded; no Interface code claims SSE, replay, or reconnect.

### Phase 6 - Integration, Visual Tuning, and Release Evidence

- **Goal:** Prove the full story across the published contract and the local staging-like stack.
- **Work items:**
  - Run focused tests after each phase, then complete Cloud and Interface validation.
  - Exercise empty account, successful in-thread creation on desktop and mobile, reload/deep link, older history, exact send retry, terminal activity, session expiry, provisioning failure, and reduced motion.
  - Capture desktop and mobile screenshots. Confirm that messaging structure is immediately legible against the supplied Substack Chat and WhatsApp Web patterns, while typography, spacing, button geometry, avatars, and motion remain grounded in the existing Allies onboarding implementation.
  - Verify no new analytics captures message, Job, personality, greeting, activity, or Ally name. Home analytics are out of scope.
- **Impacted systems:** both repositories, test fixtures, and review evidence only.
- **Exit criteria:** Complete commands pass; visual acceptance checks pass; the contract source is canonical staging; no unrelated dirty-worktree files are included.

## Acceptance Criteria

1. A signed-out visit to `/home` redirects to `/sign-in?returnTo=%2Fhome`; successful Google sign-in returns to `/home`.
2. A signed-in empty Workspace renders no fabricated Ally rows and shows `Meet your first ally`.
3. The creation action opens `/home/new` as a provisional conversation in the Home thread pane on desktop and as the focused thread route on mobile; no modal or drawer is used.
4. Completing signed-in onboarding creates the Ally through Cloud, refreshes the list, and opens its persisted onboarding conversation at `/home/{allyId}`.
5. A Workspace with Allies renders only authorized real Allies in newest-created deterministic order. The selected Ally survives reload and browser navigation through the URL.
6. Conversation history renders the persisted onboarding exchange and later user messages, groups the latest available assistant activity with its turn, loads older message pages without duplicates, and preserves sequence order.
7. Sending text uses one stable idempotency key per unchanged intent, clears the draft only after Cloud acceptance, distinguishes queued/working/completed/awaiting-action/failed/stopped states, and never claims an assistant response before a Cloud delta supplies it.
8. While a turn is active, foreground polling assembles unseen `assistant_delta` activity in sequence and stops on terminal state, awaiting action, route change, unmount, hidden document, or the 80-poll budget. The UI calls this status checking, not streaming.
9. Pending, retryable, failed, incompatible, and repair-required Ally provisioning states remain visible and truthful; chat input is disabled whenever Cloud cannot safely accept work.
10. Desktop and mobile layouts are keyboard usable, focus-visible, safe-area aware, responsive, and reduced-motion safe. Normal route navigation preserves expected Back behavior.
11. Cloud tenant-isolation and query-count tests, generated OpenAPI/client checks, focused Interface tests, type checks, lint, and production build pass.
12. Public waitlist behavior, its accepted copy, email completion, privacy exclusions, and desktop-drawer/mobile-route pattern do not regress.
13. Without reading copy, desktop is immediately recognizable as a compact conversation list beside one selected thread, and mobile is recognizable as list then focused thread. Open Runde, orange actions, Ally characters, warm whitespace, rounded geometry, and restrained motion make the result unmistakably Allies rather than a generic messaging clone or AI dashboard.

## Backend Considerations (if applicable)

### Query Optimization Plan

- **Hotspot:** The new Workspace Ally collection. It must not issue one query per binding or provisioning operation.
- **Query shape:** Authorize first. Then filter by the resolved Workspace and use `select_related('binding', 'binding__provisioning_operation')` with `order_by('-created_at', '-id')`. The existing `(workspace, created_at)` index supports the scope/order scan; PostgreSQL can scan it backward. UUID resolves ties.
- **Expected query-count change:** One authorization path plus one Ally collection query. Serialization adds zero queries. Record an `assertNumQueries` guard around the service/controller path using representative multiple rows.
- **Measurement:** Focused query-count test and `EXPLAIN` only if the test database or review shows an unexpected scan. No new index or migration is planned.

### N+1 Prevention

- `_response` dereferences `ally.binding.provisioning_operation`; both relations must be selected in the collection query.
- The list endpoint must not call `retrieve_ally` per row and must not repair or load conversations.
- Conversation data remains one request for the selected Ally only. The conversation list does not fetch one conversation per Ally.

### Detailed Unit Test Cases

- Empty authorized Workspace returns `200` with `{"allies": []}`.
- Multiple Allies return newest `created_at` first and UUID descending for a timestamp tie.
- Bound, pending, retryable, failed, incompatible, and repair-required rows serialize the current public fields correctly.
- Missing/invalid session returns `401 session_invalid`.
- A user without current membership/capability receives privacy-safe `404 ally_unavailable`; no row existence leaks.
- A valid user cannot list a foreign Workspace, even if an Ally UUID from that Workspace is known.
- Serialization of several Allies has constant query count and no conversation query.
- The generated schema includes the GET path, `AllyListResponse`, complete response envelope, and existing route contracts.
- No migration is generated by `makemigrations --check --dry-run`.

### Migration Plan

Not applicable. The endpoint reads existing models and indexes. If implementation evidence shows a new index is needed, stop and revise the plan rather than adding an unreviewed migration.

### Coverage Target

The repository's CI coverage gate remains `pytest --cov=auths --cov=workspaces --cov-fail-under=90`; the new Ally code also receives explicit risk-based tests even though that gate does not currently set a numeric threshold for `allies` in the command.

## Frontend Considerations (if applicable)

### Data Path

1. `/home` restores the session and obtains the Cloud-owned Workspace ID from the existing account query.
2. `alliesQueryOptions` calls `client.listAllies` through `runCloudOperation`.
3. `/home/[allyId]` resolves selection only against the authorized list, then calls conversation-by-Ally. No Foundry or runtime ID reaches the UI.
4. Older-history requests pass Cloud's opaque cursor and merge validated messages by stable ID and sequence.
5. Submit creates a stable key, calls `sendMessage` with CSRF handling, and inserts only the accepted response.
6. Active-turn status checks call the activity snapshot, reduce unseen deltas, and stop at the stated boundary.
7. Authenticated onboarding begins an attempt, displays Cloud's greeting as untrusted text, submits the reply through create Ally, invalidates the list, and navigates to the returned ID.

### State Management Considerations

- Session remains owned by `SessionProvider`; server truth is cached in TanStack Query; temporary drafts, provisional onboarding state, and delta accumulators stay local to Home.
- Query keys always contain Workspace and resource IDs. Logout removes account and all Workspace product query keys.
- Collection invalidation occurs only after confirmed Ally creation. Conversation insertion occurs only after confirmed message acceptance.
- Exact retry retains the same create/send key. Changing the seed or draft retires the failed key and creates a new one.
- Route changes abort conversation and activity requests. Stale responses cannot overwrite the selected Ally because query keys are resource-specific.
- Polling pauses while `document.visibilityState !== 'visible'`, never runs in the background, and is not persisted across reload.

### Reference-Pattern Comparison

The locally supplied Substack Chat and WhatsApp Web screenshots are structural evidence for a familiar messaging information architecture, not feature inventories or visual skins. Both make the conversation roster and thread relationship understandable before the user reads any label. Allies should borrow that clarity while keeping its own warm typography, orange action, Ally characters, generous whitespace, and restrained motion.

| Reference pattern | Borrow for Allies | Explicitly reject | Allies translation |
| --- | --- | --- | --- |
| Substack Chat | Dense continuous conversation roster, avatar/name/secondary-line hierarchy, strong selected row, minimal selected-thread identity, broad thread canvas, persistent reply area | Global publication navigation, chat search, All/Direct/Unread filters, group mechanics, reactions, reply-count affordances, notifications, overflow actions, and social engagement metadata | One compact Ally contact row per continuous thread; name plus real Job or provisioning state; one selected thread with no social toolbar |
| WhatsApp Web | Clear master-detail desktop shell, compact contact rows, strong left-list/right-thread relationship, calm empty main pane, and list-to-focused-thread mobile mental model | Calls, communities, status surfaces, groups, favourites, read receipts, unread badges, timestamps, last-message previews, forwarding, attachments, and Meta AI shortcuts | `/home` owns the Ally conversation list; `/home/[allyId]` owns the focused thread; the empty main pane invites the user to `Meet your first ally` |
| Existing Allies onboarding | Open Runde hierarchy, orange primary action, Ally character identity, rounded geometry, warm canvas, whitespace, and restrained transitions | A separate dashboard aesthetic, agent metric cards, generic AI sparkle treatment, or card gallery | Familiar messaging structure expressed in unmistakably Allies materials and behavior |

No borrowed feature enters scope without a real Cloud contract and an explicit product decision. In particular, the secondary row line uses only the real Ally Job or current provisioning state in this slice. It never simulates a last message, time, unread count, or presence signal.

### Experience Blueprint

#### Desktop Layout at 1024px and Above

The root is a `100dvh` master-detail messaging shell with no page scroll: the Ally conversation list is always left, and the selected Ally's continuous thread is right. The conversation list owns its own vertical overflow; the thread history owns the other scroll region. The thread header stays minimal, and the composer remains persistently anchored to the bottom.

| Region | Geometry and hierarchy | Content and behavior |
| --- | --- | --- |
| Ally conversation list | `clamp(272px, 24vw, 320px)`, full height, white, one subtle right rule, 16 to 20px horizontal inset | Allies identity, `Your allies` heading, orange create control, compact continuous contact rows, and a quiet `/account` link in the footer. No search or filter bar. |
| Conversation row | 60 to 68px minimum height, 10 to 12px gap, 40 to 44px `AllyAvatar`, restrained shared-list radius | Name on one line; real Job or provisioning state as the secondary line; selected row uses one continuous `#f3f3f3` surface and visible focus ring. No timestamp, unread badge, presence, or last-message fiction. Rows form one roster rather than isolated cards. |
| Thread header | 60 to 64px minimum height with a subtle bottom rule | 36 to 40px avatar, Ally name, Job, and an accessible selected-Ally heading. No search, call, reaction, or overflow toolbar. |
| Thread canvas | Flexible pane with a centered reading column capped near 760px and generous whitespace | Persisted messages and derived assistant activity appear in strict turn order. Assistant text is open on the canvas; user text is right-aligned on `#f3f3f3`. Results and agent states appear in sequence only when Cloud supplies them. |
| Composer | Sticky to the bottom inside the thread pane, same centered width as messages | 52px minimum pill, expanding textarea capped at a practical number of lines, orange circular send action, visible disabled/busy state, preserved draft on failure. |
| Empty account | Empty conversation list remains visible; calm invitation occupies the main thread pane | A decorative, clearly non-account Ally character grouping, one short heading, and the existing orange `Meet your first ally` action. No dashboard cards, fake contact row, or sample thread. |

The empty-state copy is deliberately short: **“Your Allies will live here.”** followed by **“Meet your first ally.”** Once at least one Ally exists, the conversation-list create action is labelled **“Meet another Ally.”**

#### Mobile Layout Below 1024px

- `/home` is the full-height Ally conversation list with the compact Allies header, create control, continuous real rows, and the same empty state. It does not squeeze a permanent second pane beside the list.
- `/home/[allyId]` is the focused Ally thread. Its minimal header includes a labelled back control to `/home`, the Ally identity, and no unsupported actions.
- Selecting a row uses normal Next navigation to `/home/[allyId]`, so browser Back returns to the list and a copied URL restores the same Ally.
- The composer clears only after Cloud accepts the message. Safe-area insets protect the mobile header and composer.
- The create action navigates to `/home/new`, which uses the focused thread region at every viewport. Successful creation replaces it with `/home/{newAllyId}` so Back does not restore a completed provisional flow.

#### In-Thread Ally Creation Contract

| Condition | Entry behavior | Exit and completion behavior |
| --- | --- | --- |
| Desktop, `min-width: 1024px` | Navigate to `/home/new` and render the shaping flow in the existing thread pane while the real Ally roster remains visible. | Successful creation invalidates the Ally list and uses `router.replace('/home/{newAllyId}')`; the persisted first exchange replaces the provisional view. |
| Mobile, below `1024px` | Navigate to `/home/new` as the focused thread route; do not open a sheet or drawer. | Back returns to `/home`. Successful creation uses the same route replacement as desktop. |
| Viewport changes during creation | Keep `/home/new` and the mounted onboarding store; responsive Home composition alone changes which pane is visible. | No modal lifecycle or cross-route handoff is required. |
| Public signed-out onboarding | Keep the current waitlist provider, email modal, analytics, and accepted two-request contract. | No authenticated Ally is created. Existing waitlist tests remain unchanged. |

The Home creation surface uses ordinary page semantics and the existing onboarding Back control. The provisional greeting, reply composer, retry state, avatar movement, and identity header remain inside the thread region.

#### State Matrix

| State | Conversation list | Thread pane | User action |
| --- | --- | --- | --- |
| Session unknown/restoring | Stable shell placeholder | Ally-shaped restrained loader and `Checking your secure session…` | None until resolved. |
| Signed out | No private data | `Opening sign-in…` while replacing the route | Automatic redirect to `/sign-in?returnTo=%2Fhome`. |
| Session unavailable | No stale private rows presented as current | `We couldn't reach your Allies.` | `Try again` calls `restore()`. |
| Allies loading | Fixed row skeletons matching real row geometry | Quiet empty canvas, not fake content | None. |
| Allies error | Conversation-list heading remains | Plain failure copy | Retry the list query. |
| No Allies | Empty list | Branded empty state | Navigate to `/home/new`. |
| Selected Ally loading | Real conversation list and selected row remain | Header and message-line skeletons | Navigation remains available. |
| Invalid or foreign Ally URL | Real authorized conversation list only | `This Ally isn't available.` | Return to `/home`; do not reveal whether a foreign ID exists. |
| Provisioning pending | Row is visible with `Getting ready` | Greeting/history may render, composer disabled | Automatic bounded Ally refetch; create another Ally remains available. |
| Provisioning retryable | Row says `Needs another try` | Existing conversation remains readable, composer disabled | No retry button in this slice; link back to list and truthful explanation. |
| Provisioning failed, incompatible, or repair-required | Row stays visible with an unavailable label | Existing safe history only if Cloud returns it; composer disabled | No fabricated recovery. Explain that this Ally cannot work yet. |
| Message accepted/queued | No conversation-list change | User message appears from Cloud response; Ally shows thinking state | Draft clears only now. |
| Message in progress | No conversation-list change | Accumulated assistant delta and one restrained working label | Poll active snapshot within the defined budget. |
| Awaiting action | No invented approval control | `This Ally needs an action that Home cannot complete yet.` | Polling stops. |
| Completed | No conversation-list change | Final assembled available assistant text; no false delivery copy | Stop polling and refetch conversation/activity once. |
| Failed or stopped | No fake assistant reply | Preserve user message and available partial text; show terminal state | Stop polling. A new execution retry is out of scope. |
| Send error before acceptance | No conversation-list change | Draft remains in composer with inline error | Explicit `Try again` reuses the same idempotency key for the same draft. Editing after failure creates a new key. |

### Component Plan

| Component | Responsibility | Reuse boundary |
| --- | --- | --- |
| `HomeWorkspace` | Session gate, account Workspace, list query, route selection, responsive shell | Uses existing session/query infrastructure. |
| `AllyConversationList` | Messaging roster identity, create entry, compact continuous Ally rows, account link, and list states | No per-row conversation fetching or business rules; never a card gallery or settings switcher. |
| `AllyConversationRow` | Avatar, name, real Job or provisioning secondary line, selected state | Uses `AllyAvatar`; no fake last-message, time, unread, or presence metadata. |
| `HomeEmptyState` | Empty conversation list plus calm thread-pane invitation and existing CTA | Uses extracted `MeetAllyButton`; no dashboard cards. |
| `ConversationPane` | Minimal header, generous thread canvas, status, sticky composer, unavailable/provisioning states | One selected Ally and one continuous thread only. |
| `ConversationHistory` | Ordered message/activity projection, older-page control, scroll anchoring | Pure view over validated models. |
| `MessageComposer` | Draft, stable intent key, submit and retry state | Clears only on acceptance. |
| `HomeAllyCreationPane` | Hosts shaping, generated greeting, reply, retry, and successful handoff at `/home/new` | Reuses common onboarding screens and the authenticated flow provider without a modal. |
| `AuthenticatedAllyFlowProvider` | Official attempt, greeting, reply, create, retry, onCreated | Implements the small common preview-flow contract; does not alter waitlist ownership. |

### Accessibility and Visual Checks

- One `h1` identifies the selected Ally or empty Home state; conversation list and thread use ordered headings.
- Ally conversation rows are links with visible focus, selected semantics, and at least 44px touch targets.
- Dynamic status uses a restrained `aria-live="polite"`; errors use `role="alert"`. Delta text is not re-announced character by character.
- The composer has a visible label, keyboard submit behavior, and error association. Enter sends only under the chosen multiline convention; Shift+Enter always creates a newline.
- Colour never carries provisioning or selection state alone. Copy and shape also identify state.
- The creation route has a labelled Back action, visible focus, and no dialog semantics or inert background.
- `prefers-reduced-motion` removes selection slide, loading wave, and avatar state transition where motion is not essential.
- Visual proof includes 1440x900 and 1024x768 desktop, 390x844 mobile, a narrow 320px check, content zoom at 200%, long names/Jobs, empty state, and all provisioning states.
- At a glance with copy blurred, desktop must still read as a conversation list beside a selected thread, and mobile must read as list then focused thread. Ally characters, Open Runde, the orange create/send actions, warm canvas, whitespace, and motion must keep the result unmistakably Allies rather than a WhatsApp or Substack skin.

## Test Plan

### Unit Tests

- Cloud service/controller tests listed above, plus constant query count.
- cloud-client mapper and operation tests for list, attempt, create, history, send, activity, malformed payloads, response limits, errors, abort, and headers.
- Appearance catalog parser tests for all v1 shapes/colours and an unsupported safe state.
- Activity reducer tests for duplicate snapshots, missing sequences, multiple turns, partial text, terminal monotonicity, window rollover, and route reset.
- Query merge tests for overlapping cursor pages and stable order.
- Composer tests for draft preservation, exact-key retry, key replacement after edit, acceptance insertion, and queue/rate errors.

### Integration and Browser Tests

- Session restore, signed-out redirect, sign-in return, and private-query cleanup.
- Empty list to `/home/new` on desktop and mobile, then successful replacement with the selected Ally route.
- Authenticated onboarding create/replay and post-create selection.
- Existing public waitlist path regression.
- Deep link, foreign/missing ID, first-Ally default selection, browser Back, and responsive list/chat composition.
- Conversation initial page, older page, send, active poll, completed, failed, stopped, awaiting-action, polling budget, hidden document, and unmount cancellation.
- Keyboard order, focus trap/restore, screen-reader labels, reduced motion, safe areas, and long-content overflow.
- Messaging-shell visual assertions: continuous compact rows, strong selection, minimal thread header, persistent composer, correct desktop master-detail and mobile list-to-thread composition, and absence of unsupported social/filter/call/read-receipt metadata.

### Commands

Run from the Cloud worktree:

```powershell
make check
make lint
make test APP=allies/tests/test_api.py
make test APP=config/tests/test_api_contract.py
make test
cd backend
uv run pytest --cov=auths --cov=workspaces --cov-fail-under=90
uv run ruff format --check .
```

Run from the Interface worktree after the canonical staging schema is published:

```powershell
bun run cloud:fetch
bun run cloud:generate
bun run cloud:check
bun run typecheck
bun run test:run
bun run lint:web
bun run build:web
```

Run the existing onboarding browser suite and extend its configured project or add a focused Home project rather than silently leaving Home outside browser coverage:

```powershell
bun --filter web exec playwright test
```

### Manual Verification Checklist

1. Use an empty signed-in local Workspace: verify no fake row and `/home/new` in-thread creation on desktop and mobile.
2. Complete onboarding with a real greeting/reply: verify one Ally, correct avatar/name/Job, persisted first exchange, and selected URL.
3. Reload and use Back/Forward: verify selection and list/chat mobile behavior.
4. Send one text, interrupt and exact-retry the request, and confirm one accepted message.
5. Observe queued, running deltas, completion, failure, awaiting action, and the polling-budget fallback without claiming streaming.
6. Expire the session during list, send, and polling requests: verify private cache cleanup and `/home` return path.
7. Exercise pending/retryable/failed/repair provisioning fixtures and verify composer gating.
8. Compare Home and onboarding screenshots for Open Runde hierarchy, orange action, gray surfaces, avatar scale, rounded geometry, whitespace, focus, and motion.
9. Blur or mask copy in desktop and mobile screenshots: verify the structure still reads as messaging, then compare against the Substack Chat and WhatsApp Web references to confirm that only roster/thread patterns were borrowed and Allies identity remains dominant.

## Risks and Mitigations

| Risk | Impact | Mitigation | Rollback or fallback |
| --- | --- | --- | --- |
| Activity snapshots are not durable replay and cap visible rows at 200 | A long or disconnected turn may not reconstruct every assistant fragment after reload | Preserve unseen deltas during the mounted turn, state the latest-available limitation, bound polling, and keep CLD-006 out of this slice | Disable runtime response assembly and leave history/send readable; do not invent a complete reply. |
| Current onboarding preview is tightly coupled to waitlist completion | A careless reuse could break the public launch flow | Extract one narrow preview-flow contract and keep separate provider ownership; run all waitlist regressions | Revert the shared extraction and keep authenticated preview behind a focused adapter while retaining the same presentation primitives. |
| Cross-repo contract lands out of order | Interface could pin a schema that staging does not serve | Cloud endpoint and canonical OpenAPI publication precede the committed client snapshot | Keep Home behind the implementation branch until `cloud:check` matches canonical staging. |
| Provisioning is not immediately bound | A new Ally may exist before it can accept messages | Select it, show the persisted conversation and truthful `Getting ready`, disable composer, and bounded-refetch the Ally | Return to the list with the row visible; never delete or pretend creation failed after Cloud committed it. |
| URL contains a missing or foreign Ally ID | Existence could leak or stale selection could break the shell | Resolve against authorized list and preserve Cloud's privacy-safe `404` language | Navigate to `/home` without identifying the foreign resource. |
| Unpaginated Ally collection grows beyond the MVP assumption | Response and render work could become large | Keep the query relation-loaded, record the explicit small-account assumption, and add cursor pagination when measured counts justify it | If implementation data already violates the assumption, stop and revise this plan before shipping. |
| Shared dirty worktrees contain unrelated auth/Docker changes | Accidental commits could mix scopes | Preserve current changes, stage by explicit path, and inspect both diffs before any later commit | Remove only this feature's staged paths from a future commit; never reset user work. |
| Design drifts into a generic messaging clone or AI dashboard | The surface may resemble the references without expressing Allies, or may stop reading as messaging | Use the reference screenshots only for master-detail hierarchy; use the local typeface, CTA, avatar component, gray surfaces, whitespace, and motion for identity; apply the blurred-copy recognition check | Reject the visual phase and retune CSS without rolling back contract/data work. |

## Rollout and Rollback

1. Land and deploy the additive Cloud list endpoint with its existing routes unchanged.
2. Pin the canonical staging OpenAPI in Interface and land the generated/client additions.
3. Land `/home` and change the sign-in default only after end-to-end staging evidence passes.
4. Rollback is route-level and additive: restore the prior post-auth target to `/account` and remove Home navigation while leaving the safe Cloud GET endpoint and client additions in place. No data migration or destructive cleanup is needed.
5. If activity rendering proves unreliable, disable active delta assembly and keep the selected Ally history/read surface truthful until CLD-006 supplies replay. Existing persisted messages and Allies are unaffected.

## Decisions and Open Questions

### Decisions

- Use `/home/[allyId]` for durable selection; `/home` remains the list/empty entry.
- Use `/home/new` for the provisional creation conversation at every breakpoint. Desktop keeps the roster visible; mobile shows the focused creation thread with normal Back navigation.
- Sort the conversation list by Ally creation time, newest first. Cloud does not expose last-conversation activity, so the UI will not imply recency.
- Keep the collection unpaginated for the small personal-Workspace MVP and make that assumption explicit.
- Use activity snapshots as bounded status checks, not streaming. Poll at 1.5 seconds for at most 80 foreground attempts per submitted turn.
- Show only real server data. Unsupported appearance or missing activity uses an explicit unavailable state rather than a plausible substitute.
- Reuse the public onboarding presentation through a narrow completion-mode contract; do not fork the visible flow or build a workflow framework.

### Open Questions

None block implementation. If real data shows that an Ally collection can already exceed the small-account assumption or that 200 activity records cannot cover ordinary responses while mounted, implementation must pause and revise the affected contract instead of silently weakening the acceptance criteria.
