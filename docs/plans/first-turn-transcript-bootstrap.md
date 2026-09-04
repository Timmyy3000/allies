# First-turn transcript bootstrap plan

## Feature overview

- Problem: Cloud durably stores the generated onboarding greeting, but the first Cloud-to-Foundry command carries only the user's reply. Hermes therefore starts from an empty transcript, while the profile materializer incorrectly treats a one-time first-chat instruction as permanent `SOUL.md` policy.
- Target users: people creating an Ally anonymously or while signed in, plus operators responsible for transcript integrity and profile isolation.
- Source docs/specs: the companion work brief; Nabu `projects/allies/index.md`, `projects/allies/engineering/specs/conversation-and-streaming.md`, and `projects/allies/product/allies-first-product-requirements.md`; the Cloud, Foundry, and pinned Hermes sources listed in Evidence.
- Success outcome: the first persisted Hermes session contains the exact Cloud greeting, the user's reply, and the generated response in that order. Replays cannot duplicate or rewrite the greeting, later turns are unchanged, and `SOUL.md` contains only durable behavior.

## User stories

1. As a person creating an Ally, I want its first reply to remember the greeting I saw, so the conversation is coherent whether I began anonymously or while signed in.
2. As a user retrying after a network or worker interruption, I want the same first turn to converge without duplicate transcript rows or a second model stream.
3. As an operator, I want bootstrap failures to be isolated, observable, and reversible without exposing a general transcript-import surface or overwriting custom souls.

## Scope

### In scope

- Add a bounded optional assistant bootstrap object to the existing execution input contract in Cloud and Foundry.
- Attach that object only to the default onboarding conversation's sequence-2 user reply, using the exact persisted sequence-1 assistant message and its UUID.
- Preserve the bootstrap object inside Foundry's existing immutable execution payload, claim, and retry path.
- Extend the PR 21 derived Hermes image with a pinned-source patch that adds one profile-scoped, authenticated, loopback-only bootstrap endpoint and one transactional `SessionDB` primitive.
- Seed the deterministic Hermes session before recording `execution.dispatched`; use one identical retry for an ambiguous endpoint response, then return the attempt to the existing pre-checkpoint retry path.
- Stop appending the legacy first-chat block to new `SOUL.md` files and remove it from existing generated souls only when the file exactly matches bytes deterministically produced from that profile seed.
- Add contract, service, runtime, image, profile-upgrade, and durable-transcript tests; define deployment, rollback, and Enkii review gates.
- After implementation validation, update the two cited Nabu notes to mark transcript bootstrap as accepted and the permanent first-chat block as superseded.

### Out of scope

- A general history-import, message-edit, transcript-repair, or bulk-bootstrap API.
- Direct `allies-runtime` access to Hermes SQLite; new queues, workers, tables, dependencies, or user-visible UI.
- Reworking CLD-009 authentication or onboarding routes. Those routes converge after Cloud has created the same durable conversation rows.
- Importing older Cloud conversation history or retroactively bootstrapping sessions that have already processed a turn.
- Rewriting, normalizing, or adopting ownership of custom or ambiguously edited `SOUL.md` files.

### Dependencies and assumptions

- Foundry PR 21 provides the derived Hermes image and is the base of the Foundry worktree. Before implementation, update PR 21 from current `origin/dev` so it includes the accepted default-soul work; keep this feature stacked until PR 21 merges.
- The derived image remains pinned to Hermes source commit `36cb5ae5530a75def7df3195e49b7a4aa2add482`. The overlay patch must fail the image build if that source no longer matches.
- Cloud's `Message` uniqueness on `(conversation, sequence)`, dispatch outbox bytes, send key, and command fingerprint remain the durability and replay anchors.
- Foundry's deterministic Hermes session candidate, conversation binding CAS, immutable command fingerprint, claim payload, and lease checkpoint rules remain authoritative.
- Hermes requests originate in the same Machine over loopback and use the profile-specific bearer credential. No bootstrap credential is added.
- Legacy commands without `bootstrap` remain valid during rollout. A command that includes bootstrap is accepted only at ordinal 2 and only while the conversation has no established Hermes session.

## Contract and shape definitions

