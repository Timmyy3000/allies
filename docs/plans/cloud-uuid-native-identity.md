# Cloud UUID-Native Identity Foundation Plan

## Feature Overview

- Problem: Cloud currently mixes integer primary keys with prefixed string `public_id` values. Both forms appear in relations, APIs, authentication, storage, migrations, admin, observability, and tests. Cloud needs one stable UUID identity model.
- Target users: Allies customers' and waitlist applicants' identifiers must remain private, stable, and consistently validated. Operators need a safe one-time reset that preserves production waitlist business data.
- Source docs/specs: Accepted Nabu Cloud UUID-native identity decision; `.agent/cloud-uuid-identity-kickoff.md`; repository `AGENTS.md`, `ENGINEERING_STYLE.md`, README/Makefile/CI/test conventions, current models/migrations/APIs/tests, and `docs/templates/PLAN_TEMPLATE.md`.
- Success outcome: All 18 Cloud product models use UUID primary keys and UUID foreign keys. No prefixed-ID layer remains. A fresh baseline builds cleanly, and verified production waitlist business data survives export, clean schema rebuild, UUID restore, checksum, and API verification.

## User Stories

1. As a Cloud API consumer, I want every product identifier to be a canonical UUID, so request, response, token, cursor, and storage identity have one unambiguous representation.
2. As a waitlist applicant, I want my existing business record preserved through the schema reset, so the foundation refactor does not lose, duplicate, or reinterpret my submission.
3. As an operator, I want an owner-approved reset runbook with verified export/restore evidence, so production can move to a clean UUID schema without relying on reversible non-waitlist data.

## Scope

### In Scope

- Convert all 18 explicit Cloud models to `UUIDField(primary_key=True, default=uuid.uuid4, editable=False)` or the repository-equivalent: `User`, `ExternalIdentity`, `UserProfile`, `AuthFlow`, `NativeAuthorizationTransaction`, `NativeExchangeCode`, `SessionFamily`, `RefreshToken`, `AvatarAsset`, `Workspace`, `Membership`, `Ally`, `AllyBinding`, `OnboardingAttempt`, `ProvisioningOperation`, `Conversation`, `Message`, and `WaitlistEntry`.
- Update every foreign key, one-to-one field, implicit many-to-many/through relation, Django content-type/admin/session relation, and test database relation so it is type-compatible with its UUID owner.
- Remove every `public_id` field, prefix generator, prefix validator/parser, lookup, ordering clause, index, admin field, fixture value, compatibility shim, and `common.identifiers` use; remove the helper module when no callers remain.
- Update API schemas/controllers/routes, auth/session/JWT/native-app exchange flows, signed cursors, storage/avatar object keys, admin/search, commands, tasks, observability, fixtures/factories, migrations, docs, and tests.
- Preserve only production `WaitlistEntry` business data. Export business fields without old identity, rebuild the complete clean schema, restore each row with a new UUID primary key, and verify counts, deterministic business-data checksums, uniqueness, timestamps, consent/source fields, and public API behavior.
- Adapt the existing CLD-003 provisioning gateway only where identity changes: preserve exact transport names and map `workspace_id=Workspace.id`, `binding_id=AllyBinding.id`, `ally_ref=Ally.id`, and `operation_id=ProvisioningOperation.id` as canonical UUID strings; require Cloud/Foundry request and receipt fixture parity and record a minimal Foundry change if any field is not treated opaquely.
- Replace historical app migrations with a reviewed clean UUID-native baseline suitable for a fresh database, including swappable-user and dependency ordering.

### Out of Scope

- New CLD-005 Foundry gateway, execution dispatch, activity projection, or event-ordering behavior. Existing CLD-003 provisioning remains in scope only for UUID identity adaptation.
- Compatibility for disposable non-waitlist rows, old integer IDs, prefixed IDs, tokens, sessions, cursors, bookmarks, or storage keys.
- Product behavior changes unrelated to identity, new dependencies, a generic identity abstraction, or a long-lived dual-write/dual-read migration.
- Preserving Django admin history, sessions, auth flows, workspaces, Allies, onboarding, provisioning, conversations, messages, or other non-waitlist data.

### Dependencies and Assumptions

