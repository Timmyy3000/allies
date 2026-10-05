# Mobile App Surface Foundation Plan

## Feature Overview

- Problem: The mobile app has polished onboarding and account screens, but it does not yet provide the signed-in Ally workspace or a real Cloud-backed conversation.
- Target users: Signed-in internal alpha testers.
- Source docs/specs: Nabu product requirements, product design specification, M2-M4 roadmap, Interface roadmap, conversation specification, the live staging OpenAPI, Expo SDK 57 documentation, `ENGINEERING_STYLE.md`, and the current mobile source.
- Success outcome: A tester can create, open, use, and inspect an Ally through real Cloud data. The app shows honest limits where the accepted Cloud contract is incomplete.

## User Stories

1. As a signed-in tester, I want to create and open an Ally, so that I can start useful work with a named helper.
2. As a tester, I want clear loading, pending, offline, failure, and retry states, so that I know what the app has and has not completed.
3. As an engineer, I want the client to use only the public Cloud contract, so that product truth and authorization stay in Cloud.

## Scope

### In Scope

- M2 stack routes: workspace, Create Ally, continuous conversation, and read-only identity.
- Contract refresh and generated TypeScript refresh, pinned on 2026-08-28 at SHA-256 `1fceace350f418f1371451356e4dcf5626259cf2148b36d2611c36dfb0ea3b4f`.
- Validated Cloud client methods and view models for onboarding attempts, Ally creation and retrieval, conversation retrieval, message submission, and activity snapshots.
- Route-aware signed-in and signed-out redirects.
- An in-memory address book of Ally IDs created or opened in the current signed-in lifecycle. Every card must come from a Cloud fetch.
- Existing onboarding reuse for the official preview-first, authenticate-before-create journey.
- One encrypted pending-command store for the OAuth handoff and unknown create/send outcomes. It uses the already-installed Expo Crypto, FileSystem, and SecureStore modules.
- Bounded message pagination and bounded activity polling.
- Account access, sign-out cleanup, accessibility, reduced motion, and complete request states.
- A documented screen map for M3 and M4.

### Out of Scope

- M3 and M4 route code.
- Tabs in M2.
- Local durable Ally catalog or mock fallback.
- Manual memory, responsibility, routine, or permission editors.
- Multiple conversations per Ally.
- Runtime, Foundry, or Hermes UI and transport.
- Attachments without an accepted Cloud contract.
- New libraries, analytics, flags, background jobs, or speculative architecture.

### Dependencies and Assumptions

- Native Google sign-in and token refresh are already available.
- `AccountViewModel.workspace.id` supplies the authorized workspace ID after sign-in.
- Appearance catalog `v1` uses `<shape>:<hex-without-#>` keys.
- Cloud owns message ordering, provisioning, retryability, and activity projection.
- The current API does not list Allies. This is an M2 mobile slice, not complete M2: the workspace is session-scoped and incomplete by design. It must say so and record the exception in Nabu.
- A future Cloud collection endpoint replaces only the in-memory ID source. It must not require a screen rewrite.

## Screen Map

