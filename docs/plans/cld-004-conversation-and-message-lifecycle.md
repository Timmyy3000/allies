# CLD-004 Conversation and Message Lifecycle Plan

## Feature Overview

- Problem: Cloud has a durable Ally and onboarding handoff, but no Cloud-owned continuing conversation or exactly-once message acceptance boundary. Interface cannot safely reload history, retry a send, or distinguish durable user intent from downstream execution.
- Target users: signed-in internal-alpha testers using a Workspace-owned Ally; Cloud and Interface engineers consuming the contract; operators proving tenant isolation and durable recovery.
- Source docs/specs: docs/plans/cld-004-kickoff.md; canonical Nabu projects/allies/engineering/specs/cld-004-conversation-and-message-lifecycle.md; Nabu conversation-and-streaming, auth-account-foundation, cld-003-create-and-manage-real-ally, and CLD-004 delivery ticket; AGENTS.md; ENGINEERING_STYLE.md; docs/templates/PLAN_TEMPLATE.md; docs/engineering/backend-development.md; current Allies Cloud code, API, migration, CI, and tests.
- Success outcome: every Ally resolves to one default customer-facing conversation whose onboarding greeting/reply are retained once and in order. A valid text send commits one ordered queued user message before success, retries replay that message, conflicts are rejected, and history remains authorized, bounded, cursor-paginated, and free of private runtime identifiers.

## User Stories

1. As a signed-in Workspace user, I want to open an Ally and see the same continuing conversation, so refreshes and reconnects do not create a new thread.
2. As a user sending text, I want one accepted message durable before the response succeeds, so a disconnect or downstream delay cannot lose my intent.
3. As a retrying client, I want the same idempotency key and normalized content to return the original message, so retries do not duplicate visible messages or work intents.
4. As a user, I want different Allies to retain separate ordered histories and bounded pending work, so one queue cannot alter another Ally.
5. As an Interface engineer, I want product-only request, response, lifecycle, pagination, and error schemas, so the client never calls Foundry or depends on private identifiers.
6. As an operator, I want authorization, concurrency, migration, and privacy evidence, so the feature can be released and rolled back without corrupting accepted work.

## Scope

### In Scope

- Add a focused chat Django domain app for Conversation and Message product records.
- Allow one default conversation per Ally while keeping Conversation first-class and addressable by its own public ID for future group/multi-agent conversations.
- Atomically retain the CLD-003 official onboarding greeting (assistant) followed by the user's reply (user), at most once, at conversation start. Existing CLD-003 Allies are lazily reconciled on first lookup; no waitlist data is imported.
- Store ordered user and assistant messages with one lifecycle enum: queued, in_progress, completed, failed, stopped. A newly accepted user message starts at queued; durable acceptance is not a second public status.
- Accept bounded text-only messages. Normalize Unicode to NFC and trim surrounding whitespace before fingerprinting and persistence; reject empty or oversized input before consuming a send key.
- Persist a caller idempotency-key digest and normalized-content fingerprint on user messages. Same conversation/key/fingerprint replays the original result; same key with different content returns a stable conflict without mutation.
- Enforce bounded send abuse control after authorization and duplicate lookup: one authenticated user/workspace identity may create at most 30 new sends per rolling 10-minute window (configurable by ALLIES_CHAT_SEND_RATE_LIMIT, minimum 1, maximum 120, and ALLIES_CHAT_SEND_RATE_PERIOD_SECONDS, minimum 60, maximum 3600). Replays do not consume the allowance; the limiter key is an HMAC digest of the workspace/user scope and never appears in responses or logs.
- Serialize sequence allocation under the conversation row and enforce a bounded pending queue of 20 queued, accepted user turns (configurable by ALLIES_CHAT_MAX_PENDING_MESSAGES, minimum 1, maximum 100). The active turn is the single accepted user Message in in_progress; it does not consume pending capacity. Capacity is released when CLD-005 asks the primitive to promote the next queued Message to in_progress; CLD-005 does not pre-lock or hold the Conversation lock. Queue saturation rejects only the new send.
- Treat the CLD-003 onboarding greeting and reply as imported history: assistant greeting is completed at sequence 1 and user reply is completed at sequence 2, both origin onboarding, neither has a caller send key, and neither counts toward pending capacity or the active-turn invariant.
- Return newest bounded history first (default 50, maximum 100) and older messages through an opaque, versioned, HMAC-protected cursor. History is complete and durable; cursor scope is one conversation.
- Recheck current Workspace capability on every lookup, send, duplicate replay, and foreign-resource path. Unauthorized/foreign resources are privacy-safe 404s.
- Publish additive versioned Interface-facing schemas and OpenAPI examples for lookup, history, send, replay, conflict, validation, queue-full, invalid cursor, and safe internal errors.
- Register conversation routes through the existing API registrar and rely on the database constraints, migration checks, and route-level authorization/privacy tests described below. No custom runtime switch or ancestry validation job is introduced for Alpha.
- Leave a stable nullable execution projection seam in the send response without implementing CLD-005 gateway dispatch or CLD-006 replay/stream/stop/retry behavior.
- Make API failure logging privacy-safe: route templates and bounded error type/fingerprint only, never request paths with content, exception strings, traceback text, SQL, request bodies, Idempotency-Key values, or provider responses. Wrap chat database/unexpected failures in a safe domain error and rely on the existing sanitized wide-event path.

### Out of Scope

- Multiple default conversations for one Ally, editing/deleting messages, deleting conversations, or retrospective public waitlist imports.
- Image/file attachments (deferred to Beta), responsibilities, routines, approvals, cross-Ally feeds, and final Interface layout/copy/animation.
- Foundry execution dispatch, attempts, event projection, runtime identifiers, Hermes/Fly access, execution acceptance, cursor replay/event streaming, reconnect continuation, stop, execution retry, and terminal recovery (CLD-005/CLD-006).
- New queue/outbox infrastructure, generic repository abstractions, background workers, or speculative event systems.

### Dependencies and Assumptions

- CLD-003 is approved and supplies Ally, OnboardingAttempt.greeting, and the ordered onboarding reply handoff. CLD-004 may modify its create transaction only to invoke the chat handoff.
- AUTH-001's session and require_workspace_capability helpers remain the authentication/authorization boundary; inactive or foreign memberships map to the existing privacy-safe unavailable response.
- Existing root API registration and status/message/data envelope remain unchanged. The new app is registered explicitly and added to INSTALLED_APPS.
- Cloud deploys on PostgreSQL while local tests also run on SQLite. PostgreSQL concurrency tests use the existing postgresql marker. A direct Conversation stores only its Ally foreign key; Workspace is derived from Ally.workspace, so a Conversation cannot carry a mismatched duplicated Workspace authority.
- Exact page choices are fixed here: newest page default 50/max 100; cursor payload includes schema version, key ID/version, conversation public ID, exclusive before_sequence, and expiry; HMAC signs no message content and uses a dedicated configured cursor-signing key ring. The active key signs new cursors while the current and previous key IDs verify during a bounded overlap that is at least the cursor TTL (plus a small clock-skew/rollout buffer). Rotation publishes the new verifier before issuance, then retires the previous key only after the overlap; it must not invalidate active cursors.
- A send key is scoped to one conversation and authenticated Workspace; its digest is never exposed. The same key in another conversation is independent.
- The execution field is additive and nullable (null until a later projection exists). CLD-004 does not invent Foundry state or IDs.
- Alpha treats the new chat tables as a fresh schema boundary. Ordinary foreign keys, uniqueness/check constraints, additive migration validation, and route-level authorization/privacy tests are sufficient; no persisted route switch, readiness state, or custom ancestry validation job is required.