- This foundation PR merges into `dev` before CLD-005 resumes; downstream branches rebase onto the merged UUID baseline.
- Production waitlist business data is the only durable dataset. All non-waitlist rows are explicitly disposable and must not be exported or restored.
- Production writes remain disabled throughout export, rebuild, restore, and verification. Owner approval is required for the export artifact, maintenance window, clean baseline, restore report, and reopen decision.
- Verified Railway topology is `staging` and `prod`, each using services `Backend`, `Worker`, `Beat`, `Postgres`, and `Redis`. Production cutover uses a separately provisioned green Postgres while the old Postgres remains intact; this PR documents owner-run commands/steps but performs no Railway mutation.
- The protected source is the current `waitlist_waitlistentry` table plus any evidence-discovered implicit table that owns waitlist business fields. No current non-waitlist relation may be silently treated as protected.
- PostgreSQL/Django UUID capabilities and the locked repository toolchain are sufficient; no new package is required.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `backend/common/identity.py` or direct model defaults | UUID default | `new_uuid() -> UUID` only if a named helper is justified; otherwise `uuid.uuid4` directly | No input; cryptographically suitable UUID4 | UUID | No I/O; no prefixes or string wrapper |
| `backend/waitlist/management/commands/export_waitlist.py` | export command | `handle(output: Path) -> None` | Owner-approved path; operator-confirmed Backend/Worker/Beat freeze and drained writes; source schema version; exact business fields; no overwrite | Versioned manifest plus data file | Runs the export in a repeatable-read transaction with the shared encoder/checksum helper; fails on missing/duplicate `attempt_id_digest`, schema mismatch, or incomplete read |
| `backend/waitlist/management/commands/restore_waitlist.py` | restore command | `handle(input: Path, expected_checksum: str) -> None` | Operator-confirmed freeze/drain; empty UUID-native waitlist table; validated manifest/schema/checksum | Restored count/checksum report | Directly restores with shared helper, assigns UUID4 PKs, preserves business fields/timestamps, and rolls back on partial/duplicate/mismatch |
| `backend/waitlist/management/commands/verify_waitlist.py` | verify command | `handle(manifest: Path) -> None` | Operator-confirmed freeze/drain; source manifest plus restored database | Recorded verification report | Directly recomputes shared canonical checksum and field/count equivalence; non-zero exit blocks operator reopen on mismatch |
| Auth/session/token services | UUID identity encoding | Existing signatures updated from prefixed strings/ints to `UUID` | Strict UUID parsing; canonical lowercase hyphenated representation at serialization boundaries; no fallback prefix parser | Existing auth/session result shapes with UUID `user_id`, `session_family_id`, and related claims | Invalid legacy IDs fail as invalid/expired; no silent account lookup or token upgrade |
| Storage/avatar services | object-key builder | Existing builder signatures accept UUID owner/asset IDs | UUID objects or validated canonical strings; reject path separators and unknown formats | Deterministic object key containing UUID segments | Existing storage I/O; old disposable keys are not migrated; never log full object URL/key |

### API and Transport Contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Public client | Existing resource routes such as `/api/v1/workspaces/{workspace_id:uuid}` and nested Ally/conversation/message routes | Existing session plus tenant membership/capability checks remain unchanged | Path/body identifiers are strict UUIDs | Existing envelope with UUID `id`/relation fields; no `public_id` | Malformed UUID is `422`/route miss per existing framework contract; unauthorized/foreign resources retain privacy-safe behavior; no prefix fallback |
| Browser/native auth client | Existing login/callback/session/refresh/native exchange endpoints | Existing CSRF, OAuth state, proof, session-family, and token rules | UUID claims/references where identity is carried | Existing auth envelope with UUID user/session/avatar IDs | Old prefixed/int claim is invalid/expired; refresh remains rotation-safe and replay detection unchanged |
| Waitlist client | Existing waitlist create/status contract | Existing public validation/rate-limit/privacy behavior | Business fields unchanged; client does not submit model identity | Existing success envelope; any returned identifier is a UUID `id` only if current evidence proves the API exposes one | Duplicate/invalid/rate-limit behavior unchanged; retries retain existing business idempotency semantics |
| Internal commands/tasks | Existing model-ID arguments | Existing operator/task authorization | UUID arguments encoded canonically | Existing safe result summaries with UUID identifiers only when necessary | Invalid IDs fail before lookup; task logs/metrics do not emit customer data or full UUID sets |
| CLD-003 Cloud/Foundry provisioning | Existing provisioning request/receipt contract | Existing service authentication and tenant/binding checks | Preserve exact field names and send canonical UUID strings: `workspace_id=Workspace.id`, `binding_id=AllyBinding.id`, `ally_ref=Ally.id`, `operation_id=ProvisioningOperation.id` | Existing receipt fields/behavior; identifiers remain opaque | Update Cloud and Foundry request/receipt fixtures and tests for UUID opacity; if Foundry validates prefixes, land the minimal cross-repo contract adaptation before Cloud cutover; no CLD-005 behavior |

Representative product response:

```json
{
  "status": "success",
  "message": "Workspace retrieved.",
  "data": {
    "id": "750e8400-e29b-41d4-a716-446655440000",
    "owner_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "My Workspace"
  }
}
```

Representative waitlist export manifest:

