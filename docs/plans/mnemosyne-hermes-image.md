# Mnemosyne-enabled Allies Hermes image Plan

## Feature Overview

- Problem: The pinned Hermes image has no Allies-controlled durable memory policy or isolated Mnemosyne provider configuration.
- Target users: Allies profiles and operators running Hermes on Foundry Machines.
- Source docs/specs: `.agent/mnemosyne-hermes-image.md`; `docs/adr/0001-two-container-tenant-machine.md`; `runtime/allies_runtime/config.py`; `runtime/allies_runtime/profile_store.py`; `projects/allies/engineering/specs/foundry-continuity-layer.md`; Nabu `meta/hermes-memory-policy.md`; pinned Hermes commit `36cb5ae5530a75def7df3195e49b7a4aa2add482`.
- Success outcome: A reproducible, provenance-labelled derived image starts with the unchanged Hermes `/init`, discovers an Allies wrapper plus pinned Mnemosyne packages, and gives every newly materialized profile fail-soft, policy-compliant, isolated memory.

## User Stories

1. As an Ally, I want relevant durable context recalled invisibly, so that conversations remain continuous without exposing memory tools.
2. As an Ally, I want memory outages or rejected writes not to interrupt a conversation, so that the primary Hermes path remains available.
3. As an operator, I want immutable image provenance, resource measurements, and rollback to the previous digest, so that deployment is auditable.

## Scope

### In Scope

- Derived Hermes image from official digest `sha256:b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca`, with pinned Mnemosyne/wrapper wheels and lock hashes.
- Allies-owned provider wrapper registered through Hermes' existing plugin/provider interface; `context_only` and `narrow_tools` modes.
- Foundry profile seed/config/manifest/fingerprint changes for provider selection, policy version, allowlist, and profile-local SQLite storage.
- Retention gate, fail-soft lifecycle, per-profile cleanup, unit/integration/image/live-smoke tests, resource measurement, rollout and rollback runbooks.

### Out of Scope

- Hermes or Mnemosyne source forks, upstream patches, or changes to `allies-runtime` sidecar/API, approvals, sessions, or tool executor.
- Nabu activation, shared-memory/subagent/cron memory, local-LLM consolidation, automatic migration of an existing shared database, or Cloud PR #21.

### Dependencies and Assumptions

- Hermes provider contract at the pinned commit remains the compatibility target; its memory manager allows one external provider and routes only advertised schemas.
- Initial candidate is the published `mnemosyne-hermes==0.5.0` with a tested `mnemosyne-memory` release (candidate `3.15.1`); exact pair and hashes are an exit criterion, not an assumption.
- Fly Machine volume `/opt/data` is the durable boundary and only the active fenced Machine writes it. Existing profile cleanup removes the entire profile tree.
- Python/runtime image and registry credentials are available in CI. Alpha targets the production Fly architecture first; a second architecture is added when required, with separate per-platform provenance retained.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `runtime/allies_runtime/memory_policy.py` (new) | `AlliesMnemosyneProvider.initialize` | `initialize(session_id: str, **kwargs) -> None` | Require `hermes_home`, immutable profile identity, `agent_context`; reject paths outside profile root; set `profile_isolation=true`, no shared surface | None; provider availability state | Opens profile-local DB; catches dependency/IO errors and marks unavailable |
| same | `get_tool_schemas` | `get_tool_schemas() -> list[dict]` | Mode is `context_only` or `narrow_tools`; validate names against schemas discovered from the selected Mnemosyne wheel | `[]` for context-only, explicit approved schemas otherwise | Never advertises stock broad/default tools |
| same | `has_tool` / `handle_tool_call` | `has_tool(name: str) -> bool`; `handle_tool_call(name: str, arguments: dict) -> str` | Check allowlist before dispatch; reject hidden names, cross-bank/path arguments, oversized or secret-bearing payloads | JSON `tool_rejected` or `memory_unavailable` on fail-soft; delegated result on success | No exception reaches conversation loop; writes pass retention gate |
| same | `prefetch` / `sync_turn` / `shutdown` | Existing Hermes `MemoryProvider` signatures | Bound query/content bytes and latency; context skip roles; no raw autosave | Prompt block/None; None; None | Prefetch is recent/relevant only; sync persists approved facts only; lifecycle failures logged safely |
| `runtime/allies_runtime/profile_store.py` | `ProfileSeed` and `_build_profile` | Existing seed/build APIs with additive memory fields | `memory_provider`, `memory_mode`, `memory_policy_version`, `memory_tool_allowlist`; bounded enum/list; no secrets | Existing receipt/manifest plus memory config | Writes `memory:` YAML and policy metadata atomically; fingerprint changes on policy changes |
| `runtime/allies_runtime/reconciliation.py` | `_runtime_seed` | Existing mapping from desired profile to `ProfileSeed` | Version desired-state contract; default safe policy for old callers | `ProfileSeed` | Reconcile remains idempotent and fenced |