### CLD-004 / CLD-005 ownership boundary

CLD-004 owns the low-level, invariant-enforcing transition primitives and their
tests. `claim_next_turn` is the only implementation of `queued -> in_progress`
and `complete_turn` is the only implementation of
`in_progress -> completed|failed|stopped`; each primitive owns its short
`transaction.atomic()` and `select_for_update()` of the Conversation, enforces
ordering and the one-active-row invariant, and is published as the Cloud
message-lifecycle contract. CLD-004 does not call a provider, enqueue a
gateway request, create an execution, or project runtime state.

CLD-005 owns the caller/orchestration path and external dispatch. Its worker or
gateway adapter calls the published CLD-004 primitives without acquiring or
holding the Conversation lock before or around the call; the primitive is the
sole lock owner and owns the complete short transaction. CLD-005 must not
reimplement either transition, update lifecycle columns directly, or claim a
second active row. CLD-005 supplies terminal evidence to `complete_turn` after
its own reconciliation rules. There is one
implementation and one test owner for each transition: CLD-004 unit and
PostgreSQL invariant tests; CLD-005 orchestration/dispatch and provider-failure
injection tests. The cross-plan contract is intentionally explicit so the two
plans cannot drift.

| Contract seam | CLD-004 publishes and proves | CLD-005 consumes and proves |
| --- | --- | --- |
| `queued -> in_progress` | `claim_next_turn(*, conversation_id)`; its own short `transaction.atomic()` locks Conversation with `select_for_update()`, claims lowest sequence, enforces one active row, and releases one pending slot. | Calls the primitive with no pre-lock and no surrounding Conversation transaction; no duplicate SQL/state transition. |
| `in_progress -> terminal` | `complete_turn(*, message_id, status)`; its own short `transaction.atomic()` locks Conversation with `select_for_update()`, accepts only the active row and allowed terminal states, and preserves ordering. A retry with the same message ID and terminal status returns the unchanged terminal row without a second transition; a different terminal status is a stable conflict. | Supplies reconciled terminal evidence and calls the primitive with no pre-lock or surrounding Conversation transaction; owns provider/runtime failure injection and dispatch retry evidence. |
| External side effects | None; acceptance tests prove no dispatch before commit and projection may remain null/delayed. | Gateway/provider calls, execution creation, projection population, and downstream failure evidence. |

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| backend/chat/services/conversations.py | ensure_default_conversation | ensure_default_conversation(*, ally, greeting, reply) -> Conversation | Persisted Ally; bounded onboarding text; Workspace authority already resolved. | Existing/new default Conversation. | Atomic Ally lock; conditional-default uniqueness; greeting then reply import once; race recovery; no waitlist query. |
| backend/chat/services/conversations.py | retrieve_conversation | retrieve_conversation(*, user, workspace_id, conversation_id=None, ally_id=None, limit=50, cursor=None) -> ConversationRead | PROFILE_READ; exactly one addressing form; limit 1..100; cursor version/scope/expiry valid. | IDs, ordered visible messages, next_cursor. | Explicit Workspace filter; default Ally call reconciles conversation; select_related and bounded message query; privacy-safe unavailable/cursor errors. |
| backend/chat/services/messages.py | accept_message | accept_message(*, user, workspace_id, conversation_id, content, idempotency_key) -> MessageAcceptance | WORKSPACE_WRITE; key 16..128 chars; NFC-normalized trimmed text 1..16,000 chars. | IDs, normalized content, sequence, queued state, nullable execution, replayed flag. | Locks Conversation first; duplicate lookup under that lock happens before any limiter call. Only the lock winner reserves one rate-limit admission with a deterministic HMAC request marker, inserts the row, and commits; if the transaction fails, rollback clears only that deterministic marker and retains the attempted aggregate quota count until the normal window expires (fail closed), never decrementing a shared bucket. A concurrent identical send therefore has one row and one limiter increment; the loser replays without incrementing. Counts only origin=send user rows with status=queued; sequence allocation; no external call. |
| backend/chat/services/messages.py | claim_next_turn | claim_next_turn(*, conversation_id: str) -> Message | CLD-004 primitive; at most one origin=send user row may be in_progress. | The next queued user Message in sequence order, or none. | Owns `transaction.atomic()` plus Conversation `select_for_update()`, atomically changes queued -> in_progress, releases one pending slot, and assigns the active-turn identity. No dispatch/provider call occurs. CLD-005 must call it without pre-locking and must not duplicate it. |
| backend/chat/services/messages.py | complete_turn | complete_turn(*, message_id, status: completed\|failed\|stopped) -> Message | CLD-004 primitive; CLD-005 supplies reconciled terminal evidence and may retry the exact message ID/status after an ambiguous response. | Terminal Message state. | Owns `transaction.atomic()` plus Conversation `select_for_update()`, accepts only the active row and allowed terminal states, and frees the active slot. If already terminal with the same status, returns the unchanged row without changing timestamps or emitting another transition (idempotent retry); if a different terminal status is requested, raises a stable conflict without mutation. CLD-005 must not pre-lock, hold a surrounding Conversation lock, update lifecycle columns directly, or duplicate this implementation. |
| backend/chat/services/messages.py | enforce_send_rate_limit | enforce_send_rate_limit(*, user_id, workspace_id, reservation_key) -> RateLimitReservation | Authenticated, authorized scope; configured count 1..120 and window 60..3600 seconds; reservation key is an HMAC of conversation and send-key digests. | Reservation decision, never serialized publicly. | Extends the existing cache-backed atomic `check_rate_limit(scope="chat-send", identity=f"{workspace_id}:{user_id}", reservation_key=..., limit=30, period=600)` so a deterministic request marker is counted once. The helper owns HMAC/cache-key construction; on surrounding transaction failure it clears only the request marker and retains the attempted aggregate quota count until the normal window expires (fail closed), never decrementing a shared bucket that may have been recreated. New sends over the per-user/workspace limit raise `SendRateLimited`; cache outage fails closed as a safe internal/unavailable error. Replays never call this function. |
| backend/chat/services/messages.py | serialize_cursor / parse_cursor | serialize_cursor(...) -> str; parse_cursor(cursor, conversation_id) -> Cursor | Versioned compact JSON, URL-safe encoding, `key_id`/version, HMAC signature, expiry and conversation scope. New cursors use the active key; verification accepts only the active and bounded-overlap previous keys. | Opaque cursor or typed cursor. | Invalid/tampered/expired/wrong-scope/post-retirement-key cursor raises CursorInvalid without history disclosure; valid old-key cursors remain readable through the overlap. |
| backend/chat/services/messages.py | message_response | message_response(message, execution=None) -> MessageResponse | Allowlisted product fields only. | Public DTO with IDs, role, content, sequence, status, created_at, optional projection. | Never serializes PKs, key digests, fingerprints, credentials, provider errors, or runtime data. |
| backend/allies/services/creation.py | create_ally integration seam | Existing create_ally signature; invoke ensure_default_conversation in its transaction. | Existing CLD-003 validation/idempotency remain authoritative. | Existing AllyCreationResult; conversation durable before create success. | Greeting/reply imported once; replay reuses Ally/conversation. |
| backend/config/api.py | safe unhandled API error path | _unhandled_error(request, exc) -> JsonResponse | Resolve an allowlisted route ID/template (never request.path or query), method, status, and stable exception class or safe error-code fingerprint only; never stringify exception or include traceback/request body. | Existing internal_error envelope. | Logs a bounded safe record and delegates to sanitized wide-event observability; chat DatabaseError/unexpected failures do not leak content. The allowlist fallback is `unknown_route`; no request-derived route text is logged. |

