# Automatic Workspace Activation

## Status

- Type: bug
- Implementation delegation: always
- Delegation source: kickoff default/configured workflow
- Planning worker: sol_planning_worker
- Planning worker source: `.agent/kickoff.yaml`
- Review worker: sol_review_worker
- Review worker source: `.agent/kickoff.yaml`
- Implementation worker: luna_execution_worker
- Implementation worker source: `.agent/kickoff.yaml`
- Planning mode: fast
- Worktree manager: forest
- Branch: fix/automatic-workspace-activation
- Worktree path: `E:/Users/Oluwatimilehin/Documents/Programming/helpers/allies-cloud/.forest/worktrees/fix/automatic-workspace-activation`
- Task workspace: `docs/plans/`
- Created: 2026-09-02
- Current phase: planning

## Objective

Ensure a newly bootstrapped Cloud workspace is automatically activated in Foundry/Fly before its first Ally is considered ready, and provide a safe recovery path for existing workspaces and provisioning operations left pending or repair-required.

## Context

Cloud already creates an idempotent personal workspace during account bootstrap. Cloud then sends profile provisioning to Foundry. Foundry currently registers the workspace/profile and returns `pending`; the local live runbook separately invokes `activate_fly_workspace`, which creates the Fly app, volume, Machine, Hermes, and `allies-runtime`. Railway staging runs the Foundry API and Postgres but does not invoke that activation workflow. PR18 correctly renders the resulting retryable state.

## Requirements

- Preserve one workspace per account and existing Ally/binding/operation identity.
- Reuse the existing Foundry workspace lifecycle and Fly provider safely and idempotently.
- Make first-workspace activation automatic in the staging/production path.
- Recover existing pending/retryable records and previously terminal records caused by the old Foundry contract mismatch through an explicit, scoped operation.
- Keep Cloud state truthful while activation/materialization is in progress.
- Add tests covering the real orchestration boundary, retry/defer behavior, idempotency, and recovery.

## Acceptance Criteria

- A new account receives a usable personal Cloud workspace.
- Creating its first Ally causes Foundry activation to run without an operator command.
- Fly resources are created/resumed once per workspace and include Hermes plus `allies-runtime`.
- The Ally becomes bound only after Foundry reports an active/materialized profile.
- Existing pending/retryable workspaces recover automatically or through the documented repair operation.
- Existing `repair_required` records from the known 422 contract failure can be safely requeued without duplicate records.
- Cloud, Foundry, and Interface contract tests pass; staging validation can prove the first-workspace path.

## Evidence And Sources

- Cloud workspace bootstrap: `backend/workspaces/services/bootstrap.py`
- Cloud provisioning dispatch: `backend/allies/services/provisioning.py`
- Foundry profile endpoint: `backend/runtime/api/register.py`
- Foundry workspace lifecycle: `backend/runtime/services/workspaces.py`
- Existing activation command: `backend/runtime/management/commands/activate_fly_workspace.py`
- Local live procedure: Foundry `docs/operations/local-fly-docker.md`
- Railway staging process configuration: Cloud `docs/operations/railway-staging.md`
- Nabu: Allies CLD-003/CLD-004 and Foundry continuity notes

## Decisions

- Primary implementation repositories: `allies-foundry` and `allies-cloud`.
- `allies-interface` is not in the initial write scope; it already consumes provisioning state and should only change if the reviewed recovery UX requires it.
- Use the existing Fly per-workspace runtime topology; do not add a generic shared Railway runtime worker without architectural justification.

## Risks

- Fly activation is externally effectful and must be bounded, idempotent, and safe under concurrent Cloud retries.
- Existing terminal records must not be bulk-reset without an explicit error-code scope and dry-run evidence.
- Railway stores deployment configuration outside Git; infrastructure changes may require a separate reviewed Railway configuration update.

## Open Questions

- Where should automatic activation run: synchronously in Foundry registration or through a durable Foundry activation worker/task?
- How are Fly/provider credentials and immutable Hermes/runtime images supplied to the deployed Foundry service?
- Should Interface expose a user-facing retry action, or should Cloud recovery remain automatic plus operator-controlled?

## Plan

To be produced by the configured fast planning worker and independently reviewed before implementation.

## Execution Notes

The current Cloud worktree contains unrelated chat retry changes; implementation must use the isolated kickoff worktree and preserve those changes in the original checkout.