### API and Transport Contracts

No new public HTTP, webhook, queue, or stream endpoint. Hermes localhost transport and the two-container topology remain unchanged. Provider errors are internal structured tool results and sanitized wide events; they are not retried as conversation requests. Profile desired-state/config changes are additive and versioned; old profiles remain readable until explicitly re-materialized.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `MemoryPolicy` | `runtime/allies_runtime/profile_store.py` or `memory_policy.py` | `provider: str`, `mode: Literal[context_only,narrow_tools]`, `policy_version: str`, `tools: list[str]`, `profile_isolation: bool`, `sync_roles: list[str]` | Provider/mode/version required; default `mnemosyne`, `context_only`, current policy; tools/sync empty in alpha | Provider fixed to wrapper; tools subset of discovered schemas; isolation and shared-surface-off are mandatory | Additive seed fields; manifest schema bump; old manifests re-materialize only on generation change |
| Generated `config.yaml` | profile root | `memory.provider: allies_mnemosyne`; `memory.mnemosyne.profile_isolation: true`; `shared_surface_read: false`; `tools: []` or approved list; `sync_roles: []` | Safe context-only defaults | No absolute host paths, credentials, Nabu settings, or broad `tools: null` | Existing model/credential/SOUL fields unchanged |
| Profile memory storage | `<volume>/profiles/<ally-key>/mnemosyne/...` | SQLite DB, provider metadata, optional embeddings files | Created only inside profile root; one writer | Resolve real path and reject traversal/symlink escape; bank name derived from immutable Ally key | Cleanup deletes with profile tree; no automatic import from shared DB |
| `.allies-profile.json` | profile root | Existing fields plus `memory_policy_version`, `memory_mode`, sorted `memory_tools`, storage-relative identifier | Required for completed generation | Fingerprint includes all policy/config values; no secrets or DB contents | Bump manifest schema and retain receipt compatibility |

### Frontend Interaction Shapes (if applicable)

Not applicable; this is a runtime/image feature with no UI or client API.

## Implementation Shape and Policy

