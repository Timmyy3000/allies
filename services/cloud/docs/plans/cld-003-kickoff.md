# CLD-003 Create and Manage a Real Ally

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: workflow default, existing repository kickoff configuration
- Planning worker: configured `codex` selector from `docs/plans/kickoff.yaml`
- Planning worker source: repository configuration
- Review worker: configured `codex` selector from `docs/plans/kickoff.yaml`
- Review worker source: repository configuration
- Implementation worker: configured `luna_execution_worker` selector from `docs/plans/kickoff.yaml` (native `gpt-5.6-luna`, max reasoning)
- Implementation worker source: repository configuration
- Planning mode: full; cross-repository lifecycle, persistence, authorization, and provider-contract work
- Worktree manager: forest
- Branch: ft/cld-003
- Worktree path: E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\cld-003
- Task workspace: E:\Users\Oluwatimilehin\Documents\Programming\helpers\allies-cloud\.forest\worktrees\ft\cld-003\docs\plans
- Created: 2026-08-21
- Target date: not specified
- Current phase: implementation

## Objective

Implement CLD-003 so authenticated onboarding creates one durable, Workspace-owned Cloud Ally with an immutable, idempotent Cloud-to-Foundry profile binding and truthful provisioning outcomes. Preserve the current official onboarding preview greeting and user reply into the real conversation after authentication, without importing or reconciling historical waitlist data.

## Context

The canonical Nabu specification is `projects/allies/engineering/specs/cld-003-create-and-manage-real-ally.md` and is Ready for Plan. The delivery ticket is `projects/allies/delivery/tickets/cloud/CLD-003.md`. Dependencies are AUTH-001, FND-006, and FND-008. Affected systems are `allies-cloud` and the Foundry provisioning contract; CLD-004 owns the ongoing conversation lifecycle.

## Requirements

- Inspect current Cloud and Foundry code, repository instructions, templates, migrations, API conventions, and validation commands before planning.
- Define Cloud Ally identity, user-visible onboarding fields, lifecycle/provisioning states, and immutable binding invariants.
- Add authenticated Workspace-scoped create/retrieve behavior with privacy-safe cross-Workspace denial.
- Define and version the Cloud-to-Foundry provisioning gateway contract, including idempotent success, pending, retryable failure, incompatible binding, and repair outcomes.
- Require sign-in/sign-up before production creation; retain only the current official onboarding preview exchange.
- Keep Foundry/Hermes/private runtime identifiers and credentials out of Cloud public responses, logs, and evidence.
- Exclude waitlist claim/import/reconciliation, post-creation editing, frontend layout, and the full conversation/streaming lifecycle.

## Acceptance Criteria

1. Same official onboarding route for first-time and previous waitlist visitors.
2. Name, job, exact personality text, and appearance are collected and editable before creation.
3. No production Ally, Workspace binding, or Foundry profile exists before authentication.
4. Current onboarding preview greeting and user reply become ordered real conversation turns after authentication.
5. No historical waitlist lookup, claim, import, or reconciliation.
6. One durable Workspace-owned Ally and one immutable binding are created.
7. Same accepted retry is idempotent; same retry identity with different content conflicts without mutation.
8. Cloud reports truthful structured success/failure and never success without matching Foundry evidence.
9. No silent rebinding; later retrieval returns the same Ally state.
10. Cross-Workspace access cannot read, mutate, retry, or infer existence.
11. Public and diagnostic surfaces expose no private provider identifiers or credentials.
12. No product-facing Ally count limit is introduced; only bounded input, rate, and cost protections apply.

## Evidence And Sources

- Nabu `projects/allies/index.md`, `projects/allies/delivery/now.md`
- Nabu `projects/allies/delivery/tickets/cloud/CLD-003.md`
- Nabu `projects/allies/engineering/specs/cld-003-create-and-manage-real-ally.md`
- Nabu `projects/allies/engineering/specs/foundry-continuity-layer.md`
- `AGENTS.md`, `ENGINEERING_STYLE.md`, `docs/templates/PLAN_TEMPLATE.md`, `Makefile`, `README.md`

## Decisions

- Use a full plan with Lavish presentation and independent adversarial and simplicity reviews.
- Start from Cloud `dev` in an isolated Forest worktree; leave unrelated dirty changes in the original checkout untouched.
- Cloud remains the product truth; Foundry is reached only through a versioned gateway.

## Risks

- Cross-repository contract drift between Cloud and Foundry.
- Duplicate or conflicting retries under concurrent requests.
- Truthful handling of partial provisioning and repair without leaking provider details.
- Conversation handoff sequencing across authentication and creation.

## Open Questions

- None blocking implementation. Repository evidence may still narrow transport details without expanding the accepted contract.

## Plan

Planning worker to produce the complete implementation plan and matching HTML artifact under `docs/plans/`, following `PLAN_TEMPLATE.md` and the full-plan content standard.

## Execution Notes

- 2026-08-21: product owner accepted the revised minimal plan and authorized shipping.
- 2026-08-21: repaired the stale implementation selector from `luna_max` to the existing native `luna_worker`; its native definition owns the Luna model and max reasoning setting.
- 2026-08-21: adopted the updated repository worker set: `sol_planning_worker`, `sol_review_worker`, and `luna_execution_worker`; native definitions remain the sole model/reasoning source.
- 2026-08-21: implementation delegation remains `always`; Ponytail Full is required in every implementation packet.

## Adversarial Review Dispositions

- Blocker accepted: persist API idempotency-key identity separately from content fingerprint with Workspace/user uniqueness and race tests.
- Major accepted: authenticate and bind the non-waitlist onboarding handoff through a server-issued, expiring, single-use contract; reject forged or replayed content.
- Major accepted: gate Cloud implementation on an executable, owned, versioned Foundry provisioning contract and rollout sequence.
- Major accepted, then simplified by owner: persist dispatch state, lease, retry/backoff, and expiry directly on `ProvisioningOperation` and run it through existing Celery/beat; no outbox model.
- Major accepted, then simplified by owner: retain the current greeting/reply through the single opaque onboarding attempt; ongoing conversation lifecycle remains outside this ticket.
- Major accepted: specify tenant-safe operation lookup and field-level diagnostic redaction with captured-log tests.
- Minor accepted: regenerate HTML from final Markdown and run content-parity, forbidden-branding, and layout audits.

## Simplicity Review Dispositions

- Keep separate idempotency identity and request fingerprint, authenticated handoff verification, executable Foundry gate, durable operation dispatch safety, and tenant-safe redaction.
- Simplify dispatcher scope to the existing Cloud Celery worker/beat with operation-owned leases, bounded backoff, and expiry; no outbox or new dispatcher framework.
- Simplify feature validation to focused risk tests plus required repository checks; keep artifact parity/layout audits in the plan-document workflow.
- Do not mint speculative conversation rows or identifiers; this slice only associates the accepted opaque onboarding attempt with the Ally.
- Owner decisions were resolved by the product-owner simplification: opaque DB attempt, operation-owned retry state, existing Celery/beat, and no separate CLD-004 receipt in this slice.

## Product-owner simplification feedback

Accepted on 2026-08-21:

- Reuse an AuthFlow-style opaque, expiring, single-use database record for the onboarding attempt; associate it with the Ally after authentication. Do not introduce a signed-token issuer/audience/key/nonce protocol or a second handoff receipt model.
- Keep dispatch lease, attempt, retry, and expiry fields on `ProvisioningOperation`; use the existing Celery worker and beat. Do not create `ProvisioningOutbox`.
- Retry by repeating the original create request with the same `Idempotency-Key`; do not add a dedicated retry service, request schema, or endpoint.
- Use one typed `provision_profile()` HTTP function; do not create a one-implementation gateway class.
- Use the existing service-bearer mechanism. Keep typed request/receipt schemas and one checked JSON fixture as the authoritative Foundry contract representation.
- Keep operation/binding state authoritative and derive the public Ally state. Do not maintain three synchronized state machines.
- Use `select_related()` for the singular retrieve path. Add query-count assertions only after a measured regression.
- Keep focused model, service, API, contract, and concurrency tests plus existing repository checks. Remove duplicate hardening, coverage, snapshot, secret-scan, and manual-verification gates.
- Roll out in three steps: deploy the Foundry contract, migrate Cloud, enable the route. No new feature-flag framework or synthetic dispatcher canary.
- Store no private provider reference unless implementation proves reconciliation requires one.
- Ticket identifiers may appear in delivery and planning references only. Do not use ticket names in code symbols, runtime schemas, routes, migrations, events, or contract filenames.
