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

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `ResourceResponse` | `app/schemas.py` | `id: UUID`, `name: str` | `id` required | Name is trimmed and non-empty | Additive field; existing clients remain compatible |

Cover request/response DTOs, database model or migration changes, frontend view
models, cache entries, feature-flag payloads, and third-party payload mappings
when they are in scope.

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