The image build context should live in a new repository-owned directory (recommended `runtime/hermes-image/`; settle naming in Phase 1). Its Dockerfile must `FROM` the exact official digest, preserve the base entrypoint and `/init`, install the locked wrapper and Mnemosyne wheels into the sealed Hermes environment (or the pinned image's supported plugin directory), and emit OCI labels for Hermes source SHA, base digest, package versions/hashes, wrapper revision, build workflow, SBOM and license notices. Build and publish a digest-only artifact for the production Fly architecture first; when a second platform is required, run the same context with an explicit platform command (for example `docker buildx build --platform linux/arm64`) and record its platform digest/provenance separately. Do not alter the sidecar Dockerfile or topology.

`AlliesMnemosyneProvider` delegates only the pinned provider lifecycle. It must set the effective DB path under the current profile root and fail closed if Mnemosyne falls back to `~/.mnemosyne` or a shared bank. `context_only` returns no schemas while retaining bounded prefetch; `narrow_tools` uses an explicit versioned allowlist (recommend recall, explicit remember/canonical update/invalidate/forget only) and excludes shared/export/import/sync/diagnostic/LLM tools. `has_tool` and `handle_tool_call` enforce the same list so hidden dispatch is rejected even if Hermes routes it. All write paths redact/reject secrets and raw transcripts, enforce byte/count limits, and return sanitized fail-soft results.

Retention defaults follow Nabu policy: persist only explicit remember requests, stable preferences/corrections, recurring constraints/relationships/environment, durable decisions, sourced knowledge, or task progress whose loss harms future help. Never persist secrets, recovery data, raw conversations, tool traces, guesses, one-off calculations, or completed status/artifact identifiers. Corrections supersede/invalidate the exact old record. Shared surfaces, subagent/cron sync, automatic raw capture, auto-sleep and local-LLM consolidation are disabled for alpha. Nabu remains user-enabled and is not initialized by this provider.

## Phases

### Phase 1 - Lock contracts and release

- Goal: Resolve package pair, image directory/registry owner, storage layout, and alpha mode.
- Work items: Verify published wheel metadata/imports against Python 3.13 and pinned Hermes; write policy/version and allowlist; record ADR/provenance fields and migration stance.
- Impacted files/systems: `docs/plans/mnemosyne-hermes-image.md`, optional ADR, `runtime/allies_runtime/config.py` constants.
- Exit criteria: Maintainer decisions recorded; compatibility matrix and resource baseline plan accepted; no implementation begins with unknown provider API.

### Phase 2 - Derived image and discovery

- Goal: Build a reproducible image whose `/init` and plugin discovery are unchanged.
- Work items: Add Dockerfile/build context, lock/hashes, wrapper package, OCI labels/SBOM/license output, production-architecture CI workflow and digest publication; test entrypoint and real imports. Keep the build inputs ready for a later second-architecture job.
- Impacted files/systems: `runtime/hermes-image/**` (or agreed path), `.github/workflows/hermes-image.yml`, `Makefile` image targets, registry.
- Exit criteria: Alpha build succeeds on the production Fly architecture with pinned provenance, hash-locked/offline wheels, SBOM, and one clean rebuild; provider appears in Hermes discovery/status; base `/init` PID1 and two-container spec remain intact. A second architecture is a beta gate unless operational demand promotes it earlier.

### Phase 3 - Foundry profile isolation

- Goal: Materialize policy and durable storage per Ally.
- Work items: Extend `ProfileSeed`/desired-state mapping, YAML serializer, manifest schema/fingerprint, reconcile idempotency, path/symlink checks, cleanup and generation migration behavior.
- Impacted files/systems: `runtime/allies_runtime/profile_store.py`, `reconciliation.py`, config/contracts, profile-store tests.
- Exit criteria: Two profiles have distinct DB paths and cannot cross-recall; restart preserves one profile's facts; old model/credential/SOUL behavior and receipts remain valid.

### Phase 4 - Wrapper and test matrix

- Goal: Enforce tool/retention policy without Hermes/Mnemosyne forks.
- Work items: Implement provider adapter, schema filtering, hidden-dispatch rejection, argument/path sanitization, explicit-write gate, fail-soft lifecycle and bounded logging; add fake-provider and real-package tests.
- Impacted files/systems: Allies wrapper module/package, runtime unit tests, Hermes integration tests in sibling `hermes-agent` (read-only reference; changes, if any, are upstream-owned and out of this repo).
- Exit criteria: Context-only advertises zero tools; narrow mode exposes only approved schemas; rejected/hidden calls cannot delegate; unavailable DB/embedding never fails stream; policy tests cover secrets/raw transcript rejection.

### Phase 5 - Proof and measurement

- Goal: Produce evidence before changing deployed digest.
- Work items: Build/import tests, FND-004-style live smoke with two profiles and restart/replacement, read-only/full-disk fail-soft test, resource benchmark against official image and candidate dependency profiles, plus a short soak at expected staging load.
- Impacted files/systems: `backend/runtime/services/hermes_smoke.py`, continuity proof/runbook, `runtime/tests/**`, CI artifacts, Fly staging Machine.
- Exit criteria: All repository checks pass; live proof shows topology/session/approval/tool/sidecar invariants; image size, RSS/PSS, DB growth, write/recall latency, CPU and first-token overhead are recorded with agreed thresholds and the production architecture label. The two-profile isolation/restart test and short staging-load soak pass.

### Phase 6 - Staged rollout and rollback readiness

- Goal: Safely promote or disable the derived digest.
- Work items: Publish candidate digest, deploy staging with new profiles/context-only, observe memory-unavailable and latency metrics, then promote; document drain/restart requirement for frozen Hermes prompts.
- Impacted files/systems: `runtime/allies_runtime/config.py`, Fly activation config/runbooks, release provenance record.
- Exit criteria: Operator sign-off on acceptance matrix; rollback tested by restoring prior official digest/config and preserving isolated DBs.

## Acceptance Criteria

1. A reproducible alpha derived image is built for the production Fly architecture from the official pinned digest, with exact package hashes, SBOM/license/provenance labels, one clean rebuild, and a discoverable wrapper/provider. A second architecture has equivalent per-platform provenance when required; bit-for-bit multi-build equality is a beta hardening gate.
2. Newly materialized profiles select the wrapper, use policy versioned config, and store Mnemosyne only under their own profile root; no cross-profile reads/writes occur.
3. Context-only exposes no Mnemosyne tools. Narrow mode advertises only the approved allowlist and rejects hidden, cross-bank, oversized, or secret-bearing dispatch.
4. Approved memory survives Hermes restart and Machine replacement on the same volume; memory DB/disk/provider failures fail soft and do not fail a conversation.
5. Hermes `/init`, sessions, approvals, normal tools, localhost transport, sidecar, leases/fencing, and cleanup semantics remain unchanged.
6. Unit, real-import/integration, image, live-smoke, and resource evidence pass before any production digest change.

## Backend Considerations (if applicable)

### Query Optimization Plan

- Hotspots/endpoints: No new backend endpoint; profile materialization and Hermes localhost calls are the hot paths.
- Query-shape choices: Mnemosyne owns bounded top-k recent/relevant retrieval; wrapper caps bytes/results and avoids unbounded graph/shared queries.
- Expected query-count change: One bounded prefetch per eligible turn and explicit tool calls only; measure p50/p95 latency and DB growth against no-provider baseline.
- Measurement/monitoring plan: Wide events record mode, provider availability, latency bucket, result count and reason code without content, profile key, DB path, or secrets.

### N+1 Prevention

- Relation access map: Not applicable to Django relations; ensure no per-token/provider call loop.
- Prefetch/select plan per endpoint/service: Single lifecycle prefetch/sync per turn; no synchronous embedding or consolidation on the streaming critical path.
- N+1 regression guardrails: Unit call-count assertions and p95 budget in live smoke.

### Detailed Unit Test Cases

- Happy path: provider discovery, context prefetch, explicit remember/recall, restart persistence.
- Validation and bad input: unknown tool, hidden tool, cross-bank/path argument, oversized payload, secret pattern, malformed profile policy.
- Auth/RBAC boundaries: profile identity is derived from Foundry seed; no user-controlled bank/path or Nabu activation.
- Idempotency/retry behavior: materialize/reconcile twice, provider initialize retry, Machine replacement; no duplicate writes or manifest drift.
- Failure-path behavior: missing package, DB locked/read-only/full disk, embedding unavailable, shutdown exception; stream remains successful with sanitized event.

## Frontend Considerations (if applicable)

Not applicable.

## Test Plan

- Unit tests: `runtime/tests/test_profile_store.py`, `test_profile_reconciliation.py`, `test_config.py`, new wrapper policy/dispatch tests with fake provider.
- Integration/API tests: Real pinned Hermes/Mnemosyne imports in temporary `HERMES_HOME`; plugin discovery, MemoryManager routing, provider lifecycle, profile restart.
- Regression checks: Existing Hermes smoke/continuity, two-container spec, credential socket, session/approval/tool behavior, no sidecar diff.
- Manual verification checklist: inspect image labels and digest; run `/init` as PID1; `hermes memory status`; verify context-only tool list; run two-profile isolation and restart; induce DB failure; inspect sanitized events; confirm cleanup.
- Commands: `make check`; `make validate`; `make runtime-test`; `make lint`; `make runtime-lint`; targeted `pytest runtime/tests/test_profile_store.py runtime/tests/test_profile_reconciliation.py`; Hermes `scripts/run_tests.sh`; `docker buildx build --platform <production-fly-platform>` (alpha); optional deferred `docker buildx build --platform <second-platform>` when operationally required; `docker buildx imagetools inspect <digest>`; container import/status smoke; FND-004 staging proof command with immutable `HERMES_IMAGE`.

## Resource Measurement

Measure official-image baseline and each candidate dependency profile on the target production Fly machine: compressed/uncompressed image size, cold start and `/init` readiness, idle and two-stream RSS/PSS, CPU, first-token overhead, prefetch/recall p50/p95, SQLite growth/write latency, embedding cold-start/download, and failure recovery. Alpha uses deterministic two-profile isolation/restart plus a short expected-staging-load soak; the 50-profile/24-hour soak is deferred to beta. Record architecture, machine size, package lock, image digest, sample count and thresholds; do not enable embeddings/local LLM until measured capacity and cost are accepted.

## Rollout, Rollback, and Migration

- Publish a candidate digest/tag separately; deploy staging with immutable `HERMES_IMAGE` and feature setting for new profiles only. Start context-only, observe latency/error/resource events, then consider narrow mode.
- Existing legacy profiles are left untouched in alpha. A single explicit restart/re-materialize gate opts a profile into the new generation; frozen sessions stay on the legacy generation until that gate. Never silently mutate a live profile generation, merge databases, or export/import data. A full migration state machine and operator command suite is a beta project.
- Roll back by restoring the prior official Hermes digest and disabling provider config for new generations; preserve Mnemosyne DBs for diagnosis/re-enable. If schema/API incompatibility exists, quarantine the DB and do not auto-export/import or delete it.
- Machine replacement uses the same `/opt/data` volume and must pass isolation/restart proof before promotion. Rollback restores the prior digest/config and leaves any new DB read-only for diagnosis.

## Risks and Mitigations

- Risk: Stock Mnemosyne capture stores raw or sensitive interaction data. Mitigation: wrapper write gate, `sync_roles=[]`, bounded/redacted explicit writes, no shared surface; fail closed on uncertainty. Rollback: context-only or provider disabled.
- Risk: Sealed Hermes venv/entrypoint or entry-point discovery differs by release. Mitigation: build against pinned commit with real import/discovery and PID1 smoke; keep wrapper in supported plugin path. Rollback: previous digest.
- Risk: Package/API drift or unpinned transitive dependency. Mitigation: exact wheel hashes, lockfile, compatibility matrix, SBOM and CI rebuild.
- Risk: Embeddings inflate image/RAM/cold start. Mitigation: smallest supported profile first, measure before enabling; feature-disable embeddings/local LLM.
- Risk: Cross-profile bank collision/path escape. Mitigation: immutable Ally-key-derived bank, profile-root realpath check, `profile_isolation=true`, symlink tests, one-writer fencing.
- Risk: Existing sessions retain stale prompt/config. Mitigation: generation/restart gate and explicit migration runbook.
- Risk: Memory failures are hidden operationally. Mitigation: sanitized reason-coded wide events and availability/latency/resource alerts without content.

## Open Decisions

1. Exact published Mnemosyne pair and extras (candidate 0.5.0 + 3.15.1): choose by Python 3.13 import/discovery, image/RAM, recall latency and license/SBOM review.
2. Alpha mode: recommend `context_only`; enable narrow allowlist only after product confirms explicit memory UI/need.
3. Write policy: recommend wrapper gate plus `sync_roles=[]`; decide whether any safe automatic fact extraction is acceptable later.
4. Storage layout: recommend profile-root `mnemosyne` home and immutable Ally-key bank; no automatic migration from shared DB.
5. Image registry, CI workflow owner, multi-arch builder and digest promotion authority.
6. Embeddings, auto-sleep/consolidation and local LLM: disabled until resource/cost evidence and privacy review.
7. Source of policy defaults: recommend versioned Foundry `ProfileSeed` with image-safe defaults, overridable only by an authenticated product contract.

## Validation Basis and Evidence Inspected

- Repository instructions: root and Foundry `AGENTS.md`, `ENGINEERING_STYLE.md`, `docs/templates/PLAN_TEMPLATE.md`, Makefile and `.github/workflows/ci.yml`.
- Foundry code/tests: `runtime/allies_runtime/config.py`, `profile_store.py`, `reconciliation.py`, `composition.py`, `runtime/Dockerfile`, profile/reconciliation/config/Hermes/smoke tests, `backend/runtime/services/hermes_smoke.py`, `continuity_proof.py`, `docs/adr/0001-two-container-tenant-machine.md`.
- Hermes pinned source: `agent/memory_provider.py`, `memory_manager.py`, `agent_init.py`, `plugins/memory/__init__.py`, `tool_executor.py`, and repository `AGENTS.md` at commit `36cb5ae5530a75def7df3195e49b7a4aa2add482`.
- Mnemosyne source/package evidence: upstream Hermes integration README and provider source; published wheel metadata for `mnemosyne-hermes==0.5.0` and `mnemosyne-memory==3.15.1`; package profile/resource documentation. Current upstream main (0.7.0 integration) is not a production pin.
- Allies Nabu: `projects/allies/index.md`, Foundry continuity/conversation and Hermes/Fly references, decision log, roadmap, and canonical `meta/hermes-memory-policy.md` (read-only; no Nabu mutation required).
- Validation basis is the existing CI/test contracts plus the proof and measurement commands listed above. No implementation code was changed or committed by this planning task. Kickoff remote version preflight was unavailable/malformed and did not affect repository evidence collection.

## Adversarial Review Revisions (accepted execution gates)

The review found the original plan directionally complete but insufficiently executable at several boundaries. The following safeguards are now mandatory plan gates; they do not expand the product scope.

### Provider discovery and precedence (Phase 1 gate)

- Record the exact pinned Hermes loader path and precedence: bundled `plugins/memory/<name>` versus `$HERMES_HOME/plugins/<name>`, package entry points (`hermes_agent.plugins` and `hermes_agent.memory_providers`), and `memory.provider` config selection. Run a probe in the derived container that prints the resolved module/version and source path, then assert `allies_mnemosyne` wins over a same-named user plugin and that an unrecognized provider fails closed.
- Test the effective config precedence (profile `config.yaml` > process environment > image defaults, as implemented by the pinned Hermes commit) with conflicting values. Assert `memory.tools` gating cannot re-enable wrapper tools in context-only mode.
- Extend the image status proof to assert provider name, availability, mode, effective profile DB root, and zero shared-surface/subagent registration; do not treat an import-only check as discovery proof.

### Implicit capture and background-write proof (Phase 4 gate)

- Inventory every selected Mnemosyne wheel path that can write SQLite: `sync_turn`, lifecycle hooks (`on_session_end`, `on_session_switch`, `on_context_compress`, delegation hooks), prefetch/consolidation/auto-sleep, scratchpad/graph helpers, and provider shutdown/flush. Pin the inventory to the package hash and fail CI if a new write-capable hook appears without policy review.
- In the wrapper, bypass or no-op automatic sync/consolidation/background hooks for the alpha policy (`sync_roles=[]`, auto-sleep/consolidation disabled). Explicit writes pass the retention gate only. Context-only may read bounded recent/relevant records but must not write.
- Use the real package against a temporary SQLite DB and attempt forbidden inputs (raw transcript, tool trace, secret, one-off calculation, artifact/commit identifier). Query SQLite tables and filesystem after every lifecycle hook; assert forbidden bytes/identifiers are absent, including after shutdown, cancellation, and restart.

### Race-safe profile storage (Phase 3 gate)

- Define the invariant: `realpath(effective_db)` must remain beneath the generation's profile root, be keyed by the immutable Ally/profile key, and be opened only after the generation fence is acquired; no two active writers may share a DB.
- Materialization/reconcile and provider initialization must re-check generation/lease ownership immediately before opening SQLite. A concurrent replacement either completes before open or returns a fenced/stale-generation result without touching the new generation.
- Add a deterministic concurrent test: two threads/processes repeatedly reconcile, replace, initialize, write, and clean the same profile while a second profile operates independently. Assert no cross-profile rows, no stale writer writes, atomic manifest/fingerprint, and cleanup leaves no open DB handles.

### Alpha migration gate (Phase 6)

Do not build a full migration state machine or operator command suite for alpha. Legacy profiles remain untouched. An explicit, idempotent `re-materialize-and-restart` operation creates a new isolated generation, fences the old writer, validates the manifest/policy, restarts Hermes to reload its frozen prompt/provider state, and then runs the two-profile isolation/restart proof. If validation fails, the old generation remains authoritative and the new DB is quarantined read-only. There is no silent merge, export, or import. Track the full inspect/prepare/activate/verify/rollback state machine as a beta migration project.

### Hermetic reproducible image build (Phase 2 gate)

- Pin the base digest, package wheels and hashes, Python/toolchain versions, Docker Buildx/BuildKit versions, and CI action SHAs (checkout, setup, build/push, attestation/SBOM). Build with an offline wheelhouse (`--no-index --require-hashes`) and no network-dependent post-install scripts.
- Set `SOURCE_DATE_EPOCH` from the reviewed source commit timestamp; normalize file ownership, mtimes, locale, archive ordering and wheelhouse paths. Emit deterministic OCI labels and in-toto/SLSA attestation subjects containing base digest, source SHA, lock hash, wrapper revision and workflow run.
- Alpha performs one clean rebuild and compares source/lock inputs, SBOM package set, labels, and attestation subject. Resolve known nondeterministic labels (timestamps, workflow IDs, builder metadata) or document their normalization before release. Bit-for-bit layer/config equality across two builds is a beta hardening gate. When a second architecture is added, record each platform digest and provenance separately.

### Complete MemoryProvider fault boundaries (Phase 4 gate)

Test the adapter boundary and every hook actually invoked by alpha `context_only` (initialization, schema discovery, prefetch, prompt block, turn/session lifecycle and shutdown). Inject representative synchronous exception, `asyncio.CancelledError`, timeout, malformed schema/result, and oversized result; include a real-package SQLite locked/read-only/full-disk fault. The wrapper must bound/cancel work, return sanitized unavailable/rejected results, and never leak an exception or cancellation into Hermes. Keep an inventory of all other Mnemosyne write-capable/background hooks and require rollout sign-off that they are bypassed; defer the full Cartesian narrow-mode hook matrix to beta.

### Schema and argument/result integrity (Phase 4 gate)

- At build time, record a canonical sorted JSON hash of the selected Mnemosyne tool schemas and package version. At runtime, recompute and refuse narrow mode if the hash differs from the reviewed allowlist fixture.
- Validate arguments against each allowlisted JSON schema (types, required fields, maximum lengths, enum values); strip/reject bank/path/author/shared-surface overrides. Validate delegated results against a bounded result schema, truncate/redact unexpected fields, and return `tool_error`/`tool_rejected` for malformed output.

### Privacy-safe observability ownership (Phases 4–5)

- Generate a per-operation correlation ID (opaque UUID/ULID) at Foundry boundary and propagate it to wrapper events; never use Ally IDs, DB paths, prompts, tool arguments, or memory text as metric labels.
- Foundry owns provider availability, policy-rejection, latency and profile-generation metrics; image/infra CI owns build reproducibility, digest, SBOM and resource metrics; Fly operations owns alert routing and rollback. Define alerts for sustained provider-unavailable, policy-rejection spikes, p95 prefetch/recall latency, image drift, RSS/CPU budget breach and DB growth/quota breach.

### Alpha retention limits and soak (Phase 5 gate)

- Enforce maximum record/result bytes and a hard per-profile SQLite size guard. On exhaustion, reject the write/read with a reason code and continue the conversation; do not invent eviction or compaction policy in alpha.
- Run deterministic two-profile isolation/restart and a short soak at expected staging load. Measure DB growth, write latency, recall p95, RSS/PSS, file descriptor/open-handle count, and cleanup time. Defer the 50-profile/24-hour soak and any eviction policy to beta.