### API and Transport Contracts

| Consumer | Method and path | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Interface | GET /api/v1/workspaces/{workspace_id}/allies/{ally_id}/conversation | Valid session; PROFILE_READ; denied/foreign resources 404. | Query limit 1..100 (default 50), optional opaque cursor. | 200 SuccessResponse[ConversationResponse], newest page first, ascending sequence, next_cursor for older records. | 401 session_invalid; 404 conversation_unavailable; 422 cursor_invalid/invalid limit; 500 internal_error. |
| Interface | GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id} | Valid session; PROFILE_READ; conversation ancestry checked. | Same bounded limit/cursor. | Same ConversationResponse. | Same privacy-safe and validation errors. |
| Interface | POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages | Valid session; WORKSPACE_WRITE; membership rechecked before duplicate lookup. | SendMessageRequest plus Idempotency-Key header (16..128 chars). | 201 new or 200 replay: MessageAcceptanceResponse with queued message, nullable execution, replayed flag. | 401 session_invalid; 404 conversation_unavailable; 409 idempotency_conflict or turn_terminal_conflict; 422 validation_error; 429 domain reason `conversation_queue_full` or `send_rate_limited`; 500 internal_error. Both 429 reasons map to exactly the same public body, headers, logs, and metrics shape for every caller, with no remaining count, identity, key, content, window, `Retry-After`, or timing detail; retry only the exact request/key for replays. |

Representative request:

    {"content": "Help me plan tomorrow's study block."}

Representative new response:

    {"status":"success","message":"Message accepted","data":{"conversation_id":"conv_01J...","message":{"id":"msg_01J...","sender":"user","content":"Help me plan tomorrow's study block.","sequence":3,"status":"queued","created_at":"2026-08-24T20:00:00Z"},"execution":null,"replayed":false}}

Replay returns the same message/execution with replayed true and HTTP 200. Changed-content reuse returns 409 with code idempotency_conflict and does not echo original content. Public errors never include private infrastructure/provider text.

The two domain reasons are retained for aggregate operator counts, but the
public rate-limit response is intentionally indistinguishable across users and
workspaces:

    {"status":"error","message":"Request temporarily unavailable","error":{"code":"rate_limited"}}

The response body and headers contain no counter, remaining allowance, reset
time, workspace/user identity, key material, content, `Retry-After`, or timing.
The rate-limit wide event, log record, and metric sample are aggregate-only:
`schema_version`, event name, allowlisted route ID, method, status `429`, and
reason (`conversation_queue_full` or `send_rate_limited`). They omit duration,
request/correlation IDs, identity, key, content, allowance, reset time, and
all other request-derived fields. Tests inspect the serialized wide event,
log, and metric payload and assert that `duration_ms` and timing fields are
absent. Tests send 31 new messages for one user/workspace (with the default
30-per-600-second window), prove the 31st is a privacy-safe 429, prove that a
different workspace for the same user has an independent allowance, and prove
that a duplicate replay succeeds without consuming either bucket.

If an existing Ally has a missing, invalid, or partially imported CLD-003
greeting/reply, Cloud must not fabricate text, duplicate a partial row, or
report a successful conversation. The handoff returns a typed,
privacy-safe repairable/unavailable outcome (`onboarding_handoff_repair_required`
or `onboarding_handoff_unavailable`, with retryability metadata); GET does not
return a normal success payload and POST is not admitted for that Conversation.
The CLD-003 create transaction rolls back its conversation handoff on this
outcome, leaving the Ally's existing rows untouched. Reconciliation attempts
are idempotent and add no message or pending-capacity row until both source
turns validate. These outcomes are tested for existing Allies and partial
imports.

Queue invariant: a Conversation may have zero or one active send-origin user Message in in_progress, identified by that row's public message ID. It may also have up to 20 send-origin user Messages in queued. The onboarding greeting and reply are completed historical rows and are excluded from this count. A duplicate replay is evaluated before rate and capacity checks and succeeds even when either limit is exhausted. Conversation locking serializes identical key races: the first request performs the single rate-limit reservation/increment and inserts the row; the second sees the committed row and replays without calling the limiter. A new valid send receives 429 send_rate_limited when its authenticated user/workspace scope has reached 30 sends in the configured 10-minute window, or 429 conversation_queue_full when queued count is already 20; neither rejection consumes the idempotency key. PostgreSQL concurrency evidence must assert one row and exactly one limiter increment for identical concurrent sends. CLD-005 calls `claim_next_turn` with no pre-lock or surrounding Conversation transaction; the primitive alone locks Conversation, changes the lowest-sequence queued row to in_progress, and thereby releases one pending slot. Terminal completion of the active row frees the active slot; it never changes the order of queued rows. A retry of `complete_turn` with the same message ID and terminal status returns the unchanged terminal row; a different terminal status is a stable conflict.

### Data shapes and invariants

Keep the categories below distinct. Only the **Database Models** table describes
persisted database models/tables; enums, API schemas, DTOs, temporary signed or
internal structures, projections, and service primitives are not database rows.

#### Database Models