```json
{
  "format_version": "waitlist-business-export-v1",
  "source_table": "waitlist_waitlistentry",
  "business_columns": ["attempt_id_digest", "attempt_token_digest", "completion_digest", "generation_claimed_at", "name", "appearance_catalog_version", "appearance_key", "job", "personality", "greeting_text", "greeting_policy_version", "greeting_generated_at", "reply_text", "reply_recorded_at", "email_normalized", "consent_version", "joined_at", "expires_at", "created_at", "updated_at"],
  "row_count": 42,
  "canonical_checksum": "sha256:<64 lowercase hex>",
  "exported_at": "2026-08-25T12:00:00Z"
}
```

`waitlist-business-export-v1` is locked to exactly those 20 fields. The old integer PK and `public_id` are the only excluded current columns. Canonical encoding uses UTF-8 JSON Lines with keys in manifest order. It preserves NFC strings exactly apart from JSON escaping, normalizes datetimes to UTC RFC3339 with six fractional digits and `Z`, and encodes database null as JSON `null` (never an empty string). Rows are ordered strictly by unique `attempt_id_digest`. Blank or repeated `email_normalized` values are valid and are never deduplicated. Source-to-restored equivalence compares every encoded field row-for-row by `attempt_id_digest`; UUID identity is outside the checksum. Pagination/filtering behavior is unchanged except that cursor payloads encode UUID resource identity. This is a breaking identity reset with no legacy compatibility window.

### Data Shapes and Invariants

#### Database Models

| Type / category | Model / table | Location | Fields and types | Required / nullable / defaults | Validation, indexes, constraints, and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- | --- |
| Persisted auth models (9) | `User`, `ExternalIdentity`, `UserProfile`, `AuthFlow`, `NativeAuthorizationTransaction`, `NativeExchangeCode`, `SessionFamily`, `RefreshToken`, `AvatarAsset` | `backend/auths/models.py` | `id: UUID`; every relation to user/session/transaction/avatar is UUID-backed | UUID PK required/default UUID4; existing business null/default rules unchanged | Rebuild unique identities, token digests, session-family/replay indexes, one-to-one constraints, active-user indexes without `public_id` | Disposable rows; clean-baseline only; old sessions/tokens become invalid |
| Persisted workspace models (2) | `Workspace`, `Membership` | `backend/workspaces/models.py` | `id: UUID`; UUID owner/workspace/user FKs | UUID PK required/default UUID4 | Preserve ownership, membership uniqueness, tenant indexes and cascading behavior; UUID ordering is explicit where stable ordering is needed | Disposable rows; clean-baseline only |
| Persisted Ally models (4) | `Ally`, `AllyBinding`, `OnboardingAttempt`, `ProvisioningOperation` | `backend/allies/models.py` | `id: UUID`; UUID workspace/ally/user/binding FKs/one-to-ones | UUID PK required/default UUID4 | Preserve one-binding-per-Ally, onboarding/provisioning idempotency/state constraints and indexes; remove prefix-based ordering/lookup | Disposable rows; clean-baseline only; external provider references remain opaque non-PK fields where required |
| Persisted chat models (2) | `Conversation`, `Message` | `backend/chat/models.py` | `id: UUID`; `Conversation.ally` and `Message.conversation` UUID relations | UUID PK required/default UUID4 | Preserve current conversation ownership and message ordering/idempotency constraints; do not invent workspace/author FKs | Disposable rows; clean-baseline only; CLD-005 additions excluded |
| Persisted waitlist model (1) | `WaitlistEntry` | `backend/waitlist/models.py` | `id: UUID`; exact export-v1 business fields: `attempt_id_digest`, `attempt_token_digest`, `completion_digest`, `generation_claimed_at`, `name`, `appearance_catalog_version`, `appearance_key`, `job`, `personality`, `greeting_text`, `greeting_policy_version`, `greeting_generated_at`, `reply_text`, `reply_recorded_at`, `email_normalized`, `consent_version`, `joined_at`, `expires_at`, `created_at`, `updated_at`; no `public_id` | UUID PK required/default UUID4; current business defaults/nullability unchanged | Unique `attempt_id_digest` is export ordering/equivalence key; repeated/blank emails remain valid and are not deduplicated; preserve digests, timestamps, null/empty distinctions, consent, appearance, greeting, reply, and expiry semantics | Only protected data: exact-field export, clean rebuild, UUID restore, row-for-row checksum/API verification |
| Framework/implicit tables | Django auth permission/group through tables, admin log, sessions, migrations, content types, implicit relation tables | Django/contrib plus generated schema | UUID FK columns wherever they reference UUID product models | Framework defaults | Fresh baseline must create type-compatible relations with swappable user dependency and no orphan FK | Framework/business rows disposable; permissions/content types regenerated normally |

#### Enums

