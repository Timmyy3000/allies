# CLD-012 routine contract plan

## Using this template

Historical concise draft. The owner's subsequent Sol revision request makes `cld-012-routines-contract.md` the authoritative current plan. Route: full; HTML required: no. Contract freeze and live feasibility remain pending. Planning only; no production changes.

## Feature Overview

Publish a narrow routines-v1 contract and reproducible evidence for separate concurrent sessions of one Ally profile. Authority: accepted Nabu `projects/allies/engineering/specs/routines.md`, revision `9f8226916656619b66b617eb313a59e09901e4ecc5c7b5584552ea37f6913433`, and inspected CLD-012/CLD-013/FND-012 tickets. Product approval already exists.

Inspected Cloud `41f06a2c25093015af4190a178c849114c4fb28a` and Foundry `1d03ea557be757f4eca4c6b6478d542291169b14`, both repository instructions/styles, copied kickoff configuration, template, README, Makefiles, pytest configuration and CI. Reuse the existing strict v1 envelopes, canonical fingerprints and gateway; no shared framework.

## User Stories

1. Implementers receive matching contracts and failure semantics across repositories.
2. Users can chat while separate routine sessions execute with their Ally's authorized resources.
3. Operators can distinguish demonstrated capability from required runtime changes.

## Scope

### In Scope

Contract documents, matching fixtures, focused contract/constraint tests, a minimal local feasibility harness and sanitized evidence. Exact artifacts appear in the phases below.

### Out of Scope

Production code, migrations, scheduler/CLD-013 implementation, FND-012 feature implementation, interface work, deployment and merge. This planning worker does not commit, push, open PRs or spawn agents.

### Dependencies and Assumptions

Use assigned worktrees and existing dependencies. Engineering recommendations require contract review, not renewed product approval. Unknown feasibility and policy details must be resolved before dependent integration is declared ready.

## Contract and Shape Definitions

### Function and Service Shapes

Only proposed test/harness helpers: `test_routines_v1_vectors() -> None`, `test_stable_separate_session_ids() -> None`, and `smoke_routine_sessions.main() -> int`. Inputs are synthetic fixtures and local sandbox configuration; output is assertions or sanitized pass/fail/blocked evidence. No product service is added.

### API and Transport Contracts

Freeze complete request, receipt and error examples for management (`create/update/pause/resume/delete/get/list`), owner discovery/detail, dispatch, result events, approval decisions and cancellation of waiting runs. Use existing authentication/error conventions. New routine kinds must reject safely on old consumers; preserve existing conversation-message v1 behavior and fingerprints.

| Area | Contract to freeze |
| --- | --- |
| Ownership/identity | Cloud owns routines, scheduling, authorization and main-chat projection; Foundry owns profiles, executions, attempts, leases and events. Immutable owner/workspace/Ally/binding correlation; separate main and fresh run conversation IDs |
| Management/discovery | Distinct title and full Ally-authored prompt. Clear user instructions create immediately; suggestions need agreement; missing timing/timezone requires clarification. Delete requires chat confirmation. Controls act through the Ally; only persisted success changes visible state. Include responsible Ally and Active/Paused status; include paused recurring routines, exclude deleted/exhausted schedules; owner-scoped bounded pagination and authorized Full prompt detail |
| Schedule/timezone | One-time and recurring schedules; saved browser/device IANA timezone changes only explicitly. Freeze grammar and precision. Preserve local wall time across DST; gap moves to next valid time, fold runs once (recommend earliest instant). Recover latest missed recurring occurrence once or missed one-time once, visibly delayed; never replay deliberately paused/skipped occurrences |
| Dispatch/context | Immutable revision/full-prompt snapshot, fresh conversation per occurrence, same profile/memory/files/authorized tools. No automatic main/prior-run transcript copy. Edits/pause/delete affect future work; already working run finishes |
| Results/context | Every completed run, including unchanged checks, and every failure posts attributed main-chat result. Preserve typed rich references and model-visible identity; no full transcript or run-inspection link. Recommend durable ingestion followed by insertion after the active main turn and before the next turn, with insertion receipt/watermark. UI projection alone is insufficient; preserve results after deletion |
| Approval | Expire unanswered request after 24h; earlier due occurrence cancels waiting run and proceeds only after effective terminal fencing. Serialize approval/expiry/replacement: approval already authorizing work becomes working and causes skip; cancellation/expiry winning invalidates old approval. Rejection prevents action; all outcomes reach main chat. Separate human wait from 60s transport deadline; preserve existing 300s chat approval contract |
| Lifecycle/errors | Schedule state is separate from run outcome. Working same-routine overlap skips without backlog; different routines/main chat remain concurrent. Terminal failure does not automatically rerun the whole task or pause recurring work. Preserve bounded safe transport retries and truthful pending/cancellation states |
| Correlation/revision | Routine/occurrence/run IDs, revision, both conversation IDs, binding and execution/attempt/generation/sequence. Same semantic key/hash returns same receipt; changed replay conflicts. Expected revision rejects stale mutations; generation fences stale events/actions; occurrence identity survives transport retries |
| Privacy/retention/capacity | Existing authorization/approval safeguards and payload limits; reject oversized full prompt before save, never truncate. Preserve posted results; inventory policy before defining retention windows or quotas. Retain records needed by live approvals, pending delivery and supported replay windows. No new user-visible restrictions without policy evidence or Product decision |