### Function and service shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `allies-cloud/backend/chat/services/dispatch.py` | onboarding bootstrap helper | `_first_turn_bootstrap(message: Message) -> FirstTurnBootstrap | None` | Message must be the default conversation's sequence-2 onboarding reply; sequence 1 must be the stored assistant greeting and match the onboarding attempt | Exact greeting UUID and text, otherwise `None` | One indexed lookup; invariant failures stop dispatch before outbox creation |
| `allies-foundry/backend/runtime/services/executions.py` | command persistence | existing create-or-get execution path with parsed `ExecutionInput.bootstrap` | Bootstrap is optional; if present, ordinal must be 2 and the binding must have no Hermes session | Existing execution result | Persists bootstrap inside immutable `Execution.input_payload`; request fingerprint handles exact retry and mismatch |
| `allies-foundry/runtime/allies_runtime/hermes.py` | profile bootstrap client | `bootstrap_session(profile_id, session_id, bootstrap) -> HermesBootstrapResult` | Canonical profile/session identifiers, UUID message ID, bounded text; same profile bearer auth and canonical JSON bytes on retry | `created` or `duplicate` | Maps `409` to terminal conflict; transport loss is ambiguous and retryable by the worker |
| `allies-foundry/runtime/allies_runtime/worker.py` or current claim runner in `foundry.py` | first-turn pre-dispatch step | `_bootstrap_first_turn(claim, session_id) -> None` | Only when a typed bootstrap is present and the claim has no established session | None after Hermes acknowledgement | Ensures deterministic session, retries the same bootstrap once, then records `execution.dispatched`; unresolved response loss calls existing `stopped` before any checkpoint |
| pinned Hermes `hermes_state.py` through image patch | transcript primitive | `bootstrap_assistant_message(session_id: str, message_id: str, text: str) -> Literal["created", "duplicate"]` | Existing session; bounded exact text; UUID identity; transaction sees either empty history or the exact prior bootstrap row | Created/duplicate result | Owns `BEGIN IMMEDIATE`; inserts one assistant row and updates message count, or raises stable not-found/conflict errors without mutation |
| `allies-foundry/runtime/allies_runtime/profile_store.py` | legacy soul cleanup | existing materialize/reconcile path plus `_clean_owned_first_chat_block(seed, path) -> Literal["clean", "removed", "custom_preserved"]` | Compares bytes with the exact old generated form and the exact clean personality form | Cleanup classification | New profiles write only personality. Existing exact generated files are atomically replaced; every other file is left byte-for-byte unchanged |

### API and transport contracts

| Consumer | Method and path / event | Authentication and authorization | Request schema | Success response schema | Error responses / retry semantics |
| --- | --- | --- | --- | --- | --- |
| Cloud to Foundry | Existing execution command | Existing internal authentication, workspace/profile scoping, send key, and command fingerprint | Existing command; `payload.bootstrap` is optional `FirstTurnBootstrap` | Existing acceptance response | Unknown fields still fail. Exact command replay converges; same idempotency identity with different bootstrap fails through the existing fingerprint conflict |
| Allies runtime to Hermes | `PUT /p/{profile}/api/sessions/{session_id}/bootstrap` | Named profile path, matching profile context, profile-specific bearer key, and loopback peer required | `HermesTranscriptBootstrapV1` | `HermesTranscriptBootstrapResponseV1` | `400/422` malformed, `401` bad bearer, `403` default/out-of-scope/non-loopback, `404` session, `409` nonempty or mismatched history. Only timeout/disconnect gets one identical retry; `409` never retries |

Representative execution payload fragment:

```json
{
  "kind": "execution_input",
  "text": "I need help planning my launch.",
  "bootstrap": {
    "kind": "assistant_message",
    "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
    "text": "Hi, I'm Nova. What are we working on first?"
  }
}
```

`bootstrap` is omitted, not `null`, on every later turn and on legacy commands. Cloud and Foundry cap both user and bootstrap text at the existing 16 KiB command-text limit, reject unknown fields, and include the bootstrap bytes in the existing command fingerprint.

Representative Hermes request and responses:

```json
{
  "schema_version": "v1",
  "kind": "assistant_transcript_bootstrap",
  "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
  "text": "Hi, I'm Nova. What are we working on first?"
}
```

```json
{
  "object": "hermes.session.bootstrap",
  "session_id": "allies-conversation-...",
  "message_id": "8ef84387-581e-4e6f-a31d-6fbca75d95f4",
  "status": "created"
}
```

An exact replay returns `200` with `status: "duplicate"`; the first insert returns `201`. Responses never echo greeting text. The endpoint has no pagination, filtering, delete, update, multi-message, or default-profile behavior.

### Data shapes and invariants

#### Database models

Not applicable. Cloud already stores the greeting `Message`, and Foundry already stores the execution payload as JSON. Hermes uses its existing sessions/messages tables. No migration, index, or new persisted model is needed.