No enum vocabulary changes. Existing auth, membership, onboarding, provisioning, chat, and waitlist statuses remain unchanged; tests prove the migration does not reinterpret state values.

#### API Request Schemas

| Type / category | Request schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| API request schemas | Existing workspace/Ally/chat/auth schemas | `backend/**/schemas.py` | Every model reference becomes `UUID`; business fields unchanged | Existing required/null/default rules | Strict UUID parse; reject integers, prefixes, malformed/overlong values, and cross-tenant IDs | Breaking reset; no dual parser |
| Waitlist request | Existing create/request schema | `backend/waitlist/schemas.py` | Business fields unchanged; no client-supplied ID | Existing rules | Normalization, consent, duplicate, and rate-limit behavior unchanged | Compatible business contract; identity response changes only if currently exposed |

#### API Response Schemas

| Type / category | Response schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| Product response schemas | Existing auth/workspace/Ally/chat responses | `backend/**/schemas.py` | `id` and relation identifiers are canonical UUID strings; no `public_id` | Existing shape otherwise unchanged | Tenant-safe fields only; serializers never fall back to internal integer/prefix aliases | Breaking identity representation accepted for pre-launch reset |
| Waitlist response | Existing waitlist response | `backend/waitlist/schemas.py` | Business-safe fields unchanged; exposed identifier, if any, is UUID `id` | Existing required/null rules | Do not expose export metadata, source PK, checksum, or internal restore state | Verify exact pre/post public behavior apart from accepted UUID identity change |

#### Temporary / Internal Shapes

| Type / category | Shape | Location | Fields and types | Lifetime / visibility | Validation, security, and invariants | Compatibility / rotation notes |
| --- | --- | --- | --- | --- | --- | --- |
| Signed JWT/session claims | Auth token payload | `backend/auths/**` | UUID `sub`/user/session-family/avatar references; existing issue/expiry/audience fields | Token lifetime; opaque to product clients | Signature/audience/expiry/replay checked before UUID lookup; no sensitive data in logs | All pre-reset tokens invalid; no legacy claim parser |
| Signed cursor | Existing cursor payloads | controllers/services | UUID scope/resource ID plus ordering fields and signature metadata | Page lifetime; opaque | Signature, tenant scope, bounds, and UUID type checked; stable tie-breaker remains explicit | Old cursors invalid after reset |
| Waitlist export artifact | `waitlist-business-export-v1` | encrypted owner-approved operational storage | Exact 20-field canonical JSONL rows, manifest, count, SHA-256 checksum; no old IDs | Through verified restore and approved rollback window | Client-side or platform KMS encryption at rest plus TLS; named least-privilege access/audit; independent immutable hash | Owner records policy-backed retention before cutover; never delete before verification and rollback window end; deletion receipt retains no business data |
| Full database logical dump | Pre-cutover encrypted PostgreSQL custom-format dump | Owner-approved secure backup destination | Complete old database for rollback; `pg_dump --format=custom --no-owner --no-acl`; independent SHA-256 | Through verified restore and approved rollback window | Encrypted/access-audited; `pg_restore --list` plus isolated timed restore rehearsal | Owner records policy-backed retention before cutover; old DB/dump survive verification and rollback window; deletion receipt required |
| Storage key | Avatar/object key | storage service | UUID owner/asset segments and existing safe suffix | Object lifetime | No traversal, bounded suffix, opaque bucket URL | Old disposable objects may be purged under existing storage policy |

#### Shared Internal Helper

| Type / category | Helper | Location | Signature | Inputs and validation | Return value | Side effects and errors |
| --- | --- | --- | --- | --- | --- | --- |
| Shared helper (not a service abstraction) | `encode_waitlist_row` / `checksum_waitlist_rows` | waitlist command helper module | Exact export-v1 row -> canonical UTF-8 JSONL bytes; ordered rows -> SHA-256 | Locked 20 fields, NFC strings, fixed UTC datetimes, JSON null, unique attempt digest ordering | Canonical bytes/digest | Pure deterministic logic shared only by the three thin commands; no I/O, state machine, framework, or generic export API |

#### PostgreSQL Migration Contract

The migration test introspects PostgreSQL, not only Django metadata. It asserts target columns and UUID types for all 18 model PKs and exactly these 22 relations: `ExternalIdentity.user`, `UserProfile.user`, `UserProfile.current_avatar`, `AuthFlow.user`, `AuthFlow.session_family`, `NativeExchangeCode.transaction`, `NativeExchangeCode.user`, `SessionFamily.user`, `RefreshToken.family`, `AvatarAsset.user`; `Workspace.owner`, `Membership.workspace`, `Membership.user`; `Ally.workspace`, `AllyBinding.ally`, `OnboardingAttempt.user`, `OnboardingAttempt.ally`, `ProvisioningOperation.binding`, `ProvisioningOperation.workspace`, `ProvisioningOperation.user`; `Conversation.ally`, `Message.conversation`. It separately asserts UUID target references for PermissionsMixin `user_groups`/`user_permissions` and `django_admin_log.user_id`. It deliberately does not pin generated constraint names or incidental indexes; existing model/domain tests continue to own business uniqueness, deletion, and indexing invariants. Framework-owned tables may retain independent integer PKs when they do not reference product identities.