### Data Shapes and Invariants

#### Database Models

None added. Document future per-conversation binding/lease scope and preserve main-chat identity, same-conversation exclusion, tenant checks and generation fencing.

#### Enums

Freeze operation, schedule state, occurrence disposition, run outcome and approval decision vocabularies, mapping to existing enums explicitly. These are contract types, not new tables.

#### API Request Schemas

Define strict per-operation required/nullable fields: trusted scope, command/idempotency IDs, expected revision, title/full prompt/schedule; dispatch adds immutable occurrence/run/conversation correlation; approval/cancel adds attempt/generation and deadlines. Reject unknown fields.

#### API Response Schemas

Define detail/page, durable management receipt, accepted dispatch receipt, event ingestion receipt and privacy-safe errors. List omits full prompt; detail includes it. Acceptance is distinct from completion.

#### Temporary / Internal Shapes

Run snapshot, scoped cursor, result projection and harness evidence. Evidence contains source/image revisions, synthetic labels, overlap intervals and assertion outcomes, never credentials or private transcripts.

#### Service Primitives

Document Cloud revision CAS/occurrence admission, Foundry action fencing and Cloud dedupe/context-insertion acknowledgement. Preserve short transactions and existing lock order; no transaction spans model execution or human wait.

### Plain-language glossary

Profile: shared Ally identity/resources. Session: separate working history. Occurrence: scheduled opportunity. Run: its execution. Attempt: fenced runtime effort. Schema: boundary data; model: persisted row.

### Frontend Interaction Shapes (if applicable)

Not applicable: no interface work. Preserve Full prompt, conversation-led controls, distinct routine activity/results and main-chat approval requirements for clients.

## Phases

### Phase 1 - Contract artifacts and tests

- Add Cloud `docs/contracts/routines-v1.md`, `docs/contracts/fixtures/routines-v1.json`, `backend/allies/tests/test_routines_contract.py`.
- Add a portable contract copy and identical fixtures at the same documentation paths in Foundry, plus `backend/runtime/tests/test_routines_contract.py`. Record shared revision/hash; use generic public-safe examples.
- Supply complete valid envelopes/receipts/errors for every operation, canonical hash vectors, stale/duplicate/unauthorized cases, lifecycle/race and schedule examples. Reuse existing serialization functions; do not add runtime handlers or a schema engine.
- Resolve exact grammar, pagination, retention/capacity evidence, context-insertion acknowledgement and durable approval continuation. Exit: reviewed contract revision and matching vectors; unresolved items explicitly block affected integration.

### Phase 2 - Minimal feasibility evidence

Current constraints are explicit:

- Foundry `backend/runtime/models.py:771`: `ConversationBinding.profile` is one-to-one and primary key. `services/executions.py:126-184,288-333` rejects another conversation for that profile.
- `models.py:1037-1040`: `runtime_lease_profile_unresolved_unique` allows only one ACTIVE/STOPPING lease. `services/claims.py:145-195` skips occupied profiles; lines 355-380 derive claims from the single binding. `services/sessions.py:29` preserves attempt/lease-authorized session CAS.
- `runtime/allies_runtime/hermes.py:360-379` derives distinct stable IDs; `coordinator.py:35-47,112-118` serializes proof turns by profile. Distinct IDs do not prove concurrent execution.
- `runtime/hermes-image/provider/allies_mnemosyne/provider.py:413-510` has isolation/init safeguards and SQLite timeout but skips background contexts; default context_only does not grant writes. Concurrent memory/file mutation remains unproved.

Add Foundry `backend/runtime/tests/test_routine_session_constraints.py`, `runtime/tests/test_routine_session_feasibility.py`, `runtime/hermes-image/smoke_routine_sessions.py`, and `docs/operations/routine-session-feasibility.md`.

