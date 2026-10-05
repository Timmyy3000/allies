# Mobile Cloud API parity

## Feature Overview

- Problem: The current mobile runtime is a local visual walkthrough even though the shared Cloud client and native session boundary already support the real Allies flow.
- Target users: Signed-in Allies users creating, browsing, and messaging Allies on iOS and Android.
- Source docs/specs: Nabu `projects/allies/index.md`, `projects/allies/engineering/specs/interface/INT-008-mobile-google-auth-and-account.md`, `projects/allies/engineering/specs/interface/mobile-onboarding-implementation.md`, `projects/allies/engineering/specs/conversation-and-streaming.md`, and the web Allies workspace implementation.
- Success outcome: Mobile uses the same typed Cloud contracts, idempotency, retry, ordering, terminal-state, pagination, and authorization behavior as web while keeping native navigation, bearer transport, storage, and presentation.

## Plan Hygiene and Evidence Boundaries

This plan contains repository-relative paths and synthetic behavior only. It does not contain credentials, private URLs, device details, or live user records.

## User Stories

1. As a new user, I want my onboarding reply and Ally configuration preserved through Google sign-in, so that I do not lose the Ally I started creating.
2. As an Ally user, I want sent messages to survive uncertain network results, so that retrying does not create a duplicate.
3. As an Ally user, I want the roster and conversation to reflect Cloud state, so that mobile and web show the same durable data.
4. As an Ally user, I want activity updates to remain ordered and visible through terminal or partial states, so that an incomplete response is not silently hidden.

## Scope

### In Scope

- Remove the mobile runtime dependency on the local mock provider.
- Connect onboarding attempts, authenticated Ally creation, durable workspace roster, and native Google session continuation.
- Connect conversation history, exact message sends, replay handling, retry persistence, activity polling, terminal refetch, and reconciliation messaging.
- Reuse `@allies/cloud-client` schemas, mappers, errors, idempotency inputs, and activity projection.
- Restore the native account/profile surface for the existing account and avatar Cloud operations.
- Preserve current Allies visual screens and native interaction patterns.

### Out of Scope

- Waitlist entry or waitlist completion. Mobile has no waitlist path.
- Web routes, web components, browser cookies, CSRF transport, or web SSE implementation.
- New Cloud endpoints or changes to Cloud authorization.
- New mock data in the production runtime.

### Dependencies and Assumptions

- The generated Cloud contract and `@allies/cloud-client` are the source of truth.
- A configured mobile build has `EXPO_PUBLIC_CLOUD_API_URL` and the registered native return URL; a client-less build remains unavailable rather than pretending to be connected.
- Cloud exposes the durable workspace-scoped Ally collection and conversation/activity endpoints already present in the shared client.
- Native activity polling is acceptable where the web client uses SSE; both consume the same activity snapshot and projection rules.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/lib/cloud/native-cloud-client.ts` | `isAuthenticatedCloudRequest` | `(request: Request) => boolean` | Exact method and path allowlist; retry endpoint included | Whether the request receives the in-memory bearer | No bearer for public onboarding or native auth; unknown routes stay cookie-free |
| `apps/mobile/src/features/allies/queries.ts` | `useAllies` | `(workspaceId: string) => query result` | Signed-in workspace ID | `AllyViewModel[]` | Uses shared client and refresh adapter; refetches pending provisioning with a bounded interval |
| `apps/mobile/src/features/conversation/conversation-state.ts` | `mergeConversationMessages` | `(pages: readonly ConversationViewModel[]) => MessageViewModel[]` | Immutable message IDs and matching copies | Ordered, deduplicated messages | Conflicting copies surface a reconciliation error |
| `apps/mobile/src/features/conversation/conversation-state.ts` | `projectMobileActivity` | `(current: ActivityProjection, snapshot: ActivitySnapshotViewModel) => ActivityProjection` | Shared activity snapshot view model | Shared monotonic projection | Out-of-order and duplicate activities remain visible; permanent terminal gaps are explicit |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Mobile onboarding | `POST /api/v1/onboarding/attempts` | Public Cloud onboarding contract | Shared `AllySeedInput` mapping | Attempt token and greeting | Validation is terminal for the current attempt; network uncertainty can be retried with a fresh preview |
| Mobile creation | `POST /api/v1/workspaces/{workspace_id}/allies` | Native bearer; workspace authority remains Cloud-side | Shared `CreateAllyInput` with onboarding attempt and reply | `AllyViewModel`; `201` or `202` | Reuse the same idempotency key for the same command, including after sign-in or uncertainty; rotate only after intent changes |
| Mobile roster | `GET /api/v1/workspaces/{workspace_id}/allies` | Native bearer; workspace-scoped | None | `AllyViewModel[]` | Query retry follows shared Cloud error policy; pending provisioning is polled while bounded |
| Mobile conversation | `GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation` and `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}` | Native bearer; Ally/conversation authorization is Cloud-side | Typed cursor and limit | `ConversationViewModel` | Older pages merge with loaded messages and retain the latest cursor |
| Mobile send | `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages` | Native bearer; conversation authority is Cloud-side | Exact trimmed message body and idempotency header | `MessageAcceptanceViewModel` | Persist before send; `replayed: true` is accepted and deduplicated; ambiguous results retain the pending command |
| Mobile retry | `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/{message_id}/retry` | Native bearer; conversation authority is Cloud-side | Existing message ID and stable retry key | `MessageAcceptanceViewModel` | Reuse the pending key and refetch when a terminal status is returned |
| Mobile activity | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities` | Native bearer; conversation authority is Cloud-side | Typed limit/cursor/replay options | `ActivitySnapshotViewModel` | Poll only while focused and active, stop at terminal/error/budget, refetch conversation on terminal |