### Plain-language glossary

- **Business data:** Waitlist fields representing the applicant submission and audit timestamps, excluding old database IDs and the removed `public_id`.
- **Clean baseline:** A new initial migration graph that creates the UUID-native schema from an empty database; it is not a conditional destructive migration.
- **Canonical checksum:** SHA-256 over a documented, stable ordering and normalized serialization of protected waitlist business fields.
- **Reset window:** An owner-approved period in which production writes/workers are disabled and the clean schema is installed and verified.

### Frontend Interaction Shapes (if applicable)

No visual or state-flow redesign. Existing clients must treat identifiers as opaque canonical UUID strings. Update route builders, typed API models, cache keys, and tests wherever the repository contains them; loading, error, empty, and permission behavior remains unchanged. Old bookmarked prefixed-ID routes fail through the existing not-found/validation behavior.

## Phases

### Phase 1 - Freeze inventory and UUID contract

- Goal: Establish an auditable map of all 18 models, implicit/framework relations, and every identity consumer before migration work.
- Work items: Use a PR checklist (not a ledger abstraction) to record the model/FK graph and classify hits across active runtime code, active migrations, current contracts, current operational docs, settings, commands, admin, logs, JWT/session claims, cursors, storage, routes, fixtures, and `common.identifiers`; lock canonical UUID behavior, exact waitlist export-v1, and four-field Cloud/Foundry fixture parity. Historical accepted plans remain unchanged or receive a clear superseded label rather than mechanical rewrites.
- Impacted files/systems: PR checklist plus model/schema/controller/auth/storage/observability/test directories.
- Exit criteria: Named checklist covers all 18 models and every `public_id`/prefix helper hit; exact waitlist table/columns and absence/presence of inbound relations are owner-reviewed; no CLD-005 file enters scope.

### Phase 2 - Convert schema and runtime atomically

- Goal: Land the clean UUID baseline and every active runtime consumer in one reviewable, inseparable change.
- Work items: Convert PKs/FKs/one-to-ones; remove `public_id`/generators; rebuild migrations in dependency order; update routes, schemas, services, auth/JWT/session/native exchange, cursors, storage, tasks, admin, observability, fixtures, tests, and CLD-003 four-field contracts. Use one central strict UUID parser test matrix plus representative distinct route-boundary tests; run full existing domain/auth/tenant suites. The schema contract asserts target columns/types for exact 18 PKs, 22 relations, permission through refs, and admin-log user ref; it does not assert generated constraint names or incidental indexes, while existing business-invariant tests remain.
- Impacted files/systems: All model/migration modules and active runtime/API/auth/storage/admin/test consumers.
- Exit criteria: Fresh PostgreSQL migration and `makemigrations --check` pass; active runtime/migrations/current contracts/current ops docs have zero legacy identity hits; strict UUID boundaries and existing suites pass; historical plans are unchanged or labeled superseded.

### Phase 3 - Build waitlist tooling and rehearse

- Goal: Prove production waitlist business data can survive the clean reset before touching production.
- Work items: Add three thin Django commands (export, restore, verify) that share only one canonical row encoder/checksum helper; do not create a generic export framework or application maintenance-state infrastructure. Freeze/drain remains an operator procedure. Run one complete staging/shadow waitlist export/rebuild/restore/API rehearsal and one separate isolated timed custom-format logical-dump restore; cover corrupt/truncated/duplicate-attempt/null/empty/repeated-email cases.
- Impacted files/systems: Waitlist commands/helper/tests, secure artifact destinations, staging/shadow and isolated restore database.
- Exit criteria: The single complete waitlist rehearsal passes field equivalence/API gates; the separate full-dump rehearsal meets RTO and schema/count checks; failure injection proves no partial reopen.

### Phase 4 - Production cutover and final validation