| Type / category | Model / table | Location | Fields and types | Required / nullable / defaults | Validation, indexes, constraints, and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- | --- |
| Persisted model / table | `Conversation` | `backend/chat/models.py` | `public_id`, `ally` FK, `is_default`, timestamps | IDs required/immutable; `is_default=true` for initial direct conversation | Conditional unique Ally where `is_default=true`; Workspace authority is derived from `Ally.workspace`, never duplicated; every lookup joins `Ally.workspace` | New chat migration depends on `allies.0001`; additive, no destructive migration. A future group conversation contract must add its own composite Workspace/participant safeguard rather than duplicate authority. |
| Persisted model / table | `Message` | `backend/chat/models.py` | `public_id`, `conversation` FK, `sequence`, sender user/assistant, origin send/onboarding, content max 16000, status, `send_key_digest`, `content_fingerprint`, timestamps | Send-origin user rows require key/fingerprint and default `queued`; onboarding rows may omit key/fingerprint but require `completed`; assistant greeting is onboarding/completed | Unique conversation/sequence; conditional unique conversation/send key for send-origin user rows; one partial unique conversation active `in_progress` send row; sender/origin/key/status checks; sequence allocated under lock | Onboarding rows are copied once, are historical, and never count toward pending capacity; raw key is never stored. |

#### Enums

| Type / category | Enum | Location | Members / representation | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| Enum (persisted field vocabulary) | `MessageLifecycle` | `backend/chat/models.py` | `queued`, `in_progress`, `completed`, `failed`, `stopped` | One field vocabulary only. Send-origin rows begin `queued`; onboarding greeting and reply are completed history. At most one send-origin user row per Conversation is `in_progress`; only `queued -> in_progress` releases pending capacity; only active `in_progress -> terminal` is allowed. | CLD-004 primitives own claim/terminal transitions and lock/order invariants; CLD-005 calls them without pre-locking or direct lifecycle writes. |

#### API Request Schemas

| Type / category | Request schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| API request schema / DTO | `SendMessageRequest` | `backend/chat/api/schemas.py` | `content: string` | Required; 1..16000 after normalization; extra fields forbidden | NFC + trim; text-only Alpha; no attachment fields. Caller also supplies `Idempotency-Key` 16..128 chars. | Additive route contract through the existing OpenAPI 0.1 envelope. |

#### API Response Schemas

| Type / category | Response schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| API response schema / DTO | `ConversationResponse` | `backend/chat/api/schemas.py` | `id`, `ally_id`, bounded `messages` list, nullable `next_cursor` | `id`, `ally_id`, and `messages` required; `next_cursor` nullable | Messages are ordered by `sequence`; no provider/runtime fields | Additive through existing OpenAPI 0.1 envelope. |
| API response schema / DTO | `MessageAcceptanceResponse` | `backend/chat/api/schemas.py` | `conversation_id`, `message`, nullable `execution`, `replayed: bool` | `execution` nullable; `replayed` required | Message lifecycle is the product truth and starts `queued`; replay returns the original row and current projection | `execution` is populated only by later CLD-005 projection work. |

#### Temporary / Internal Shapes

| Type / category | Shape | Location | Fields and types | Lifetime / visibility | Validation, security, and invariants | Compatibility / rotation notes |
| --- | --- | --- | --- | --- | --- | --- |
| Temporary signed/internal shape | `CursorPayload` | `backend/chat/services/messages.py` | Schema version, key ID/version, conversation public ID, exclusive `before_sequence`, expiry, signature | Temporary signed payload; opaque to clients and never persisted as a model/table row | Signature verifies against active or previous key within the bounded overlap; conversation scope and expiry are checked before history is returned; key ID is not secret and is never sourced from message content | New cursors use the active key. Previous-key verification lasts at least cursor TTL plus bounded skew/rollout buffer, then retired keys reject without invalidating active cursors during overlap. |
| Temporary internal shape | `RateLimitReservation` | `backend/chat/services/messages.py` / existing cache helper | Opaque request marker and decision | Cache/transaction lifetime; never serialized or logged | Marker is a deterministic HMAC of authorized workspace/user scope plus conversation/send-key digests; one concurrent identical send can reserve/count once; rollback clears the marker but retains the attempted aggregate quota count until the normal window expires (fail closed), with no shared-bucket decrement | Cache-helper extension only; no new queue or worker. |

#### Optional Future Projection

| Type / category | Projection | Location | Fields and types | Lifetime / visibility | Validation, security, and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| Optional future projection / response field | `ExecutionProjection` | `backend/chat/api/schemas.py` | Nullable, product-only version/state/reference fields | Optional and `null` in CLD-004; populated later by CLD-005 | Must not contain Foundry/Hermes/Fly/profile/runtime/credential/address identifiers | Additive seam; CLD-005 owns population and downstream compatibility. |

#### Service Primitives

| Type / category | Primitive | Location | Signature | Inputs and validation | Return value | Lock/transaction ownership, side effects, and errors |
| --- | --- | --- | --- | --- | --- | --- |
| Service primitive | `ensure_default_conversation` | `backend/chat/services/conversations.py` | `ensure_default_conversation(*, ally, greeting, reply) -> Conversation` | Persisted Ally; bounded onboarding text; Workspace authority already resolved | Existing/new default Conversation | Atomic Ally lock, conditional-default uniqueness, greeting then reply import once, and race recovery; no waitlist query or external call. |
| Service primitive | `accept_message` | `backend/chat/services/messages.py` | `accept_message(*, user, workspace_id, conversation_id, content, idempotency_key) -> MessageAcceptance` | `WORKSPACE_WRITE`; key 16..128 chars; NFC-normalized trimmed text 1..16000 chars | IDs, normalized content, sequence, queued state, nullable execution, replayed flag | Locks Conversation first; duplicate lookup under that lock precedes limiter admission. Only lock winner reserves one rate-limit admission, inserts, and commits; rollback clears the deterministic request marker but retains the attempted aggregate quota count until the normal window expires (fail closed), with no shared-bucket decrement. No external call. |
| Service primitive | `claim_next_turn` | `backend/chat/services/messages.py` | `claim_next_turn(*, conversation_id: str) -> Message` (or none) | CLD-004 primitive; at most one send-origin user row may be `in_progress` | Lowest-sequence queued user Message, or none | Owns complete short `transaction.atomic()` plus Conversation `select_for_update()` lock; changes `queued -> in_progress` and releases one pending slot. CLD-005 calls it without pre-locking and never duplicates it. |
| Service primitive | `complete_turn` | `backend/chat/services/messages.py` | `complete_turn(*, message_id, status: completed|failed|stopped) -> Message` | CLD-005 supplies reconciled terminal evidence; only active row and allowed terminal states are valid | Terminal Message state | Owns complete short transaction and Conversation lock; same message ID/status retry returns unchanged row without a second transition, different terminal status is a stable conflict without mutation. CLD-005 must not pre-lock, directly update lifecycle columns, or duplicate it. |

### Plain-language glossary