Representative creation request:

```json
{
  "name": "Example Ally",
  "job": "Help plan my workday",
  "personality": "I want you to be concise",
  "appearance": { "catalog_version": "v1", "key": "ghosty:ff5800" },
  "onboarding_attempt": "<attempt-token>",
  "reply": "Help me plan tomorrow"
}
```

Representative accepted-send response:

```json
{
  "status": "success",
  "data": {
    "conversation_id": "<conversation-id>",
    "message": {
      "id": "<message-id>",
      "sender": "user",
      "content": "Help me plan tomorrow",
      "sequence": 4,
      "status": "queued",
      "created_at": "<timestamp>",
      "retryable": false
    },
    "execution": null,
    "replayed": false
  }
}
```

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `AllyViewModel` | `packages/cloud-client/src/mappers/allies.ts` | ID, name, job, personality, appearance, provisioning state, retryable | Required fields from shared schema | Never infer authorization or durable identity from local state | Shared with web |
| `PendingCreateCommand` | `apps/mobile/src/lib/pending-command-store.ts` | Full create intent, attempt token, reply, key, timestamps, optional account binding | Encrypted at rest; bounded lifetime | Same intent keeps its key; binding prevents cross-account reuse | Existing encrypted store reused |
| `PendingMessageCommand` | `apps/mobile/src/lib/pending-command-store.ts` | Conversation ID, exact content, key, timestamps, account/workspace binding | Encrypted at rest; one pending message per conversation | Never delete after ambiguous acceptance | Existing encrypted store reused |
| `ActivityProjection` | `packages/cloud-client/src/activity-projection.ts` | Seen sequences, turns, state, contiguous sequence, pending activities | Shared empty projection default | Monotonic state and sequence ordering | No mobile-specific duplicate reducer |

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Onboarding preview | `submit(reply: string): Promise<boolean>` | Preview -> account continuation or create -> Ally conversation | Onboarding attempt + exact reply -> `CreateAllyInput` | Preserve pending create through native Google sign-in; report expired attempt and retry |
| Ally roster | `openAlly(allyId: string): void` | Session -> roster loading -> loaded/empty/error | Durable Ally list -> existing roster presentation model | Signed-out route goes to native sign-in; provisioning state remains visible |
| Conversation composer | `send(content: string): Promise<void>` | Idle -> pending persisted -> accepted/replayed or retained retry | Exact body + stable key -> acceptance | Disable duplicate sends; show retry and terminal/reconciliation states |
| Account | `updateProfile`, `uploadAvatar`, `deleteAvatar`, `logout` | Query -> edit/upload -> success/error | Shared account/avatar client methods | Cloud authorization and validation remain authoritative |

## Phases

### Phase 1 - Reconnect the real Cloud boundaries

- Goal: Make the production router use native session, onboarding, roster, and account data.
- Work items: Remove the mock provider wrapper, include the retry route in the native bearer allowlist, preserve pending onboarding commands across Google sign-in, restore the completion route, add durable roster queries and appearance mapping, and restore account/profile support.
- Impacted files/systems: Mobile providers, routes, onboarding flow, session routing, Ally queries, account feature, shared Cloud client transport tests.
- Exit criteria: No production route reads `useMockApp`; signed-in roster data comes from `listAllies`; a signed-out create intent is encrypted and resumes after sign-in; waitlist is not referenced.

### Phase 2 - Match conversation behavior

- Goal: Bring mobile message and activity behavior to the web contract without copying web presentation.
- Work items: Add typed conversation queries, immutable-ID history merging, pending send persistence, replay-safe acceptance, retry action, bounded foreground activity polling, shared activity projection, terminal refetch, and permanent-gap messaging.
- Impacted files/systems: Mobile conversation route/features, pending command store, shared Cloud activity projection.
- Exit criteria: Replayed sends do not duplicate, ambiguous acceptance remains retryable with the same key, older pages remain loaded, terminal snapshots refetch the conversation, and activity gaps are visible.

### Phase 3 - Verify and document

- Goal: Leave runnable checks and an accurate handoff.
- Work items: Run focused tests, mobile lint/typecheck, relevant shared package tests, update the mobile README and Nabu handoff with the implementation boundary, and inspect the final diff for accidental waitlist/mock runtime paths.
- Impacted files/systems: Mobile tests, README, Nabu implementation handoff.
- Exit criteria: All available relevant checks pass; any environment-only limitation is stated; README and Nabu describe the same runtime behavior.

## Acceptance Criteria