| Milestone | Destination | Purpose | Implementation status |
| --- | --- | --- | --- |
| M2 | Allies workspace | Open a reachable Ally, create another Ally, or open Account | Implement now |
| M2 | Create Ally | Reuse name, appearance, job, personality, and preview screens | Implement now |
| M2 | Ally conversation | Show one continuous history, composer, and lifecycle activity | Implement now |
| M2 | Ally identity | Show name, appearance, job, and personality | Implement now |
| M3 | Allies root | Durable server-backed Ally collection | Map only; blocked by collection contract |
| M3 | Activity root | Attention feed for results, waiting, approvals, failures, and routine outcomes | Map only |
| M3 | Settings root | Account, integrations, responsibilities, and routines entry points | Map only |
| M3 | Profile | Edit user identity under Settings | Existing account capability; future navigation only |
| M3 | Integration detail | Connect and manage a supported integration | Map only |
| M3 | Responsibility detail | Review responsibilities created through conversation | Map only |
| M3 | Routine detail | Review routines created through conversation | Map only |
| M4 | Approval detail | Review and approve a consequential Ally action | Map only |
| M4 | Usage | Show understandable usage and limits | Map only |
| M4 | Delete Ally | Explain impact, confirm, and show durable completion | Map only |
| M4 | Recovery | Reconcile interrupted, failed, or uncertain work | Map only |

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `packages/cloud-client/src/client.ts` | `beginOnboardingAttempt` | `(input: OnboardingAttemptInput, signal?: AbortSignal) => Promise<OnboardingAttemptViewModel>` | Final name, job, exact personality, and appearance; reject pre-aborted signals | `{ attemptToken, greeting }` | Network, validation, malformed-response errors |
| `packages/cloud-client/src/client.ts` | `createAlly` | `(workspaceId, input, idempotencyKey, signal?) => Promise<AllyViewModel>` | Non-empty IDs and UUID-like idempotency value; request schema validation | Cloud Ally view model | Auth, validation, conflict, network, contract errors |
| `packages/cloud-client/src/client.ts` | `getAlly` | `(workspaceId, allyId, signal?) => Promise<AllyViewModel>` | Non-empty path IDs | Cloud Ally view model | Auth, not-found, network, contract errors |
| `packages/cloud-client/src/client.ts` | `getConversationByAlly` | `(workspaceId, allyId, page?, signal?) => Promise<ConversationPageViewModel>` | `limit` is bounded; cursor is opaque | Conversation page with messages and next cursor | Auth, not-found, network, contract errors |
| `packages/cloud-client/src/client.ts` | `sendMessage` | `(workspaceId, conversationId, content, idempotencyKey, signal?) => Promise<MessageAcceptanceViewModel>` | Trimmed non-empty content; bounded by Cloud schema | Accepted message, execution summary, replay flag | Auth, validation, conflict, network, contract errors |
| `packages/cloud-client/src/client.ts` | `getActivitySnapshot` | `(workspaceId, conversationId, limit?, signal?) => Promise<ActivitySnapshotViewModel>` | Bounded limit | Ordered safe activity rows and state | Auth, not-found, network, contract errors |
| `apps/mobile/src/features/allies/ally-session-index.tsx` | `addReachableAlly` | `(allyId: string) => void` | Non-empty Cloud Ally ID | None | Adds an ID to current signed-in memory only |
| `apps/mobile/src/features/allies/ally-session-index.tsx` | `clearReachableAllies` | `() => void` | None | None | Clears IDs at sign-out or session invalidation |
| `apps/mobile/src/features/allies/ally-queries.ts` | query and mutation hooks | Existing React Query conventions | Use session adapter for token refresh | Typed query and mutation results | Cache updates and invalidation only after Cloud success |
| `apps/mobile/src/features/onboarding/onboarding-cloud-input.ts` | `toCreateAllyInput` | `(flow, attemptToken, reply) => CreateAllyInput` | Trim required values; validate selected color and shape | Cloud request input | Throws a local validation error before transport |
| `apps/mobile/src/features/conversation/conversation-state.ts` | `getPollingDecision` | `(messageStatuses, snapshotState, elapsedMs, isFocused) => 'poll' | 'paused' | 'terminal' | 'unknown' | 'limit'` | Known strings, ten-minute ceiling, route focus | Explicit polling decision | No side effects |
| `apps/mobile/src/lib/pending-command-store.ts` | `createPendingCommandStore` | `(dependencies?) => PendingCommandStore` | Zod-validated create and message commands; current 4,000-character reply remains valid | Read/write/delete/clear methods | Encrypts JSON with Expo Crypto AES-GCM, writes ciphertext under `Paths.document`, keeps the AES key in SecureStore, and supports injected test storage |