#### Enums

| Type / category | Enum | Location | Members / representation | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- |
| Boundary literal | bootstrap kind | Cloud and Foundry contract modules | `assistant_message` | Only an assistant transcript seed is accepted | Additive optional field |
| Boundary literal | Hermes bootstrap kind | derived-image overlay | `assistant_transcript_bootstrap` | Version `v1` and exact literal required | Private image API |
| Service result | bootstrap status | Hermes overlay/runtime client | `created`, `duplicate` | A duplicate means identity, role, content, and sole-row shape all match | Additive private result |

#### API request schemas

| Type / category | Request schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| Nested command DTO | `FirstTurnBootstrap` | both `backend/.../contracts.py` modules | `kind: Literal["assistant_message"]`, `message_id: UUID`, `text: StrictStr` | All required when object exists; object itself optional | Extra fields forbidden; text nonempty, UTF-8, at most 16 KiB | Absence preserves old commands and later turns |
| Private HTTP DTO | `HermesTranscriptBootstrapV1` | derived-image API patch/runtime client | `schema_version: "v1"`, `kind`, `message_id`, `text` | All required and non-null | Exact fields only; same bounds; path session/profile are authoritative | New private endpoint in derived image only |

#### API response schemas

| Type / category | Response schema | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility notes |
| --- | --- | --- | --- | --- | --- | --- |
| Private HTTP DTO | `HermesTranscriptBootstrapResponseV1` | derived-image API patch/runtime client | `object`, `session_id`, `message_id`, `status` | All required | IDs must equal request/path; unknown or malformed success fails closed | New private endpoint |

#### Temporary / internal shapes

| Type / category | Shape | Location | Fields and types | Lifetime / visibility | Validation, security, and invariants | Compatibility / rotation notes |
| --- | --- | --- | --- | --- | --- | --- |
| Persisted JSON subshape | execution bootstrap | Foundry `Execution.input_payload`, claim payload | `kind`, UUID string, exact text | Execution and retry lifetime; not a database model | Immutable after command acceptance; payload digest and command fingerprint cover it | Old rows have no field |
| Internal image patch | Hermes source overlay | `runtime/hermes-image/patches/first-turn-transcript-bootstrap.patch` | Minimal diff against two pinned upstream files | Build-time only | `git apply --check`/`git apply`; image build fails on source drift | Update intentionally with Hermes pin |

#### Service primitives

| Type / category | Primitive | Location | Signature | Inputs and validation | Return value | Lock/transaction ownership, side effects, and errors |
| --- | --- | --- | --- | --- | --- | --- |
| Service primitive | exact transcript seed | Hermes `SessionDB` overlay | as specified above | Empty session or exact single assistant seed | `created`/`duplicate` | One SQLite write transaction serializes concurrent requests; mismatch never rewrites |
| Service primitive | pre-dispatch bootstrap | runtime worker | as specified above | Persisted claim data and deterministic session | Acknowledged seed | No `execution.dispatched` event until acknowledgement; no model stream on unresolved bootstrap |
| Service primitive | generated-soul cleanup | profile store | as specified above | Exact deterministic old bytes | Classification | Atomic replacement only for proven generated content; uncertain ownership is preserved |

### Plain-language glossary

- Bootstrap: the one assistant greeting inserted into a brand-new Hermes session before the first user reply.
- Checkpoint: a durable Foundry event after which automatic replay could produce a second external action. Here it is `execution.dispatched`.
- Exact retry: the same method, path, profile, session ID, message ID, text, and canonical JSON bytes.
- Established session: a conversation binding already has a Hermes session, or Hermes reports any transcript state other than the exact bootstrap row.
- Overlay: a small patch applied to the pinned Hermes source during the derived-image build, without maintaining a general Hermes fork.

### Frontend interaction shapes

Not applicable. Both onboarding entry paths already produce the same Cloud conversation and messages. No UI state, component, route, or client payload changes.

## Phases

### Phase 0 - Rebase the image foundation

- Goal: put the work on a current, reviewable base.
- Work items: update Foundry PR 21 from current `origin/dev`; resolve its overlap with the merged default-soul work; rerun PR 21 checks and terminal Enkii reviews; keep this feature branch based on the refreshed PR 21 head.
- Impacted systems: Foundry branch topology only.
- Exit criteria: PR 21 is mergeable and green, and this branch contains both the derived image and current default-soul behavior.