- Goal: Blue/green the production database using the verified Railway topology while preserving all and only waitlist business data. Target RPO is zero accepted waitlist writes after the freeze/drain checkpoint; target RTO is 60 minutes from scaling services to zero to restored Backend health, with owner-authorized rollback if either target or a verification gate is missed.
- Canonical runbook: This Phase 4 section is the sole exact-command cutover runbook; implementation must not create a third duplicate operations document. Immediately before execution, revalidate Railway CLI command help/behavior, linked project/environment, regions, replica counts, and variable-reference method; record non-secret evidence and amend this section if CLI behavior changed.
- Owner-run preflight (no Railway mutation in this PR): pin the reviewed app revision; explicitly link/verify `cloud`/`prod`; record `railway status --json`, regions, and counts (`Backend ams=1`, `Worker ams=1`, `Beat ams=1` currently). After verified context, provision green with `railway add --database postgres --json`; immediately verify returned service/environment. Never capture `railway variable list` because it outputs secrets.
- Freeze and drain: announce outage; scale production `Backend`, `Worker`, and `Beat` to zero with `railway service scale --project cloud --environment prod --service Backend ams=0`, then the same explicit command for `Worker` and `Beat` (resolve and record the current region ID instead of assuming `ams` if topology changes); confirm no replicas, in-flight HTTP, Celery tasks, scheduled jobs, or DB writes remain. Record the final transaction/checkpoint time establishing RPO zero.
- Preserve old state: from a secure operator job/host with the old database secret injected privately, create an encrypted PostgreSQL custom-format backup using `pg_dump --format=custom --no-owner --no-acl --file=<encrypted-secure-path>/cloud-prod-pre-uuid.dump <private-connection>`; compute SHA-256 and store it independently in immutable release evidence, then verify `pg_restore --list` succeeds. Rehearse on an isolated Postgres with `pg_restore --clean --if-exists --no-owner --no-acl --dbname=<isolated-private-connection> <dump>`, time the restore against the 60-minute RTO, and run schema/count smoke checks. PITR is not enabled and is not a rollback mechanism. Keep old Postgres intact/read-only and create the locked waitlist export; do not expose connections or variables in logs/evidence.
- Build green: point an owner-controlled one-off job at green Postgres using secret injection outside captured output; deploy the pinned revision; run fresh migrations, PostgreSQL migration-contract assertions, waitlist restore, and source/restored field equality. Production validation is read-only only: schema queries, counts/checksums, and safe GET/health checks. It includes no production POST canary.
- Switch references while stopped: update DB references for all three services with scoped, secret-safe `railway variable set --environment prod --service Backend <DB_REFERENCE_KEY>=<GREEN_REFERENCE> --skip-deploys`, repeated for `Worker` and `Beat`. Explicitly scale `Backend` back to recorded `ams=1`, redeploy, and pass status/health/read-only waitlist/migration gates; then scale `Worker` to `ams=1`, redeploy, and pass its status/queue gate; then scale `Beat` to `ams=1`, redeploy, and pass its status/scheduler gate. Never rely on redeploy alone to restore replicas. Redis remains unchanged.
- Approval, rollback, and retention: the release owner has rollback authority until all gates pass; the database owner independently approves equivalence. On failure, scale green consumers to zero, restore all three old references, then explicitly scale/redeploy/gate Backend, Worker, and Beat at recorded counts. Before cutover, owners approve and record retention durations for old Postgres, logical dump, and waitlist export based on policy. None may be deleted before verification completes and the approved rollback window ends; deletion receipts are required.
- Impacted files/systems: Railway `prod`/`staging`; `Backend`, `Worker`, `Beat`, old and green `Postgres`, unchanged `Redis`; secure backup storage and immutable release evidence. The PR contains runbook/docs/tests only and performs no Railway mutation.
- Exit criteria: Green schema/contract, exact waitlist equivalence, read-only production gates, RPO/RTO, full CI, privacy checks, active-scope zero-hit search, all three green references, two-person approval, retention record, and CLD-005 parked-until-merge handoff all pass.

## Acceptance Criteria