1. Assert current binding/lease rejection and claim exclusion using real models/services; keep protections unchanged. Verify stable IDs across retries and distinct conversations/profiles.
2. Probe the pinned local Hermes image directly with one synthetic profile, main session and two routine sessions. Hold routine work with barriers; prove main completion before release, overlapping intervals, correct event identity and no history leakage. Label bypass of Foundry admission explicitly.
3. Use actual provider/file tool paths to test shared authorized memory continuity into a fresh session, cross-profile isolation, concurrent independent writes and conflicting same-file read/modify/write. Detect lost updates; do not use harness-only locks or weakened policy to claim safety.
4. Bound each scenario to 60 seconds and three sessions; clean only harness-created resources. Record actual image digest/source SHA and pass/fail/blocked per property. Pinned Dockerfile references Hermes `36cb5ae5530a75def7df3195e49b7a4aa2add482`, mnemosyne_hermes 0.5.0 and mnemosyne_memory 3.15.1. Missing image/model/provider prerequisites remain unverified, not passed.

Exit: reproducible constraint evidence plus honest live-capability results and the smallest required change boundary. Fakes test harness logic only.

### Phase 3 - Review and handoff

Parent task performs separate correctness/simplicity review and revision-aware Nabu reconciliation after acceptance. CLD-013 receives frozen management/schedule/discovery, occurrence/revision, approval and context-insertion rules. FND-012 receives identical contract/hash and binding/lease/claim/session-CAS evidence; reconcile FND-010 cancellation before replacement.

Minimum future Foundry changes span `backend/runtime/models.py`, migrations, `services/executions.py`, `claims.py`, `sessions.py`, `approvals.py`, runtime contracts and `runtime/allies_runtime/foundry.py`/`hermes.py`; provider/file changes only where the probe demonstrates need. Changing binding alone is insufficient. No such changes occur in CLD-012.

Dependent integration requires actual main-model result insertion, durable 24h approval continuation without whole-prompt restart, effective cancellation before replacement and concurrent sessions with safe resources. Preserve old main-chat identity and same-conversation exclusion. CLD-013/FND-012 may develop against the accepted contract; integrated release depends on both.

## Acceptance Criteria

1. Every matrix area has reviewed schemas/examples/error semantics and matching fixture hashes.
2. Existing chat v1 behavior and engineering safeguards remain intact.
3. Tests reproduce binding/lease/claim constraints; live proof distinguishes supported, failed and unverified capabilities.
4. Handoff names exact source revisions, commands/results, policy resolutions and dependent changes.
5. No production implementation or unsupported claim of product readiness.

## Backend Considerations (if applicable)

### Query Optimization Plan

No query changes. Future discovery uses owner filtering, bounded keyset pages and responsible-Ally join; measure in CLD-013.

### N+1 Prevention

No new production relation access. Future page query count must remain constant; harness workload stays fixed.

### Detailed Unit Test Cases

Cover malformed/unknown/oversized input, owner mismatch, stale revision/generation, identical/changed retry, event reorder, DST gap/fold, latest-missed recovery, one-time pause rejection, paused/skipped nonrecovery, failure without rerun, approval/expiry/replacement race and result arrival during an active main turn.

## Frontend Considerations (if applicable)

### Data Path

Not applicable: contract-only episode; client APIs and presentation are downstream.

### State Management Considerations

No client changes. Preserve schedule/run distinction and pending-versus-persisted outcomes.

## Test Plan

Planning validation: template/scope review and diff check only; no live feasibility or product tests claimed.

Later execution, from the relevant repository root with local test configuration:

```powershell
# Cloud
make check
make lint
make test APP="allies/tests/test_contract.py allies/tests/test_routines_contract.py"
# Foundry
$env:DJANGO_DEBUG = "true"
make check
make lint
make test APP="runtime/tests/test_cld005_contract.py runtime/tests/test_routines_contract.py runtime/tests/test_routine_session_constraints.py"
uv run --locked --project runtime pytest runtime/tests/test_hermes.py runtime/tests/test_coordinator.py runtime/tests/test_routine_session_feasibility.py
make validate
```

Repeat database concurrency assertions on disposable PostgreSQL; SQLite does not prove row-lock behavior. Use locked uv recipes from Makefiles if make is unavailable. Preserve CI, secret scanning, coverage and policy checks.

Proposed harness CLI after implementation: `uv run --locked --project runtime python runtime/hermes-image/smoke_routine_sessions.py --hermes-url <local-endpoint> --timeout-seconds 60`. The implementation must document actual local service/image setup and secure environment configuration, verify this command, and record image digest. Actual provider storage tests may run inside the pinned container; they alone do not prove model responsiveness. Never substitute a mocked transcript for live proof.

## Risks and Mitigations

Primary risks: profile-wide admission still serializes work; memory/files lose updates; existing 300s approvals cannot support 24h durable waits; UI-only results never reach Hermes context. Mitigate with the focused probes and explicit downstream boundaries above. Schedule grammar, retention/capacity and continuation remain engineering freeze prerequisites, not invented product decisions.

Rollback: remove/revert only this episode's documentation/test/harness additions; no runtime migration or deployment rollback exists. Failed probes preserve protections and record required work. Do not claim concurrency by disabling authorization or serializing whole routines against main chat.