### Phase 1 - Add the fail-closed Hermes capability

- Goal: make Hermes the sole transcript writer for one initial assistant message.
- Work items: add the pinned-source patch and build-time drift check; add the transactional SessionDB primitive; add the profile-only route, bearer and loopback checks, strict request parsing, stable error codes, and response DTO; extend image smoke tests to inspect durable history after create, exact retry, mismatch, nonempty session, wrong profile, wrong auth, and unprefixed/non-loopback requests.
- Impacted files/systems: Foundry `runtime/hermes-image/Dockerfile`, a new `patches/` file, image tests/workflow, and pinned Hermes API/session source through the overlay.
- Exit criteria: the image build proves the patch applies to the pin, all negative cases leave history unchanged, and SQLite history contains one exact assistant row after duplicate requests.

### Phase 2 - Carry the immutable contract through Foundry

- Goal: preserve and validate bootstrap data from command acceptance to the runtime claim.
- Work items: add matching strict contract types; validate ordinal 2 and no bound session; include the object in `Execution.input_payload`; verify request fingerprint and payload digest mismatch behavior; expose it unchanged in claims; update the public Cloud-Foundry contract fixture.
- Impacted files/systems: Foundry contract, execution, claim, serializer, and tests.
- Exit criteria: absent bootstrap remains compatible, exact retries return the existing execution, and late/mismatched requests fail before a claim is produced.

### Phase 3 - Bootstrap before the no-replay checkpoint

- Goal: close the response-loss window without risking a second stream.
- Work items: add the Hermes client method; ensure the deterministic session before dispatch; call bootstrap and accept `created` or `duplicate`; retry one timeout/disconnect with identical bytes; if acknowledgement remains unknown, call existing `stopped` while the attempt is still pre-checkpoint so the lease returns to queued work; record `execution.dispatched` only after bootstrap acknowledgement, then start the existing stream exactly once. Treat contract, auth, scope, conflict, and malformed-success errors as terminal pre-dispatch failures.
- Impacted files/systems: Foundry runtime Hermes client, claim runner, and runtime tests.
- Exit criteria: a lost first response followed by duplicate acknowledgement succeeds once; two lost responses requeue without a stream; a later claim converges through the same bootstrap identity.

### Phase 4 - Keep SOUL durable and preserve custom files

- Goal: remove the one-time instruction from managed soul materialization.
- Work items: make new materialization write only `seed.personality`; retain the seed field as a compatibility input for existing profiles rather than adding a data migration; during reconciliation, construct the exact legacy generated bytes from the stored seed; atomically remove the suffix only when the entire file equals that form; accept already-clean content; preserve every other byte sequence as custom/uncertain; surface cleanup write failures as repair-required rather than claiming success.
- Impacted files/systems: Foundry profile store and tests. The accepted default-soul renderer from `origin/dev` remains the source for new durable behavior.
- Exit criteria: new files have no first-chat block, exact generated files become clean, and edited/custom/marker-like files remain byte-identical.

### Phase 5 - Attach the exact Cloud greeting

- Goal: make the existing first dispatch the synchronization boundary.
- Work items: add the matching DTO; resolve the sequence-1 assistant message while constructing the sequence-2 onboarding command; verify it belongs to the same default conversation and onboarding attempt; serialize its UUID and exact stored text into the outbox command; leave later and non-onboarding commands unchanged; extend fixtures and service tests.
- Impacted files/systems: Cloud execution contracts, conversation/dispatch services, public contract fixture, and tests.
- Exit criteria: both anonymous and signed-in creation produce the same bootstrap command, an invariant mismatch stops dispatch, and an outbox retry reuses byte-identical command data.

### Phase 6 - Integrate, deploy, and record the decision

- Goal: roll out in a compatibility-safe order and capture durable proof.
- Work items: merge/deploy PR 21 first; retarget/rebase the feature Foundry PR onto `dev`; merge/deploy Foundry before Cloud; deploy Cloud; run one anonymous and one signed-in canary; inspect Cloud rows, Foundry execution/events, and Hermes durable messages; update the Nabu conversation spec and first-product requirements with accepted/superseded status and implementation references.
- Impacted systems: Foundry, Cloud, deployment evidence, and Nabu.
- Exit criteria: both canaries show one greeting and ordered durable history, required checks pass, and Enkii is terminal with no unresolved P0-P2 findings.

## Acceptance criteria

