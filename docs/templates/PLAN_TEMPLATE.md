# <Feature Name> Plan

## Feature Overview

- Problem:
- Target users:
- Source docs/specs:
- Success outcome:

## User Stories

1. As a `<user type>`, I want `<capability>`, so that `<outcome>`.
2. As a `<user type>`, I want `<edge/failure handling>`, so that `<safe outcome>`.
3. As an `<operator/admin>`, I want `<operational capability>`, so that `<maintainability outcome>`.

## Scope

### In Scope

-

### Out of Scope

-

### Dependencies and Assumptions

-

## Contract and Shape Definitions

Document every interface this plan introduces or changes. Use the language and
types used by the affected codebase. Mark a subsection `Not applicable` only
when the plan genuinely has no change of that kind; do not leave it blank.

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `path/to/file` | `functionName` | `function functionName(input: Input): Promise<Output>` | `Input` fields and constraints | `Output` shape | Writes, events, and thrown/returned errors |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Web client | `POST /api/v1/resource` | Required role or permission | `CreateResourceRequest` | `SuccessResponse<ResourceResponse>` | `400`, `401`, `403`, `422`, `500`; retry rule |

Include a representative JSON request and response for every changed HTTP API,
webhook, queue message, or streamed event. State pagination, filtering,
idempotency, versioning, and backwards-compatibility behavior where relevant.

### Data Shapes and Invariants

Keep these categories separate. The `Type / category` column is intentional:
only the **Database Models** table describes persisted database tables. Do not
describe an enum, API schema, DTO, cache helper, signed payload, projection,
or service primitive as a database row.

#### Database Models

| Type / category | Model / table | Location | Fields and types | Required / nullable / defaults | Validation, indexes, constraints, and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- | --- |
| Persisted model / table | `Resource` | `app/models.py` | `id: UUID`, `name: str` | `id` required; `name` non-null | Name is trimmed and non-empty; list indexes and database constraints are named | Additive migration; existing rows and clients remain compatible |

#### Enums

| Type / category | Enum | Location | Members / representation | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| Enum (persisted field vocabulary) | `ResourceStatus` | `app/models.py` | `active`, `archived` | Only listed values are accepted; transitions are explicit | Additive members require a compatibility decision |

#### API Request Schemas

| Type / category | Request schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| API request schema / DTO | `CreateResourceRequest` | `app/schemas.py` | `name: str` | Required, non-null | Trimmed, bounded, and rejects unknown fields | Additive versioned request contract |

#### API Response Schemas

| Type / category | Response schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| API response schema / DTO | `ResourceResponse` | `app/schemas.py` | `id: UUID`, `name: str` | `id` required; no nullable fields unless stated | Product-safe fields only; stable ordering/pagination rules where applicable | Additive field; existing clients remain compatible |

#### Temporary / Internal Shapes

| Type / category | Shape | Location | Fields and types | Lifetime / visibility | Validation, security, and invariants | Compatibility / rotation notes |
| --- | --- | --- | --- | --- | --- | --- |
| Temporary/internal shape | `CursorPayload` | `app/services.py` | Signed cursor fields | Temporary; opaque to clients and never persisted as a model row | Signature, scope, expiry, and key-rotation overlap are checked | Active/previous key window and retirement behavior are explicit |
| Temporary/internal shape | `RateLimitReservation` | `app/services.py` | Opaque reservation token and decision | Cache/transaction lifetime; never serialized or logged | Idempotent reservation and rollback reconciliation | Reuses the existing limiter contract; no new queue/worker unless justified |
| Optional future projection | `ExecutionProjection` | `app/schemas.py` | Product-only execution version/state/reference | Optional and nullable; populated by a later owner | Must not expose private provider/runtime identifiers; null behavior is specified for this plan | Additive seam; population and compatibility are owned by the downstream plan |

#### Service Primitives

| Type / category | Primitive | Location | Signature | Inputs and validation | Return value | Lock/transaction ownership, side effects, and errors |
| --- | --- | --- | --- | --- | --- | --- |
| Service primitive | `ensure_default_conversation` | `app/services/conversations.py` | `ensure_default_conversation(...) -> Conversation` | Authorized persisted owner and bounded handoff data | Persisted model instance | Owns its transaction/lock and idempotent race recovery; no external call |
| Service primitive | `accept_message` | `app/services/messages.py` | `accept_message(...) -> MessageAcceptance` | Authorized scope, normalized bounded content, caller idempotency key | Persisted acceptance DTO/result | Owns duplicate-before-admission, transaction, and commit-before-success behavior |
| Service primitive | `claim_next_turn` | `app/services/messages.py` | `claim_next_turn(...) -> Message \| None` | Conversation with queued work | Claimed persisted message or none | Sole owner of the short transaction and conversation lock for queued → active; no provider call |
| Service primitive | `complete_turn` | `app/services/messages.py` | `complete_turn(...) -> Message` | Active message plus allowed terminal state | Terminal persisted message | Sole owner of the short transaction and conversation lock for active → terminal; same-status retry is idempotent and conflicting status is a stable error |

### Plain-language glossary

- **Model / table:** a persisted database record shape and the table that stores it.
- **Schema:** a validated boundary shape for input or output; an API schema is not automatically a table.
- **Enum:** a closed list of allowed named values, often stored in a model field.
- **DTO:** a data-transfer object used to carry data across a boundary; it may be backed by a schema and need not be persisted.
- **Primitive:** a small service operation that owns one state transition or durable boundary.
- **Index:** a database access structure that speeds a known lookup or ordering pattern; it is not a separate domain model.
- **Constraint:** a database or application rule that rejects invalid combinations or transitions.
- **Invariant:** a condition that must remain true across retries, concurrency, failures, and migrations.

Cover request/response DTOs, database model or migration changes, frontend view
models, cache entries, feature-flag payloads, and third-party payload mappings
when they are in scope. If a category is genuinely unchanged, keep its heading
and write `Not applicable` with a reason rather than leaving the section blank.

### Frontend Interaction Shapes (if applicable)

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| `ResourceForm` | `submit(values: ResourceFormValues): Promise<void>` | `idle -> submitting -> success \| error` | Form values -> `CreateResourceRequest` -> view model | Concrete UI states and recovery action |

## Phases

### Phase 1 - <Name>

- Goal:
- Work items:
- Impacted files/systems:
- Exit criteria:

### Phase 2 - <Name>

- Goal:
- Work items:
- Impacted files/systems:
- Exit criteria:

## Acceptance Criteria

1.
2.
3.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots/endpoints:
- Query-shape choices (`select_related`, `prefetch_related`, aggregates, pagination):
- Expected query-count change:
- Measurement/monitoring plan:

### N+1 Prevention

- Relation access map:
- Prefetch/select plan per endpoint/service:
- N+1 regression guardrails:

### Detailed Unit Test Cases

- Happy path:
- Validation and bad input:
- Auth/RBAC boundaries:
- Idempotency/retry behavior:
- Failure-path behavior:

## Frontend Considerations (if applicable)

### Data Path

- User action entry:
- Client route/component:
- Client API route/proxy:
- Backend endpoint:
- Response -> UI model mapping:
- Error/loading/retry path:

### State Management Considerations

- State ownership by layer (local/hook/context/store):
- Source of truth vs derived state:
- Caching/invalidation approach:
- Concurrency and dedupe handling:

## Test Plan

- Unit tests:
- Integration/API tests:
- Regression checks:
- Manual verification checklist:
- Commands:

## Risks and Mitigations

- Risk:
- Mitigation:
- Rollback/fallback:
