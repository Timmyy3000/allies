# Routine management from ordinary Hermes chat

Route: fast; implementation and reviews performed directly, per owner instruction.
No new service, scheduler, secret, or dependency. Cloud owns routine state.

## Approach and boundaries

Add the Allies routines plugin to the existing derived Hermes image. Ordinary
Cloud-backed claims carry a signed per-attempt capability; the runtime passes it
as private request context. Foundry validates the live lease, generation and
profile before forwarding the bound message, binding and command fingerprint to
Cloud. Credentials and identity are not model-selected arguments. Routine streams
receive no management capability. Hosted local cron is disabled.

Use Hermes' real tool-call ContextVar for replay identity, including its deferred
tool bridge. Supply system instructions for immediate clear-request creation,
future-self prompts, explicit schedule and browser timezone, and later-turn
deletion confirmation. The browser timezone remains fixed on the saved schedule.

Preserve the accepted Cloud workspace ID on routine execution using the existing
cloud_workspace_id column. Outgoing result/approval scopes use that snapshot.
Legacy executions without it retain their previous scope; no historical event
fingerprints are rewritten. This fixes rejection when Cloud and Foundry IDs differ.

## Evidence and review

- Backend full suite: 646 passed, 13 skipped; Django and migration checks, Ruff pass.
- Runtime full suite: 623 passed, 5 skipped; final tool-focused tests: 2 passed.
- Both Docker images build; Hermes image smoke executes actual plugin discovery
  and the deferred tool bridge, verifies retry identity, and excludes local cron.
- Local Docker/PostgreSQL integration: tool creation, duplicate replay, timed
  admission, separate run claim, typed result, HTTP publication and main-chat
  insertion passed. Model input and business outcome were scripted.
- Direct correctness review found and fixed Cloud dispatch-byte erasure handling
  and Cloud/Foundry workspace-ID correlation; regression tests cover both.
  Direct simplicity review retained existing services and transport. No unresolved
  P0–P2 finding identified; no independent reviewer delegated.

## Rollout and limits

Merge/promote Cloud first, then Foundry and both published runtime images, and web
timezone support. Existing image reconciliation updates the test Ally. No manual
routine release digest or new Railway service is needed. Verify a real-model
create-and-trigger conversation in staging after promotion. No merge/deploy here.
Rollback these adapters/images; preserve saved Cloud routines and scheduling.