1. The first onboarding reply carries the exact persisted Cloud greeting and UUID.
2. Hermes durable history is assistant greeting, user reply, generated assistant response, in order.
3. Exact bootstrap retry leaves one greeting row and opens at most one model stream.
4. Different text or identity, a late ordinal, an established/nonempty session, malformed data, invalid auth, non-loopback access, and the wrong/default profile all fail without transcript mutation.
5. Later turns omit bootstrap and follow the current session path unchanged.
6. New managed profiles write only durable soul content.
7. Existing exact generated souls are cleaned atomically; custom and uncertain files are byte-identical after reconciliation.
8. Anonymous and signed-in onboarding converge on the same runtime contract and show one visible greeting.
9. Cloud and Foundry checks pass, image tests cover the private endpoint, and an end-to-end proof checks durable transcript order.
10. PR 21 lands first; the feature Foundry PR is then retargeted to `dev`; Cloud targets `dev`; all required CI and terminal Enkii code, policy, and security reviews pass without unresolved P0-P2 findings.

## Backend considerations

### Query optimization plan

- Cloud adds at most one indexed `(conversation_id, sequence=1)` lookup while building the first onboarding command. Cache/use the already loaded conversation and onboarding attempt; do not add per-message relation walks.
- Foundry reuses the conversation binding and execution transaction already used during command acceptance. The bootstrap adds no list query or polling query.
- Hermes checks the target session and at most the first two message rows inside one existing `BEGIN IMMEDIATE` write transaction. It does not scan other sessions or profiles.
- Expected steady-state change is zero queries for later turns. Measure first-turn query counts in focused tests and watch bootstrap latency/error counters during canaries.

### N+1 prevention

- The Cloud helper is invoked for one outbound message, not a collection. Tests should assert the first-turn query budget and no change for later dispatch.
- Foundry claim serialization reads the existing JSON payload and adds no ORM relation access.
- Hermes queries one session by primary key and its own ordered messages. No cross-profile query is permitted.

### Detailed unit test cases

- Happy path: exact Cloud row selection; contract round trip; first insert; duplicate response; worker proceeds to one stream; ordered persistent history.
- Validation: empty/oversized/non-string text, bad UUID, unknown fields, unsupported version/kind, ordinal other than 2, bound session, malformed success response.
- Auth and isolation: missing/wrong bearer, path/profile mismatch, default-profile path, other named profile, and non-loopback peer.
- Idempotency: duplicate command, duplicate claim, concurrent identical bootstrap, same message ID with different text, different ID with same text, and existing unrelated message.
- Failure paths: session creation loss, first bootstrap response loss then duplicate, two response losses then pre-checkpoint requeue, SQLite error rollback, cleanup write failure, and no stream/event checkpoint before acknowledgement.
- Soul safety: new profile, exact old generated content, already-clean content, custom prefix/suffix/edit, marker text in custom content, missing files, and repeated reconciliation.

## Frontend considerations

### Data path

The user action, Cloud routes, visible conversation response, loading states, and client mapping are unchanged. The new data path begins after Cloud has persisted the greeting and first user reply: Cloud outbox command to Foundry execution JSON to claim payload to the runtime's private Hermes bootstrap request.

### State management considerations

Not applicable to frontend state. Cloud remains the visible source of truth; Hermes holds a private runtime copy of the greeting for model context.

## Test plan

- Unit tests: focused Cloud contract/dispatch tests; Foundry contract/execution/claim/client/worker/profile-store tests; patched Hermes SessionDB and handler tests.
- Integration/API tests: build the derived image, start it with named profiles and per-profile keys, create a deterministic session, call bootstrap twice, send the user turn, and inspect `/messages` plus the profile SQLite database.
- Regression checks: commands without bootstrap; ordinary later turns; existing request fingerprint conflicts; lease stop/requeue rules; memory-provider behavior from PR 21; default-soul tests; anonymous/native onboarding tests.
- Manual verification: capture correlation ID, Cloud greeting UUID/text, Foundry execution and event order, Hermes session ID, durable role/content order, absence of duplicate stream, and redacted logs for both onboarding paths.
- Cloud commands: `make check`, `make lint`, `make test APP=chat`, plus the focused onboarding/dispatch test modules.
- Foundry commands: `make check`, `make validate`, `make lint`, `make test APP=runtime`, `make runtime-lint`, `make runtime-test`, `make hermes-image-build`, and `make hermes-image-test`.
- Artifact checks: compare Markdown and HTML hashes across repositories; compare Markdown `##` sections with HTML `section[data-plan-section]`; search HTML for external brand names, logos, copied product tokens, and decorative triangle marks; run the Lavish narrow/mobile layout audit.