Do not add a repository, service class, provider, or new global state library. One small store factory follows the existing `createSecureSessionStore` pattern and permits deterministic tests. It exists only because OAuth and unknown outcomes require the same command identity after remount. Add new methods to the current shared client and use React Query hooks in mobile feature folders.

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Mobile | `POST /api/v1/onboarding/attempts` | Public contract | `OnboardingAttemptRequest` with final configuration | `SuccessResponse<OnboardingAttemptResponse>` | Retry the same configuration after user action; a configuration edit starts a new attempt |
| Mobile | `POST /api/v1/workspaces/{workspace_id}/allies` | Bearer session; Cloud checks workspace access | `CreateAllyRequest`; required `Idempotency-Key` | `201` or `202` `SuccessResponse<AllyResponse>` | One retry reuses the same key and body; never report success without Cloud success |
| Mobile | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}` | Bearer session; Cloud checks workspace and Ally access | Path IDs | `SuccessResponse<AllyResponse>` | React Query retry policy; no retry for auth, validation, or not-found |
| Mobile | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation` | Bearer session | `limit`, opaque `cursor` | `SuccessResponse<ConversationResponse>` | Cancel on route exit; retry safe request within existing policy |
| Mobile | `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages` | Bearer session | `SendMessageRequest`; required `Idempotency-Key` | `200` or `201` `SuccessResponse<MessageAcceptanceResponse>` | A manual retry reuses the same key and body until definitive acceptance |
| Mobile | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities` | Bearer session | Bounded `limit` | `SuccessResponse<ActivitySnapshotResponse>` | Poll only while active; stop on terminal state, blur, or unmount |

Representative creation request:

```json
{
  "name": "Sally",
  "job": "Help me plan and finish important work.",
  "personality": "I want you to be concise, quirky",
  "appearance": {
    "catalog_version": "v1",
    "key": "ghosty:fd304f"
  },
  "onboarding_attempt": "opaque-attempt-token",
  "reply": "Let us plan my week."
}
```

Representative creation response data:

```json
{
  "id": "ally_123",
  "binding_id": "binding_123",
  "operation_id": "operation_123",
  "name": "Sally",
  "job": "Help me plan and finish important work.",
  "personality": "I want you to be concise, quirky",
  "appearance": {
    "catalog_version": "v1",
    "key": "ghosty:fd304f"
  },
  "provisioning_state": "pending",
  "retryable": false
}
```

Representative message request:

```json
{
  "content": "Help me choose the three most important tasks for today."
}
```

Representative message acceptance data:

```json
{
  "conversation_id": "conversation_123",
  "message": {
    "id": "message_123",
    "sender": "user",
    "content": "Help me choose the three most important tasks for today.",
    "sequence": 4,
    "status": "accepted",
    "created_at": "2026-08-28T09:00:00Z"
  },
  "execution": null,
  "replayed": false
}
```

The client treats cursors and all IDs as opaque. It does not parse runtime identifiers. The client accepts additive response fields through loose boundary schemas but rejects missing required fields and malformed values.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `AllyViewModel` | `packages/cloud-client/src/client.ts` | `id`, `name`, `job`, `personality`, `appearance`, `provisioningState`, `retryable` | Required | IDs and text are non-empty; appearance is catalog version and key | Additive client type; no storage migration |
| `ConversationPageViewModel` | same | `id`, `allyId`, `messages`, `nextCursor` | Cursor nullable | Messages retain Cloud sequence | Cursor is opaque |
| `MessageViewModel` | same | `id`, `sender`, `content`, `sequence`, `status`, `createdAt` | Required | Sequence is a non-negative integer; date is ISO | Unknown sender/status renders neutral UI |
| `ActivitySnapshotViewModel` | same | `conversationId`, `activities`, `state`, `lastContiguousSequence` | Required | Activity order follows sequence | Unknown kinds render safe text without special controls |
| `ReachableAllyId[]` | mobile memory | Cloud Ally IDs | Empty by default | IDs enter only after a Cloud response or a valid route open; reveal 12 at a time with one `visibleCount` | Not persisted; replace with collection query later |
| `PendingCreateCommand` | encrypted document file | exact create body, idempotency key, Cloud greeting, created time, expiry, optional bound user and workspace | Schema-validated; preserves current input limits; expires after seven days | Encrypt and write before sign-in; bind atomically to the first authenticated `userId` and workspace before transport; retry uses the same body and key | Delete after definitive success, explicit cancel, expiry, account/workspace mismatch, or explicit sign-out |
| `PendingMessageCommand` | encrypted document file per conversation | conversation ID, exact content, idempotency key, created time, bound user ID, and workspace ID | One unresolved command per conversation; schema-validated | Encrypt and write before transport; retry uses the same body and key only for the bound principal | Delete after definitive acceptance, explicit discard, account/workspace mismatch, or explicit sign-out |

There is no database migration and no durable mobile product model.

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Workspace | `useReachableAllies()` | `loading -> content | empty | error` | Session IDs -> parallel bounded `getAlly` queries | Skeleton rows, honest session-only empty copy, per-screen retry, sign-in redirect |
| Create Ally | `createAlly.mutate(input)` | `editing -> attempt_pending -> preview -> auth_required -> create_pending -> provisioning | ready | error` | Existing flow -> `OnboardingAttemptRequest` -> Cloud greeting -> persisted `CreateAllyRequest` -> `AllyViewModel` | Preserve form and exact command; require sign-in before production create |
| Conversation | `useConversation(allyId)` | `loading -> ready -> submitting -> accepted -> active | awaiting_action | terminal | unknown` | Route ID -> Cloud Ally and conversation -> ordered message/activity view | Full-screen retry for first load; one unresolved transport command at a time; later accepted messages may queue in Cloud |
| Identity | `useAlly(allyId)` | `loading -> content | error` | Route ID -> `AllyViewModel` | Read-only; retry or back action |
| Account | existing hooks | Existing states | Existing account endpoints | Reachable from workspace; sign-out returns to sign-in |

### Route and Session Matrix

| Session state | Public `/` | `/sign-in` | `/auth/return` | Protected `/allies*` and `/account` |
| --- | --- | --- | --- | --- |
| `checking` / `refreshing` | Keep route and show bootstrap state | Keep route; disable sign-in action | Keep route so callback delivery can finish | Keep route and show bootstrap state; do not redirect yet |
| `signed-out` | Allow official onboarding | Allow; retain validated `returnTo` | Always allow | Replace with `/sign-in?returnTo=<safe-path>` |
| `signed-in` | Replace with `/allies`; workspace exposes pending-create resume | Replace with validated `returnTo` or `/allies` | Allow until callback delivery completes, then caller routes | Allow |
| `offline-with-session` | Replace with `/allies` | Replace with `/allies` | Allow | Allow read shell and cached data; disable mutations and show offline recovery |
| `unavailable` | Allow with storage/auth-unavailable state | Allow with unavailable state | Allow | Keep route and show unavailable recovery; do not loop redirects |

`returnTo` uses the existing safe relative-path parser and accepts only signed-in app routes. Sign-out uses route replacement. The callback route is never redirected before `deliverNativeAuthReturn` runs.

### Official Onboarding State Machine

| State | Trigger | Action | Failure / back behavior |
| --- | --- | --- | --- |
| `editing` | User completes personality | Submit final configuration to `POST /onboarding/attempts` | Keep fields and show Retry; Back edits fields |
| `attempt_pending` | Request succeeds | Store token and Cloud greeting in flow memory; enter preview | Abort on unmount |
| `preview` | User sends first reply | Create one idempotency key, set a seven-day expiry, AES-encrypt the exact unbound pending create command, and atomically move its ciphertext into the app document directory before navigation or transport | Encryption or storage failure blocks transport and preserves UI input; no valid input-size reduction |
| `auth_required` | User is signed out | Route to `/sign-in?returnTo=/allies/new/complete` | Sign-in cancel keeps the pending command; explicit Cancel clears it |
| `create_pending` | Signed-in user or auth return | Reject and delete expired or mismatched records. Atomically bind an unbound record to `account.userId` and `account.workspace.id`, then send the persisted exact command and key. | Network, timeout, or abort keeps the bound command for same-key retry; a later account or workspace cannot read or submit it |
| `provisioning` | Cloud returns `201` or `202` | Add returned Ally ID to reachable memory, clear pending command, open conversation | Render Cloud `provisioning_state` and `retryable` honestly |
| `attempt_invalid` | Cloud rejects expired or invalid attempt | Preserve configuration and reply draft, start a new attempt, show its new greeting, and require reply confirmation before a new command | Never reuse an attempt token with changed configuration |

Editing any final configuration after an attempt exists discards that attempt in local flow memory. It does not mutate Cloud. The preview must render the Cloud greeting, not `FIRST_ALLY_GREETING`, in create mode. The local greeting remains available only to the non-production visual preview test path if one remains.

### Conversation Merge and Polling Rules

- Cloud returns the newest bounded page first. `next_cursor` addresses older messages.
- Use `useInfiniteQuery` and fetch older pages only from the user action.
- Flatten all pages, deduplicate by immutable message ID, and sort by `sequence` ascending.
- The same message ID with different content, sender, or sequence is a contract error. Do not silently choose one copy.
- After accepted send, place the returned durable message in the newest cache page by ID and then refetch the newest page.
- The composer is disabled only while its current network submission is unresolved or when offline/unavailable. Once Cloud accepts a message, another valid message can be sent and Cloud owns bounded queue admission.
- Poll every three seconds while the focused route has `queued`, `in_progress`, or `running` work.
- Stop automatic polling for `awaiting_action`, `completed`, `failed`, `stopped`, an unknown state, blur/unmount, or after ten minutes. Keep manual Refresh and truthful copy.
- Propagate React Query abort signals into every Cloud read.
- Render only `ActivityResponse.text`. Use `state` only for allowlisted visual status. Never render `kind`, IDs, or additional payload fields as user copy.

## Phases

### Phase 1 - Pin and Validate the Cloud Surface

- Goal: Make the accepted staging contract the compile-time and runtime boundary.
- Work items:
  - Completed planning gate: `bun run cloud:fetch`, `bun run cloud:generate`, and `bun run cloud:verify` pinned SHA-256 `1fceace350f418f1371451356e4dcf5626259cf2148b36d2611c36dfb0ea3b4f` on 2026-08-28.
  - Verify all seven required public paths, both idempotency headers, request bodies, cursor/limit parameters, and response fields before client code.
  - Implement client methods only for operations consumed by M2. Defer `getConversationById` until a route needs it, but include its path in authenticated request classification.
  - Add boundary schemas, view models, and client methods to the existing `packages/cloud-client/src/client.ts`.
  - Expand `isAuthenticatedCloudRequest` for accepted workspace, Ally, conversation, message, and activity paths.
  - Add focused client and mobile transport tests for mapping, authorization header scope, aborts, malformed responses, idempotency, and retry identity.
- Impacted files/systems:
  - `packages/cloud-client/openapi/allies-cloud-0.1.0.json`
  - `packages/cloud-client/openapi/metadata.json`
  - `packages/cloud-client/src/generated/openapi.ts`
  - `packages/cloud-client/src/client.ts`
  - `packages/cloud-client/src/index.ts`
  - `packages/cloud-client/test/*`
  - `apps/mobile/src/lib/cloud/native-cloud-client.ts`
  - `apps/mobile/src/lib/cloud/native-cloud-client.test.ts`
- Exit criteria:
  - Generated types match the pinned schema.
  - Every new client operation rejects malformed data and uses the existing controlled transport.
  - Auth headers attach only to accepted protected Allies Cloud paths.

### Phase 2 - Add Honest Signed-In Navigation and Workspace

- Goal: Make `/allies` the signed-in application entry without a tab framework.
- Work items:
  - Replace the current `/account`-only redirect logic with the route/session matrix above.
  - Add `/allies` as the signed-in entry.
  - Add a minimal in-memory reachable-ID context or module scoped to the signed-in provider. Clear it when the session clears.
  - Fetch every workspace row from Cloud and use one local `visibleCount` plus Load more to reveal 12 more IDs at a time.
  - Show the contract-limited empty state: create an Ally, or open one through a current-session route.
  - Add Create Ally and Account actions.
  - Keep the brand logo orange and use Ally accents only on Ally-owned UI.
- Impacted files/systems:
  - `apps/mobile/src/app/_layout.tsx`
  - `apps/mobile/src/app/allies/index.tsx`
  - `apps/mobile/src/lib/providers/app-providers.tsx`
  - `apps/mobile/src/features/allies/ally-session-index.tsx`
  - `apps/mobile/src/features/allies/ally-queries.ts`
  - `apps/mobile/src/features/allies/allies-workspace-screen.tsx`
  - Focused route and state tests.
- Exit criteria:
  - Signed-in routes no longer redirect to Account.
  - Sign-out clears query data and reachable IDs.
  - The workspace never renders an Ally that Cloud did not return.

### Phase 3 - Submit the Existing Onboarding Flow

- Goal: Turn the polished onboarding flow into the only Create Ally form.
- Work items:
  - Add a create mode entry at `/allies/new` that reuses `OnboardingFlow`; keep the signed-out official flow at `/`.
  - Submit the final configuration to begin one onboarding attempt when the user leaves personality. Render the returned Cloud greeting.
  - Keep the existing name, appearance, job, personality, preview, keyboard, and motion behavior.
  - Replace the preview-only send action with the preview callback and state machine above.
  - Build the appearance key from the accepted `v1` catalog convention.
  - AES-encrypt the exact pending create body and Expo Crypto idempotency key before OAuth or transport. Store ciphertext under `Paths.document` and its generated AES key in SecureStore. Reuse the command after timeout, abort, remount, or restart.
  - Expire the pre-auth command after seven days. Bind it to the first authenticated user and workspace before submission. Delete it without display or submission on an account/workspace mismatch. Clear every pending command on explicit sign-out.
  - Use `/allies/new/complete` to resume after authentication. Show a Finish creating card in the workspace when a pending command survives restart.
  - Preserve input after failure. An invalid attempt returns to a new Cloud greeting and requires reply confirmation.
  - On success, add the returned Cloud Ally ID to reachable memory and replace the route with the Ally conversation.
- Impacted files/systems:
  - `apps/mobile/src/app/allies/new.tsx`
  - `apps/mobile/src/app/allies/new/complete.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-flow.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-preview-screen.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-cloud-input.ts`
  - `apps/mobile/src/features/onboarding/onboarding-state.ts`
  - Focused onboarding mapping and mutation tests.
- Exit criteria:
  - There is one creation form and one Cloud submission path.
  - A failed request does not lose user input or add an Ally to the workspace.
  - A successful response opens the correct Cloud Ally.

### Phase 4 - Add the Continuous Conversation

- Goal: Let the tester talk to one Ally through the accepted Cloud lifecycle.
- Work items:
  - Add `/allies/[allyId]` as the continuous conversation route.
  - Fetch the Ally and its first conversation page in parallel through the refresh adapter.
  - Render messages by Cloud sequence and sender with stable keys.
  - Add a Load earlier action when `nextCursor` exists. Do not auto-fetch unbounded history.
  - Encrypt one unresolved send command per conversation before transport. Disable only a parallel network submission for that conversation; allow another message after acceptance so Cloud can queue it.
  - Invalidate the conversation after acceptance.
  - Apply the explicit merge, dedupe, conflict, polling, timeout, focus, abort, and unknown-state rules above.
  - Render only the safe projected `ActivityResponse.text` as compact status copy.
  - Reuse the existing composer, Ally avatar, shiny thinking label, safe-area, keyboard dismissal, and reduced-motion patterns where they fit.
- Impacted files/systems:
  - `apps/mobile/src/app/allies/[allyId]/index.tsx`
  - `apps/mobile/src/features/conversation/conversation-screen.tsx`
  - `apps/mobile/src/features/conversation/conversation-queries.ts`
  - `apps/mobile/src/features/conversation/conversation-state.ts`
  - Existing onboarding preview components only when extraction reduces duplication.
  - Focused ordering, polling, idempotency, retry, and unknown-state tests.
- Exit criteria:
  - History and activity come only from Cloud.
  - Polling is bounded and stops correctly.
  - A retry cannot submit a different body under the same idempotency key.

### Phase 5 - Add the Read-Only Ally Identity

- Goal: Make the Ally contract understandable without adding edit surfaces.
- Work items:
  - Add `/allies/[allyId]/identity`.
  - Reuse the Ally query and cached Cloud record.
  - Show the Ally image, name, job, personality, appearance, and provisioning state.
  - Add Back and Open conversation actions.
- Impacted files/systems:
  - `apps/mobile/src/app/allies/[allyId]/identity.tsx`
  - `apps/mobile/src/features/allies/ally-identity-screen.tsx`
  - Existing Ally visual components.
- Exit criteria:
  - The screen is read-only and uses Cloud data.
  - It does not imply unsupported editing, memory, routine, or permission controls.

### Phase 6 - Validate, Document, and Release

- Goal: Leave reviewable code, evidence, and an accurate handoff.
- Work items:
  - Run focused tests after each phase and the complete checks before handoff.
  - Perform a Terra diff review and a Ponytail over-engineering review.
  - Test the signed-out, first-create, send, active, complete, failure, retry, offline, sign-out, and reduced-motion flows on Android.
  - Update `apps/mobile/README.md` with routes, Cloud contract, version, collection limitation, validation, and owner-only OTA publishing steps.
  - Update the accepted Nabu product design and mobile implementation notes after the verified commit. Record this as an M2 mobile slice with a time-bounded exception until the Cloud collection endpoint is accepted.
  - Classify the change as OTA eligible if it changes only JavaScript, assets already in the binary, and the pinned schema. Require a new build if native configuration or dependencies change.
  - Commit with a `mobile:` subject and `Co-authored-by: Codex <codex@openai.com>`.
  - Open a PR from `mobile/app-surface-foundation` to `dev`. Do not merge it.
- Impacted files/systems:
  - `apps/mobile/README.md`
  - Nabu Allies product and delivery notes.
  - GitHub pull request.
- Exit criteria:
  - All required checks pass.
  - Documentation describes the exact shipped surface and known contract ceiling.
  - The PR contains no unrelated worktree changes.

## Acceptance Criteria

1. Signed-in testers land on `/allies`, not `/account`.
2. Public auth return routes remain reachable during sign-in.
3. The workspace shows only Ally records fetched from Cloud.
4. The workspace states that server-wide discovery is not available when it has no reachable IDs.
5. Create Ally reuses the existing onboarding screens and visuals.
6. Creation sends the exact accepted shape with a stable idempotency key.
7. Creation failures retain the form and provide a retry.
8. Provisioning and retryable failure states come from the Cloud Ally response.
9. The conversation shows Cloud messages in sequence order and supports bounded cursor pagination.
10. The composer prevents empty and parallel transport submissions but allows later accepted messages to enter Cloud's bounded queue.
11. A message retry reuses the same idempotency key and unchanged body.
12. Polling runs only for allowlisted active states and stops after ten minutes or on paused, terminal, unknown, blurred, or unmounted state.
13. Activity copy uses only `ActivityResponse.text`.
14. Unknown Cloud states do not crash the screen or claim success.
15. Identity is read-only and uses the same cached Cloud Ally record.
16. Account and sign-out remain functional.
17. Sign-out clears session-scoped Ally navigation state and query data.
18. Keyboard dismissal, safe areas, accessibility roles and labels, and reduced motion remain correct.
19. M3 and M4 destinations are documented only.
20. The complete validation commands pass.

## Backend Considerations

### Query Optimization Plan

- Hotspots/endpoints: No backend query changes are in this repository.
- Query-shape choices: The client uses one direct Ally read per reachable ID and bounds that set to the number created or opened in the current lifecycle. Conversation pages and activity snapshots use explicit limits.
- Expected query-count change: One workspace context request, up to one Ally request per current-session ID, one conversation request per open route, and one activity request per active polling interval.
- Measurement/monitoring plan: Use request logs in development and React Query state. Do not add analytics in this change.

### N+1 Prevention

- Relation access map: Not applicable to the Interface repository.
- Prefetch/select plan: Not applicable.
- N+1 regression guardrails: Do not persist or expand the session ID list. Replace per-ID reads with the future collection endpoint when accepted.

### Detailed Unit Test Cases

- Happy path: Map each successful envelope; create an Ally; read conversation; send and complete a turn.
- Validation and bad input: Reject missing fields, malformed dates, negative sequences, empty content, invalid appearance keys, and malformed envelopes.
- Auth/RBAC boundaries: Attach the bearer token only to accepted protected paths; normalize `401` and `403` through existing behavior.
- Idempotency/retry behavior: Reuse a key for the same create/send retry; create a new key after the body changes or a definitive response.
- Failure-path behavior: Abort on route exit, stop polling on failure, preserve form input, and never add a failed creation to the workspace.

## Frontend Considerations

### Data Path

- User action entry: Workspace create action or conversation composer.
- Client route/component: Expo Router stack routes under `apps/mobile/src/app/allies/`.
- Client API route/proxy: Existing `MobileCloudClient` and native session refresh adapter.
- Backend endpoint: Public versioned Allies Cloud paths only.
- Response to UI model mapping: Zod boundary schema -> shared view model -> React Query cache -> screen.
- Error/loading/retry path: React Query state -> explicit loading/error surface -> user retry with the same safe request identity where required.

### State Management Considerations

- State ownership by layer: Cloud owns durable Ally and conversation state. React Query owns fetched cache. Screens own editable drafts. An AES-encrypted document file owns only unresolved exact command identity across OAuth/restart; SecureStore holds its encryption key. A small signed-in provider owns only reachable Ally IDs for the current lifecycle.
- Source of truth vs derived state: The ID set is navigation reachability, not product truth. Every visible row is derived from a current Cloud response.
- Caching/invalidation approach: Use existing React Query defaults. Invalidate exact Ally/conversation/activity keys after mutation success. Clear all signed-in data on session clear.
- Concurrency and dedupe handling: Cloud serializes one active turn and queues later accepted turns. One unresolved client transport command per conversation prevents parallel submission races. Persisted idempotency keys prevent duplicate accepted work. Query keys include workspace, Ally, conversation, and cursor identity.

## Test Plan

- Unit tests:
  - Shared Cloud client schema and mapping tests.
  - Authenticated path classification tests.
  - Onboarding-to-create input tests.
  - Idempotency identity tests.
  - Conversation ordering and active-state tests.
  - Poll stop-condition tests.
  - Session route/status matrix tests.
  - Pending command encryption, maximum current input size, atomic replacement, corrupt ciphertext, missing key, seven-day expiry, account/workspace binding, account switch, sign-out cleanup, and unknown-outcome tests.
  - Cursor overlap/conflict merge tests.
- Integration/API tests:
  - Controlled fetch fixtures for each accepted operation and error family.
  - React Query hook tests where screen behavior depends on invalidation or polling.
- Regression checks:
  - Existing onboarding, account, auth return, keyboard dismissal, animation, and waitlist tests.
- Manual verification checklist:
  - Sign in on Android.
  - Create two Allies in one signed-in app lifecycle.
  - Switch between them without identity or history crossover.
  - Open identity and return to each conversation.
  - Send a message and observe pending, activity, and terminal behavior.
  - Interrupt connectivity and recover with Retry or Refresh.
  - Leave an active conversation and confirm polling stops.
  - Enable reduced motion and confirm non-essential repeated motion stops.
  - Sign out and confirm signed-in state is cleared.
- Commands:
  - `bun run cloud:verify`
  - `bun run cloud:generate`
  - `git diff --exit-code -- packages/cloud-client/src/generated/openapi.ts` after generation is committed
  - `bun run test:run -- packages/cloud-client/test/allies.test.ts apps/mobile/src/lib/cloud/native-cloud-client.test.ts apps/mobile/src/lib/session/session-route.test.ts apps/mobile/src/lib/pending-command-store.test.ts apps/mobile/src/features/onboarding/onboarding-cloud-input.test.ts apps/mobile/src/features/conversation/conversation-state.test.ts` during phases
  - `bun run lint:mobile`
  - `bun run typecheck`
  - `bun run test:run`
  - `bun run bundle:mobile`
  - `bun --filter mobile exec expo export --platform android --output-dir dist/android-check`

## Risks and Mitigations

- Risk: The API cannot list all Allies.
- Mitigation: Keep the workspace honest and session-scoped. Do not persist a catalog. Track the collection endpoint as the condition for complete M2 restoration.
- Rollback/fallback: Keep Account and Create Ally reachable. Revert the new signed-in entry if Cloud creation or retrieval is not accepted.

- Risk: Lifecycle strings can change without an enum.
- Mitigation: Map known states, show neutral unknown states, and never infer completion from unknown text.
- Rollback/fallback: Disable active polling after a conservative time or explicit unknown terminal response and leave manual Refresh.

- Risk: Repeated mutations can duplicate work.
- Mitigation: Retain the key and body for a logical attempt and disable parallel submission.
- Rollback/fallback: Remove automatic mutation retry and keep manual retry with the same identity.

- Risk: Polling harms performance.
- Mitigation: Poll every three seconds only for allowlisted active states, stop after ten minutes, bound payload size, and cancel on blur/unmount.
- Rollback/fallback: Leave manual Refresh and disable polling without changing message history.

- Risk: Route guard changes regress auth return.
- Mitigation: Keep explicit public route tests and preserve `/auth/return` and `/sign-in` behavior.
- Rollback/fallback: Restore the previous redirector while keeping the feature routes unreachable.