1. All 18 named models have UUID primary keys; PostgreSQL contract assertions cover every explicit relation, PermissionsMixin group/permission through tables, and `django_admin_log.user_id`; independent framework-owned integer PKs remain allowed only when they do not reference product identities.
2. Searches find no `public_id`, prefixed-ID generator/parser/validator, prefix-based lookup/order/index, compatibility shim, or legacy identity dependency in active runtime code, active migrations, current contracts, or current operational docs. Historical accepted plans may retain the old terminology only when clearly marked superseded and are not treated as active implementation guidance.
3. Product APIs accept/return canonical UUID identifiers with strict validation and unchanged authentication, authorization, tenant isolation, and privacy-safe error behavior.
4. User/session/JWT/native exchange/avatar/workspace/Ally/onboarding/provisioning/conversation/message flows pass using UUID identity; pre-reset tokens, sessions, cursors, and disposable storage references are invalid rather than upgraded.
5. Clean migrations create the complete schema from zero, `makemigrations --check` passes, and inspected PK/FK/index/constraint types match the model graph.
6. Production reset exports exactly the locked 20 WaitlistEntry fields, preserves null/blank/repeated-email semantics without email dedupe, orders/equates rows by unique `attempt_id_digest`, restores UUID-native rows, and proves every source/restored field, count, checksum, uniqueness, timestamps, and API behavior equivalent.
7. The reset never restores non-waitlist data; failure keeps writes disabled and reroutes to intact old Postgres or restores the encrypted custom-format logical dump only under the approved rollback procedure.
8. Export and logical-dump artifacts remain encrypted/access-audited, have independently verified hashes, pass restore rehearsal, and follow owner-approved policy-backed retention recorded before cutover; old DB/artifacts cannot be deleted before verification and the rollback window end, and PITR is not claimed.
9. Full relevant tests, migration checks, lint, format inspection, and CI pass with PostgreSQL evidence.
10. Railway staging rehearsal and production blue/green runbook record current region/replicas, scale Backend/Worker/Beat from `ams=1` to zero and explicitly back to `ams=1` with a status gate after each during activation and rollback, use production read-only gates, meet RPO zero/RTO 60-minute targets, and execute no mutations in the PR.
11. CLD-003 Cloud/Foundry request and receipt fixtures match exact transport names `workspace_id`, `binding_id`, `ally_ref`, and `operation_id`, carrying canonical UUID strings from `Workspace.id`, `AllyBinding.id`, `Ally.id`, and `ProvisioningOperation.id`; any opacity adaptation is minimal and new CLD-005 behavior remains absent.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots/endpoints: UUID PK lookup in auth/session refresh, Workspace/Ally nested routes, chat lists, provisioning lookup, waitlist duplicate checks, and admin search.
- Query-shape choices: retain existing `select_related`/`prefetch_related`; replace prefix/public-ID indexes with UUID PK/FK indexes; keep business uniqueness indexes; use explicit timestamp+UUID tie-breakers rather than UUID-only chronological ordering; bound export/restore batches while preserving one consistent repeatable-read view.
- Expected query-count change: Identity conversion must not add lookups; PK/FK paths remain indexed and query counts stay equal or lower.
- Measurement/monitoring plan: Reuse existing query-count coverage; add no new query-count tests unless implementation changes a query shape. Inspect PostgreSQL plans only for changed query/index shapes and monitor sanitized latency/errors after reset.

### N+1 Prevention

- Relation access map: Auth user/profile/avatar/session; Workspace owner/memberships; Ally/binding/onboarding/provisioning; Conversation/Message ownership; Waitlist standalone.
- Prefetch/select plan per endpoint/service: Preserve current eager-loading maps. UUID conversion does not justify per-row identity translation queries.
- N+1 regression guardrails: Existing domain suites remain; add targeted query-count coverage only if a query shape changes. No prefix-to-UUID translation table or lookup loop is permitted.

### Detailed Unit Test Cases

- Happy path: Exact PostgreSQL inventory for 18 PKs/22 relations/permission refs/admin-log user ref; UUID defaults and representative distinct route boundaries; full existing auth/domain/tenant suites; CLD-003 four-field fixture parity; waitlist encoder and three command flows.
- Validation and bad input: One central UUID parser matrix covers canonical acceptance and representative malformed/legacy inputs; representative route boundaries prove parser/error integration without a Cartesian endpoint matrix. Focused JWT/cursor/storage tests and waitlist corrupt/truncated/wrong-version/checksum/duplicate-attempt cases remain.
- Auth/RBAC boundaries: foreign Workspace/Ally/conversation/message UUID, deleted user/session, token replay, session-family mismatch, admin permissions, privacy-safe missing-versus-foreign behavior.
- Idempotency/retry behavior: duplicate waitlist submission, repeated export, restore into non-empty target, repeated restore, command interruption, transaction rollback, deterministic checksum across ordering, restart after partial file write, and two-row source/restored equivalence where both rows have blank or repeated `email_normalized` but distinct unique `attempt_id_digest` values.
- Failure-path behavior: model/FK migration cycle, swappable-user ordering failure, missing waitlist column, blocked write during window, restore exception, post-restore API mismatch, logical-dump restore failure, observability redaction, old token/cursor/object key use.

## Frontend Considerations (if applicable)

Frontend implementation is not applicable in this Cloud repository. API handoff only: publish canonical UUID route/request/response contracts and tell consumers identifiers remain opaque; client implementation belongs to its owning repository.

## Test Plan