1. Mobile onboarding calls the shared public onboarding attempt API, preserves its token and greeting, requires the reply, and sends the exact create fields with stable idempotency.
2. A signed-out create intent survives native Google sign-in in the encrypted pending-command store and finishes once with the same key.
3. The home roster uses the durable workspace Ally collection, not the session-only mock/index model, and handles pending/error/empty states.
4. Conversation history merges pages without dropping loaded messages and maintains cursor/order invariants.
5. Message sends persist before network submission; replayed, uncertain, retry, terminal, and permanent-gap states are safe and visible.
6. Activity polling is foreground-only, bounded, abortable, and stops at terminal or error states; the shared projection handles dedupe and monotonic state.
7. No waitlist API or waitlist route is used by mobile.
8. Account/profile/avatar operations use the shared Cloud client and native bearer session boundary.

## Backend Considerations

### Query Optimization Plan

- Hotspots/endpoints: Workspace Ally list, latest conversation page, activity snapshot.
- Query-shape choices: Request bounded latest pages; request older pages only on user action; request activity snapshots within the shared limit; preview roster messages only when the mobile surface needs them.
- Expected query-count change: One roster query and one conversation query per opened Ally, with bounded activity polling during active work.
- Measurement/monitoring plan: Use query keys and request logs available in the existing Cloud client; do not add a mobile analytics system for this slice.

### N+1 Prevention

- Relation access map: Roster loads Allies; conversation loads the selected Ally’s conversation; activity loads the selected conversation.
- Prefetch/select plan per endpoint/service: No per-row detail fetch is required for the roster; use the Ally list response directly.
- N+1 regression guardrails: Do not call Ally detail or conversation endpoints for every roster row unless a later preview requirement explicitly adds it.

### Detailed Unit Test Cases

- Happy path: attempt -> reply -> authenticated create; roster query; conversation send and terminal refresh.
- Validation and bad input: invalid IDs, missing reply, invalid cursor, malformed Cloud response.
- Auth/RBAC boundaries: bearer only on exact authenticated paths; public onboarding and native auth remain bearer-free; Cloud denial is shown, not bypassed.
- Idempotency/retry behavior: replayed send deduplication, same key after timeout/ambiguous result, retry route authorization.
- Failure-path behavior: permanent activity gap, out-of-order/duplicate activities, expired attempt, stale session, older-page preservation.

## Frontend Considerations

### Data Path

- User action entry: Onboarding reply, roster Ally selection, conversation composer, account controls.
- Client route/component: Native Expo Router screens and current mobile presentation components.
- Client API route/proxy: `MobileCloudClient` using shared `CloudClient` operations and native bearer preparation.
- Backend endpoint: Shared Cloud onboarding, workspace, Ally, conversation, message, activity, and account contracts.
- Response -> UI model mapping: Shared Zod schemas/mappers -> existing mobile presentation models; appearance key is normalized only for rendering.
- Error/loading/retry path: Shared Cloud error classification, native session refresh, encrypted pending commands, explicit retry/reconciliation UI.

### State Management Considerations

- State ownership by layer: Session in `NativeSessionProvider`; server state in React Query; pending intent in encrypted command store; activity projection in conversation screen state.
- Source of truth vs derived state: Cloud owns authorization and durable records; query cache owns loaded server pages; projection and presentation are derived.
- Caching/invalidation approach: Stable workspace/Ally/conversation keys; invalidate roster after creation and latest conversation after terminal activity.
- Concurrency and dedupe handling: Query abort signals, serialized pending-store writes, stable idempotency keys, immutable message IDs, and mounted/focused guards.

## Test Plan

- Unit tests: Native route allowlist, safe return route, appearance mapping, conversation page merge, acceptance/retry policy, activity projection integration.
- Integration/API tests: Existing `@allies/cloud-client` contract tests and mobile session/pending-command tests; add no waitlist tests to mobile.
- Regression checks: Existing onboarding and visual component tests remain green; mock fixtures may remain isolated but are not mounted by production providers.
- Manual verification checklist: Configure Cloud, sign in with Google, complete onboarding, verify durable roster, open conversation, send once, simulate/retry an uncertain send, load older history, observe active and terminal activity, sign out, and verify waitlist is absent.
- Commands: `bun run test:run -- apps/mobile/src`, `bun run lint:mobile`, `bun --filter mobile typecheck`, `bun run lint`.

## Risks and Mitigations

- Risk: An interrupted native sign-in loses a create intent. Mitigation: Save and bind the encrypted command before leaving onboarding; retain its idempotency key.
- Risk: Mobile activity polling consumes too many requests. Mitigation: Foreground-only polling, terminal stop, abort cleanup, and a bounded budget.
- Risk: A Cloud appearance catalog grows beyond current artwork. Mitigation: Normalize unknown keys to a safe existing Ally rendering while preserving the server record.
- Risk: The current mock visual fixtures are accidentally reintroduced. Mitigation: Remove their provider from `AppProviders`, scan runtime imports, and keep mock files isolated from production routes.
- Rollback/fallback: Revert only the feature branch commit; a client-less build remains an explicit unavailable state and never claims a durable write.