- **Model / table:** a persisted database record shape and the table that stores it.
- **Schema:** a validated boundary shape for input or output; an API schema is not automatically a table.
- **Enum:** a closed list of allowed named values, often stored in a model field.
- **DTO:** a data-transfer object used across a boundary; it may be schema-backed and need not be persisted.
- **Primitive:** a small service operation that owns one state transition or durable boundary.
- **Index:** a database access structure that speeds a known lookup or ordering pattern; it is not a separate model.
- **Constraint:** a database or application rule that rejects invalid combinations or transitions.
- **Invariant:** a condition that must stay true across retries, concurrency, failures, and migrations.

### Frontend Interaction Shapes (if applicable)

Cloud does not implement UI. Interface keeps unsent drafts in client/session state, sends text plus a fresh retry key, treats returned DTOs as product truth, and retries only the identical request after uncertain transport. It maps the single lifecycle enum to copy and never calls Foundry. Loading, empty, permission, retry, and failure presentation remain Interface-owned.

## Phases

### Phase 1 - Chat domain and migration

- Goal: establish durable ownership and database invariants before routes.
- Work items: run make app NAME=chat; add chat to INSTALLED_APPS and explicit registrar; add IDs, lifecycle choices, Conversation, and Message models with foreign keys, uniqueness/check constraints, and indexes; generate migration with make migrations APP=chat MIGRATION_NAME=conversation_message; inspect generated migration; add model tests for the constraints and migration behavior.
- Impacted files/systems: backend/chat/**; backend/config/settings.py; backend/config/api.py (safe unhandled-error logging); generated chat migration.
- Exit criteria: migration applies on SQLite/PostgreSQL; make check; targeted chat model tests; no registration/import errors.

### Phase 2 - Onboarding handoff and conversation reads

- Goal: make every Ally resolve to one conversation and expose bounded authorized history.
- Work items: implement locked idempotent ensure_default_conversation with conditional uniqueness race recovery; invoke from CLD-003 create and default Ally retrieval for lazy existing-row reconciliation; return typed repairable/unavailable outcomes for missing, invalid, or partial CLD-003 handoffs without fabricating or duplicating messages; implement select_related read DTOs and a versioned HMAC cursor signed by the active key ID; add GET schemas/controllers/OpenAPI examples; test repeated/concurrent lookup, greeting/reply order, partial-import no-op/capacity behavior, cursor tamper/expiry, empty history, and foreign 404. Define the cursor key-ring rollout: deploy verification for the new key before switching issuance, accept the previous key for at least the cursor TTL plus bounded skew/rollout buffer, issue only the active key, and retire the previous key only after that window.
- Impacted files/systems: chat services, schemas, controllers, registrar, allies/services/creation.py, config/api.py, chat tests.
- Exit criteria: one conversation under concurrent lookup; valid onboarding order at most once; malformed/partial existing handoffs return typed repairable/unavailable outcomes with no new rows or capacity impact; bounded pages and cursors pass; old-key cursors remain accepted during the overlap, new cursors carry the active key ID, post-window old-key cursors are rejected, and no private identifiers appear in DTOs.

### Phase 3 - Exactly-once text acceptance and queue boundary

- Goal: durably accept one user intent per caller key with deterministic ordering and bounded pending work.
- Work items: implement NFC/trim normalization, HMAC key digest/fingerprint, Conversation lock, duplicate-before-queue, deterministic rate-limit reservation with rollback marker clearing (retain attempted aggregate count until the normal window expires; fail closed; never decrement a shared bucket), the per-user/workspace cache-backed send limiter (30 new sends per 600 seconds by default, configurable 1..120 and 60..3600), 20-pending admission, sequence allocation, commit-before-success; implement and test the published CLD-004 `claim_next_turn` and `complete_turn` primitives and their transition guards; add POST schema/controller and status mapping (201 new, 200 replay, 409 conflict, 422 invalid, 429 domain reasons `conversation_queue_full`/`send_rate_limited` mapped to one generic envelope); include nullable execution seam; test valid/invalid text, replay/conflict, auth recheck, privacy-safe 429 bodies, headers, aggregate wide events/logs/metrics with timing suppressed, independent workspace buckets, ordering, queue, separate Allies, concurrent same-key replay with one limiter increment, failed-transaction marker clearing with retained aggregate count through window expiry, idempotent same-status `complete_turn` retries, conflicting terminal retries, and that CLD-005 is the only caller/orchestration owner and cannot pre-lock or bypass the primitives.
- Impacted files/systems: chat message service/API/exceptions/tests; config API contract tests; observability tests/config tests for the shared error path.
- Exit criteria: same key converges to one row; conflict unchanged; concurrent sequences unique/deterministic; full queue and per-user/workspace rate limits reject only new requests with privacy-safe generic 429s; CLD-004 transition tests prove queued -> in_progress and active -> terminal invariants plus idempotent same-status terminal retry; CLD-005 call-site contract is explicit with no pre-lock or duplicate implementation; public DTOs product-only.

### Phase 4 - Verification, contract handoff, and release evidence

- Goal: prove migration, authorization, privacy, concurrency, and compatibility.
- Work items: run focused chat and PostgreSQL tests; inspect migration/OpenAPI; run repository checks, format/lint, full pytest, git diff --check; exercise the exact safe generic API logging contract through malformed JSON and DatabaseError in both the chat wrapper and existing global handler; update current config tests and observability tests; verify foreign keys, uniqueness/check constraints, and fresh SQLite/PostgreSQL migrations; prove route-level authorization/privacy behavior for mismatched and foreign resources; coordinate Interface and CLD-005/006 seam without adding Foundry calls.
- Impacted files/systems: chat tests/docs, config/tests/test_api_contract.py, OpenAPI, CI PostgreSQL job.
- Exit criteria: every CLD-004 criterion has named evidence; durability is proven while execution projection is null/delayed (no CLD-004 external failure injection claim); CLD-005 is named as owner of downstream failure-injection evidence for the broader EPIC criterion; no migration drift; tenant-isolation negatives, database constraint tests, and route-level authorization/privacy tests pass; Interface contract reviewed.

## Acceptance Criteria

1. Repeated/concurrent Ally access resolves to one default conversation; the database prevents two default rows.
2. No Ally has two initial conversations; existing CLD-003 rows reconcile lazily without waitlist reads.
3. Greeting then reply appear once before later messages.
4. Valid normalized text creates one durable queued user message with stable IDs and deterministic sequence; success follows commit.
5. Accepted messages remain durable and visible while execution projection is null or delayed; CLD-004 proves commit-before-success and projection absence/delay only. CLD-005 owns the external-dispatch failure-injection evidence required to extend this to the broader EPIC downstream-failure criterion.
6. Same conversation key and normalized content replay the original message/projection without duplicate work intent.
7. Changed-content key reuse returns stable 409 and leaves original unchanged.
8. Invalid/oversized/attachment-shaped input creates no message or accepted work.
9. Concurrent sends serialize sequence allocation without duplicate positions; at most one send-origin user row is in_progress for a Conversation.
10. Later valid sends enter queued order behind the active turn, up to 20 pending rows; CLD-005 promotion queued -> in_progress releases one slot, terminal active transitions free the active slot, and full queue rejects only the new send.
11. User and assistant roles expose one truthful lifecycle status from the shared enum. The CLD-003 imported user reply is origin onboarding, completed, ordered after the completed assistant greeting, and excluded from pending capacity.
12. Every protected read/send/replay/cursor parse rechecks Workspace authority; foreign denial reveals no existence.
13. Public responses and diagnostics contain no private provider/runtime identifiers. Generic API failures use an allowlisted route resolver (route ID/template, never `request.path` or query), plus method/status and a stable exception class or safe error-code fingerprint only; exception strings, tracebacks, request bodies, Idempotency-Key material, SQL, provider text, and raw paths/queries are absent. Malformed JSON and `DatabaseError` are covered through both the chat wrapper and the existing global handler, including current config and observability regression tests.
14. Interface uses conversation IDs for message operations and Ally IDs only for default resolution.
15. History defaults to 50/max 100 and older pages use opaque versioned conversation-scoped cursors.
16. Cursor payloads carry a key ID/version; new cursors use the active key, the previous key remains accepted for at least the cursor TTL plus bounded skew/rollout buffer, and post-window retirement rejects old-key cursors. Rotation tests prove old-key acceptance, new-key issuance, and post-window rejection without invalidating active cursors during the overlap.
17. Alpha contract is text-only; attachment semantics remain Beta.
18. Migration, API, authorization, idempotency, concurrency, queue-transition, history, cursor-rotation, logging, database-constraint, onboarding-repair, and contract evidence is recorded before completion. Foreign keys and uniqueness/check constraints prevent normal orphan or duplicate ancestry, migration validation runs on SQLite/PostgreSQL, and route-level mismatched Workspace and foreign Conversation/Ally IDs return privacy-safe 404s.
19. The POST contract names both domain reasons, `conversation_queue_full` and `send_rate_limited`, while mapping both to the exact generic HTTP 429 body `{"status":"error","message":"Request temporarily unavailable","error":{"code":"rate_limited"}}`; no reason, remaining count, reset time, `Retry-After`, identity, key, content, or timing detail appears in body, headers, logs, metrics, or rate-limit wide events. Rate-limit events/logs/metrics contain only aggregate allowlisted fields and suppress duration.
20. PostgreSQL concurrent identical sends serialize under the Conversation lock and assert one Message row, one successful request-marker/limiter increment, and a replay response for the loser. A transaction failure clears only the deterministic request marker while retaining the attempted aggregate quota count until the normal window expires (fail closed); it never decrements a shared bucket or claims zero residual count.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots: default conversation lookup, history read, duplicate send lookup, bounded queue count.
- Choices: explicit Workspace filters through Conversation.ally.workspace; select_related ally and ally.workspace; one bounded message query ordered by sequence; indexes on conversation/sequence and conversation/send digest; short row locks only for create/accept.
- Expected change: one membership/resource query plus one bounded message query for reads; one short transaction for sends; no per-message relation access.
- Measurement: focused ordering/limit tests; CaptureQueriesContext only if measured regression appears. Verify malformed input and injected database failures use route-template/error-type logging only.

### N+1 Prevention

- Relation map: Conversation to Ally to Workspace joined; Conversation has no duplicated Workspace column; messages fetched once bounded; DTOs use loaded fields.
- select_related for singular ancestry; no unbounded prefetch; send loads only locked conversation and key row.
- Guardrail: add a focused query-shape test only if a reusable query boundary is introduced; no generic repository layer. Conversation derives Workspace solely through `Ally.workspace` and database foreign keys prevent normal orphan rows. Route-level tests pass a Workspace ID that does not match Ally.workspace and foreign Conversation/Ally IDs, asserting privacy-safe 404s. Migration tests cover constraint creation and fresh SQLite/PostgreSQL application; no duplicated Workspace field or separate reconciliation destination is introduced.

### Detailed Unit Test Cases

- Happy path: create/retrieve conversation; greeting/reply import; newest page; valid send returns 201 queued.
- Validation: missing/short/long key, blank/long text, invalid cursor, extra JSON, attachment-like fields, full queue; rejection creates no message/key acceptance.
- Auth: missing session, inactive membership, wrong Workspace, wrong Ally/conversation, duplicate key from wrong Workspace; safe 401/404.
- Idempotency: same key/content returns 200 replay; NFC/whitespace-equivalent content replays; changed content 409; another conversation independent.
- Failure: database uniqueness race recovery; cursor tamper/expiry and key rotation (old-key acceptance during overlap, active-key issuance, post-window rejection); rollback after insert failure; queue saturation preserves accepted rows; no external dispatch before commit; missing/invalid/partial CLD-003 handoff returns typed repairable/unavailable without fabrication, duplication, success, or capacity impact.
- State/order: sequence uniqueness, onboarding order, imported user reply is completed/origin=onboarding and excluded from capacity, one active in_progress send row, queued -> in_progress release, terminal transition, idempotent same-status `complete_turn` retry and conflicting-status rejection, bounded pages, separate histories, assistant rows without send keys.
- Rate limiting: exercise 31 new sends for one user/workspace against the default 30-per-600-second window; assert the 31st is the same generic 429 envelope for every caller, with no remaining count/reset/identity/key/content/`Retry-After`/timing detail in body or headers; assert both domain reasons (`conversation_queue_full` and `send_rate_limited`) map to that exact envelope; inspect wide-event JSON, log, and metric payloads for the aggregate allowlist (`schema_version`, event, route ID, method, status, reason) and assert no `duration_ms`, request/correlation IDs, identity, key, content, allowance, reset, or timing fields; verify another workspace has an independent bucket, cache outage fails closed, and duplicate replay does not consume allowance.
- Concurrent idempotency: use a PostgreSQL barrier with two identical sends; assert one Message row, one successful deterministic request-marker/limiter increment, one replay response, and no second limiter call. Force an insert/commit failure and assert rollback clears the request marker but retains the attempted aggregate quota count until the normal window expires (fail closed); do not decrement the shared bucket, and verify replays still bypass the limiter.
- Privacy logging: caplog tests for malformed JSON and `DatabaseError` through both the chat wrapper and the existing global handler (plus current config and observability test suites) assert that only the allowlisted route ID/template, method/status, stable exception class or safe error-code fingerprint, and non-content correlation metadata remain. `request.path`, query, exception string, traceback, request body, Idempotency-Key, SQL, provider text, and raw paths are absent.
- Boundary authorization/privacy: exercise route-level Workspace mismatch and foreign Conversation/Ally IDs and prove every read/send is a privacy-safe 404; assert database foreign keys and uniqueness/check constraints reject invalid ancestry and duplicate default/sequence/lifecycle rows on both SQLite and PostgreSQL.
- Onboarding edge: existing Allies with missing/invalid greeting/reply or partial import return typed `onboarding_handoff_repair_required` / `onboarding_handoff_unavailable`; repeated repair attempts do not fabricate, duplicate messages, consume pending capacity, or report success.

## Frontend Considerations (if applicable)

### Data Path

- User action: Interface opens Ally or sends composer text.
- Client route: Interface-owned conversation screen/draft state; unchanged here.
- API: Cloud GET default/history, then POST message with Idempotency-Key.
- Backend: chat controllers call authorization-scoped services.
- Mapping: DTO role/content/sequence/status is truth; execution nullable/later-owned; replayed is retry telemetry.
- Error/retry: keep draft on validation/network failure; retry exact key/content after uncertain transport; map 401/404/409/422/429 to product copy; never display infrastructure.

### State Management Considerations

- Draft/transport client-owned; accepted messages/history Cloud-owned; execution later Cloud-owned.
- API DTOs are source of truth; UI derives copy/loading.
- Cache by conversation ID; merge sends and append older cursor pages in sequence order.
- Fresh key per intent; reuse only retries; do not infer acceptance from disconnect.

## Test Plan

- Unit: backend/chat/tests/test_models.py and test_services.py.
- Integration/API: backend/chat/tests/test_api.py and config/tests/test_api_contract.py for envelopes, status codes, schemas, auth, pagination, replay, conflict, privacy, and typed onboarding-repair outcomes.
- Regression: existing Allies create/retrieve/replay tests continue; CLD-003 now creates/reuses one conversation; no waitlist import.
- PostgreSQL: pytest -m postgresql chat/tests/test_concurrency.py for first-access race, same-key convergence, ordered different-key sends, and queue saturation.
- Manual: fresh migration; create Ally; retrieve twice; verify greeting/reply; exercise an existing partial/malformed CLD-003 handoff and confirm typed repairable/unavailable with no new rows/capacity; send/retry; changed key; foreign Workspace; older pages; inspect JSON/logs for private fields; disconnect/reload; verify migration constraints and route-level authorization/privacy behavior.
- Commands:
  - make app NAME=chat (only for initial scaffold)
  - make migrations APP=chat MIGRATION_NAME=conversation_message
  - make check
  - make lint
  - make test APP=chat
  - cd backend; uv run pytest -m postgresql chat/tests/test_concurrency.py with PostgreSQL DATABASE_URL (including CLD-004 transition primitives and CLD-005 call-site lock contract)
  - cd backend; uv run pytest --cov=chat (report coverage; no new repository threshold beyond existing CI gates)
  - cd backend; uv run pytest
  - git diff --check
  - cd backend; uv run pytest config/tests/test_api_contract.py config/tests/test_middleware.py observability/tests/test_middleware.py (safe handler/config/observability redaction regressions)
  - cd backend; uv run python manage.py migrate --check (migration state and constraint drift)
  - CI-equivalent migration --noinput, migrate --check, and ruff format --check

## Risks and Mitigations

- Duplicate conversations/turns: Ally lock, conditional default uniqueness, deterministic import, database uniqueness race recovery, PostgreSQL race tests. Fallback: stop new admission while accepted rows remain authoritative.
- Idempotency scope/leakage: authorize before key lookup, HMAC digest, content fingerprint, conditional uniqueness, conflict tests. Fallback: disable sends; never rewrite accepted keys.
- Queue/order loss: conversation lock, bounded count, unique sequence, reject only new request, concurrency tests. Fallback: stop new admission while CLD-005 drains queued rows.
- Queue semantics drift: CLD-004 owns the sole `claim_next_turn` and `complete_turn` implementations and their invariant tests; pending means send-origin user rows in queued, active means the single send-origin user row in in_progress, onboarding rows are excluded, and CLD-005 orchestration must call those primitives without pre-locking because each primitive owns the Conversation lock. Fallback: stop admission until the transition invariant check and CLD-005 call-site contract pass.
- Misleading execution state: one enum starting queued, nullable projection, explicit CLD-005/006 boundary, forbidden-field contract tests. Fallback: return execution null.
- Imported reply treated as pending work: mark the CLD-003 user reply origin=onboarding and completed at sequence 2 with no caller key; test that it never counts toward queue or active-turn capacity. Fallback: reconcile historical rows before enabling sends.
- Cursor tamper/expiry/skips and rotation invalidation: signed versioned cursor with key ID/version, exclusive sequence and scope; verify active plus previous keys for at least the cursor TTL and bounded rollout buffer, issue only the active key, and reject retired keys after the window. Fallback: revert issuance to the previous key while both verify; if the window has ended, require a fresh first page; history remains intact.
- CLD-003 import coupling: narrow service seam, no signals/external calls, regression tests. Fallback: disable create hook while lazy reconciliation remains.
- Provider/runtime leakage: allowlisted DTOs, redacted diagnostics, OpenAPI inspection. Fallback: remove projection and return null.
- Generic exception leakage: change the chat wrapper and existing global handler so failures resolve an allowlisted route ID/template (never `request.path`/query) and log only method/status plus a stable exception class or safe error-code fingerprint and non-content correlation metadata; never request content, Idempotency-Key material, SQL, provider text, exception strings, or traceback. Caplog/config/observability tests cover malformed JSON and `DatabaseError` through both paths. Fallback: disable routes and preserve only a content-free correlation ID.
- Conversation/Ally Workspace mismatch: derive Workspace through Ally.workspace and rely on database foreign keys for normal ancestry; route-level mismatched Workspace/foreign-resource requests return privacy-safe 404s. Migration and constraint tests cover fresh schema creation on SQLite/PostgreSQL. Fallback: stop new admission while accepted rows remain authoritative.
- Missing or partial CLD-003 handoff: no fabricated greeting/reply, duplicate import, or success response. Return typed repairable/unavailable outcome; preserve existing rows and do not consume message capacity. Fallback: keep the Ally conversation unavailable until repair evidence exists.
- CLD-004/CLD-005 ownership drift: do not add a second transition implementation in CLD-005; require its orchestration tests to call the CLD-004 primitives with no pre-lock or surrounding Conversation transaction, because each primitive is the sole lock owner. Fallback: block CLD-005 dispatch until the published contract and call-site evidence are present.
- Send-rate privacy, bucket drift, or duplicate increments: hold the Conversation lock across duplicate lookup and the single deterministic reservation call; extend the existing cache helper with request-marker idempotency and rollback marker clearing that retains the attempted aggregate quota count until the normal window expires (fail closed), never decrementing a shared bucket that may have been recreated; prove identical concurrent sends yield one row and one increment, independent workspace buckets, fail-closed cache outage, duplicate replay bypass, failed-transaction marker clearing with retained count, and the exact generic 429 body/headers plus aggregate-only wide-event/log/metric payloads with duration suppressed. Fallback: disable POST admission while accepted rows remain authoritative.
- Downstream failure evidence gap: CLD-004 cannot dispatch externally and therefore cannot prove a provider failure. Its exit evidence is durability while execution projection is null/delayed; CLD-005 owns downstream failure-injection evidence for the broader EPIC criterion. Fallback: do not claim the broader EPIC acceptance from CLD-004 alone.
- Migration/existing rows: additive migration, lazy bounded reconciliation, nullable reply handling, SQLite/PostgreSQL checks. Fallback: disable route, retain data.

## Rollout and Fallback

1. Apply the additive chat migration in staging; verify a fresh PostgreSQL migration, `migrate --check`, and the database foreign-key, uniqueness, and check constraints. Register the routes normally after focused migration and authorization/privacy checks pass.
2. Deploy cursor verification with both the current signing key and the next key's verifier available, while issuance still uses the current key; record the cursor TTL and overlap window (at least TTL plus bounded skew/rollout buffer).
3. Switch the active signing key for new cursors only after the verifier is deployed; monitor old-key acceptance and new-key issuance without logging cursor contents.
4. Keep the previous verifier until every cursor signed by it is outside the TTL/overlap window, then retire it and confirm post-window old-key rejection. If the new key is faulty, roll issuance back to the previous key while both verifiers remain active; never delete or rewrite cursor/history data.
5. Deploy after focused model, migration, CLD-003 regression, cursor-rotation, authorization/privacy, and PostgreSQL checks pass; no persisted route switch or preflight ancestry job is part of Alpha rollout.
6. Coordinate Interface contract consumption and keep CLD-005/006 behind separate reviewed plans. CLD-005 must call the CLD-004 transition primitives with no pre-lock or surrounding Conversation transaction; each primitive owns the short transaction and Conversation lock, while CLD-005 owns external dispatch and downstream failure-injection evidence.
7. On failure or operator rollback, stop new admission or revert the application deployment while leaving accepted conversation/message rows and additive migration data intact; an execution projection may remain null/delayed until CLD-005 reconciliation.

## Decisions And Open Questions

- Decided: dedicated chat app; one conditional-default conversation per Ally; conversation ID is message-operation boundary.
- Decided: conversation-scoped HMAC send key and normalized-content fingerprint; duplicate checks after current authorization.
- Decided: one lifecycle enum starts accepted user messages at queued; no accepted status.
- Decided: pending queue is 20 queued send-origin user rows (configurable 1..100), with at most one active send-origin in_progress row; CLD-005 promotion releases capacity. Imported onboarding rows are completed history and do not count.
- Decided: history default 50/max 100, opaque HMAC cursor with schema version, key ID/version, expiry, conversation scope, and exclusive sequence. New cursors use the active key; the previous key remains accepted for at least the cursor TTL plus bounded rollout buffer, then is retired and rejected. Rotation is additive and must not invalidate active cursors during the overlap.
- Decided: Conversation derives Workspace through Ally.workspace instead of duplicating a Workspace FK, providing a database-level single authority for direct conversation ancestry.
- Decided: CLD-004 owns the sole low-level `queued -> in_progress` and `in_progress -> terminal` primitives plus invariant tests; each primitive owns its short transaction and Conversation lock. CLD-005 owns orchestration/caller/dispatch and must call those primitives with no pre-lock or surrounding Conversation transaction, with no duplicate implementation.
- Decided: the default send limiter allows 30 new sends per authenticated user/workspace scope per rolling 600 seconds (configurable within 1..120 and 60..3600); the existing cache helper owns HMAC/key construction, replays bypass the counter, cache failures fail closed, and 429 responses/logs/metrics are generic and content/identity/timing-free.
- Decided: identical sends serialize on the Conversation lock. Duplicate lookup precedes the limiter; the winner uses one deterministic HMAC request marker and the existing cache helper's idempotent marker/count operation, while the loser replays without a limiter call. On transaction failure, rollback clears only the request marker and retains the attempted aggregate quota count until the normal window expires (fail closed), never decrementing a shared bucket. PostgreSQL proves one row and exactly one increment for the race.
- Decided: CLD-004 acceptance proves durability while execution projection is null/delayed and does not claim downstream failure injection; CLD-005 owns provider/downstream failure-injection evidence for the broader EPIC criterion.
- Decided: generic API exception logging resolves an allowlisted route ID/template (never request.path/query) and records only method/status plus stable exception class or safe error-code fingerprint and non-content correlation metadata; no traceback, exception string, request body, Idempotency-Key, SQL, provider data, or raw route text. Malformed JSON and DatabaseError are tested through both chat wrapper and existing global handler, with config/observability regressions.
- Decided: Conversation ancestry uses Ally.workspace and database foreign keys; uniqueness/check constraints and migration validation are sufficient for the new Alpha chat tables. Route-level mismatched Workspace/foreign-resource requests remain privacy-safe 404s; no custom ancestry validation job, persisted route switch, report, readiness state, or quarantine destination/model is introduced.
- Decided: rate-limit observability is aggregate-only. The wide event, log, and metric payload contain schema version, event, allowlisted route ID, method, status 429, and one of `conversation_queue_full` or `send_rate_limited`; they suppress duration and omit request/correlation IDs, identity, key, content, allowance, reset time, `Retry-After`, and other request-derived fields.
- Decided: missing/invalid/partial CLD-003 greeting/reply yields typed repairable/unavailable outcome; no fabricated or duplicate message, success response, or pending-capacity impact.
- Decided: Alpha text-only; no attachment field.
- Decided: `complete_turn` retries with the same message ID and terminal status are idempotent no-ops that return the unchanged row; a different terminal status is a stable conflict without mutation. No new worker/outbox/gateway/event system; commit-before-return leaves CLD-005 seam.
- Open but non-blocking: exact controller module split, safe ExecutionProjection field names, cursor TTL default, and the exact clock-skew/rollout buffer value. These cannot weaken the active/previous key overlap, post-window rejection, ownership, privacy, state, idempotency, queue, or history contracts.

## Revision and Evidence Notes

This plan preserves the CLD-004 specification and records implementation choices left open by that specification: routes, schemas, page limits, cursor shape and key-rotation rollout, queue/active-turn transitions, onboarding-origin and partial-handoff treatment, model/index strategy, privacy-safe error logging, database constraints, route-level authorization/privacy tests, and test commands. The final user revision removes the proposed custom ancestry validation job and persisted route switch because Alpha's new chat tables are protected by ordinary foreign keys, uniqueness/check constraints, migration validation, and route-level authorization/privacy coverage. CLD-004 owns the low-level transition primitives/tests while CLD-005 owns orchestration/dispatch and must call them; CLD-004 proves durability with a null/delayed projection and names CLD-005 for downstream failure injection; malformed/partial CLD-003 handoffs return typed repairable/unavailable outcomes without fabrication, duplication, success, or capacity impact. It does not implement code or mutate Nabu. The HTML companion must be generated from this final Markdown and retain every contract, phase, acceptance criterion, test, risk, and open decision.