- Unit tests: Exact PostgreSQL UUID targets for 18 PKs/22 relations/permission through refs/admin-log user ref; one central UUID parser matrix; representative distinct route boundaries; auth claims/cursors/storage/admin/observability; locked waitlist encoder/checksum and three thin commands.
- Integration/API tests: Full auth/session/native/avatar, Workspace/membership, Ally/binding/onboarding/provisioning, exact four-field CLD-003 Cloud/Foundry request/receipt UUID fixture parity, chat, and waitlist API suites with UUID positive/negative/tenant-boundary cases; fresh PostgreSQL migration test; export/rebuild/restore and encrypted logical-dump restore rehearsals. Staging/shadow runs may use POST/GET contract tests; production gate is strictly read-only schema/count/checksum/GET/health verification.
- Regression checks: Full existing domain/auth/tenant suites, authorization/privacy, token rotation/replay, business uniqueness/idempotency, timestamp ordering, storage cleanup, admin access, and CI migration checks; query counts only where query shapes change.
- Manual verification checklist: Search for `public_id` and known prefix helpers; inspect the exact PostgreSQL migration contract; inspect OpenAPI route/response schemas; run locked waitlist manifest/count/checksum and row-for-row equivalence; exercise POST contracts only in staging/shadow; use read-only production GET/health gates; verify non-waitlist tables empty after production reset; inspect logs/admin/metrics for sensitive export, secrets, or legacy IDs; verify immutable hashes, restore rehearsal, and expiry/deletion receipts.
- Commands: `make sync`; `make check`; `make migrations APP=<each affected app>` during development; `cd backend; uv run python manage.py makemigrations --check`; clean disposable database `make migrate`; `make test`; targeted `make test APP=backend/auths/tests`, `backend/workspaces/tests`, `backend/allies/tests`, `backend/chat/tests`, `backend/waitlist/tests`; `make lint`; `make format` and inspect diff; repository searches with `rg` for `public_id`, `new_public_id`, and known prefixes; run export/restore/verify commands against a rehearsal database.
- CI basis: Existing `.github/workflows/ci.yml`, Makefile, locked `uv` dependencies, Django system/migration checks, pytest with PostgreSQL concurrency coverage, Ruff lint/format, and coverage reporting.

## Risks and Mitigations

- Risk: Hidden legacy identity remains in active runtime, migrations, current contracts, or current operational docs. Mitigation: PR checklist, central parser/representative boundary tests, schema/OpenAPI inspection, and narrow zero-hit searches; historical accepted plans remain unchanged or are labeled superseded. Rollback/fallback: block merge; there is no compatibility shim.
- Risk: Clean migration graph breaks swappable-user/framework dependency ordering. Mitigation: build from empty PostgreSQL repeatedly, inspect generated dependencies/through tables/content types, and run system/migration checks in CI. Rollback/fallback: revise the baseline before production; never fake migration state.
- Risk: Waitlist data is lost, duplicated, or reinterpreted. Mitigation: locked 20-field contract, attempt-digest ordering, exact null/string/datetime encoding, no email dedupe, write freeze, encrypted custom-format logical dump, deterministic checksum/count, rehearsed restore, API equivalence, and two-person approval. Rollback/fallback: keep writes closed and repoint all services to intact old Postgres; never continue with any field/checksum mismatch.
- Risk: Export artifact exposes applicant data. Mitigation: least-privilege encrypted storage, business fields only, no git/log/admin attachment, access audit, and owner-approved deletion/retention. Rollback/fallback: stop reset, revoke access/rotate credentials, and follow incident handling before retry.
- Risk: UUID changes accidentally weaken tenant authorization or enumeration privacy. Mitigation: retain ancestry/capability checks and negative cross-tenant tests; UUID unpredictability is not authorization. Rollback/fallback: block merge/traffic reopening until boundary tests pass.
- Risk: Existing clients use prefixed routes/tokens/cursors. Mitigation: pre-launch breaking reset is explicit, all non-waitlist state is disposable, and clients/fixtures deploy with the foundation. Rollback/fallback: revert deployment as one unit; do not introduce dual parsing.
- Risk: Railway cutover partially switches services or leaks secrets in evidence. Mitigation: explicit environment/service-scoped commands, all three services stopped during reference update, Backend-first restart, pinned revision, no `railway variable list` output, immutable non-secret release evidence, and RPO/RTO gates. Rollback/fallback: release owner scales green consumers to zero, restores all three old references, and redeploys Backend then Worker/Beat.
- Risk: CLD-003 Foundry assumes a prefixed binding key. Mitigation: cross-repo fixture/contract inspection and UUID opacity test before merge. Rollback/fallback: land only the minimal Foundry parser/schema adaptation or block Cloud cutover; do not add CLD-005 behavior.
- Risk: CLD-005 scope leaks into the foundation. Mitigation: diff review against the brief and explicit excluded-path/behavior checklist. Rollback/fallback: split/remove gateway/projection changes before review.
- Required pre-cutover approval: Owners record policy-backed retention durations, secure destinations, maintenance window, and two-person reopen evidence. The waitlist field contract and `pg_dump`/`pg_restore` procedure are resolved in this plan; only environment-specific values and retention durations are approved immediately before execution.