## Rollout, monitoring, and rollback

1. Land and deploy the refreshed PR 21 image foundation. Do not merge the stacked feature if PR 21 checks or Enkii reviews regress.
2. Deploy Foundry support first. It accepts both legacy commands without bootstrap and new commands with bootstrap.
3. Deploy Cloud second. Existing immutable outbox commands remain legacy; newly created first-turn commands carry bootstrap.
4. Canary one anonymous and one signed-in Ally. Required evidence: bootstrap `created` or `duplicate`, `execution.dispatched` after bootstrap acknowledgement, exactly one stream start, and durable role order `assistant,user,assistant`.
5. Monitor low-cardinality counts for created, duplicate, conflict, auth/scope rejection, ambiguous response/requeue, terminal bootstrap failure, and soul cleanup result. Logs include correlation/profile/session/message IDs but never greeting text, bearer keys, or soul contents.
6. Roll Cloud back first to stop producing bootstrap fields. Foundry remains backward compatible. If the private endpoint or runtime is faulty, roll Foundry back to the PR 21 image and worker together. Do not roll back by deleting Hermes rows or replaying a post-dispatch attempt.
7. A seeded-but-unacknowledged attempt remains safe: the old Cloud/Foundry path may be paused while operators inspect it; the new runtime can resume it through exact duplicate acknowledgement. A session with conflict is quarantined for manual diagnosis, never rewritten.

## Enkii terminal review criteria

- Review the refreshed PR 21, the stacked Foundry feature PR, and the Cloud PR. Each required code, policy, and security review must reach a terminal passing state.
- Re-run Enkii after any change to the overlay, auth/scope checks, transaction logic, checkpoint ordering, fingerprint behavior, soul cleanup, or deployment sequence.
- Merge is blocked by an unresolved P0, P1, or P2; a nonterminal review; skipped required check; merge conflict; or a finding that transcript mutation, tenant isolation, exact retry, or custom-soul preservation is not proven.
- Record the terminal review URL/status and CI run for each PR in execution notes. A prior 5/5 result on PR 21 is evidence only for that prior head and must be renewed after the base update.

## Risks and mitigations

- Response loss after insert: one identical retry returns `duplicate`; continued ambiguity uses pre-checkpoint `stopped`, so no stream has started and a later claim can retry safely.
- Concurrent or mismatched bootstrap: Hermes serializes the empty-check and insert in one write transaction; only the exact sole row converges.
- Excessive mutation surface: the route accepts one assistant message only for an empty named-profile session over loopback with existing bearer auth.
- Upstream drift: the image applies a minimal patch to the exact pinned commit and fails its build on a rejected hunk. Upgrading Hermes requires deliberate patch/test review.
- Stacked-branch drift: refresh PR 21 from `dev`, keep the feature stacked for review, then rebase and retarget immediately after PR 21 merges.
- Legacy commands during rollout: optional absence remains valid. Deploy Foundry first and Cloud second.
- Custom soul damage: only a whole-file exact match to deterministic legacy output is rewritten. Ambiguous content is preserved, and write failure is surfaced.
- Partial rollback: Cloud can stop sending the optional field independently; Foundry image and worker roll back together; durable transcript rows are never deleted as rollback.

## Evidence inspected

- Repository guidance: workspace and both repository `AGENTS.md` files, both `ENGINEERING_STYLE.md` files, plan templates, READMEs, Makefiles, Foundry runtime README, Enkii policy guidance, and current CI/image workflows.
- Cloud implementation: conversation creation and activation, dispatch/outbox serialization, execution contracts, onboarding services/models, and related tests.
- Foundry implementation: contracts, execution acceptance, claims, leases/checkpoints, runtime client/worker, profile store, derived-image Dockerfile/tests, and PR 21 branch history against current `origin/dev`.
- Hermes pin: API route registration, profile middleware/authentication, session create/messages/chat handlers, and `SessionDB` transaction/message primitives at commit `36cb5ae5530a75def7df3195e49b7a4aa2add482`.
- Nabu: Allies index, accepted conversation/streaming decisions, and first-product onboarding requirements. The implementation must update those notes only after validation.

## Open decisions

None required before implementation. The plan selects the narrow pinned-source overlay, PUT contract, empty-or-exact transaction rule, and pre-dispatch retry checkpoint. If implementation evidence shows the pinned Hermes image lacks a reliable loopback peer signal, stop and return for design review rather than weakening the isolation requirement.
