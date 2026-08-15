---
name: simplicity-review
description: Run an independent simplicity review of an engineering work brief and revised implementation plan after adversarial review through a configurable dedicated worker. Use when a workflow needs a fresh-agent check for overengineering before plan approval or implementation while preserving requirements, accepted risk controls, and repository policies. Supports harness-native worker selection shared with or separated from implementation. Produce structured simplification findings, not implementation changes.
---

# Simplicity Review

Review a proposed plan for unnecessary complexity after its correctness and risk gaps have been challenged. Seek the least complicated solution that fully satisfies the current problem.

Do not implement changes or rewrite the plan. Return evidence-backed recommendations to the calling workflow.

## Dedicated Review Worker And Inputs

When the active harness can spawn workers, run this review in a fresh dedicated worker session. Keep the current agent as the orchestrator. Fresh means independent, not blind. Use a new worker session for this review even when adversarial review or implementation uses the same named worker.

Use the repository's existing agent-workspace convention and its single `kickoff.yaml`. Store one harness-native review selector under `plan_review.workers`; that selector is shared by `adversarial-review` and `simplicity-review`:

```yaml
version: 1
plan_review:
  workers:
    <harness>:
      agent: "<native-agent-name>"
ship_it:
  workers:
    <harness>:
      agent: "<same-or-different-native-agent-name>"
```

Each harness entry must use exactly one selector:

- `agent`: an exact harness-native named worker. Its native definition is the source of truth for model, reasoning, instructions, and other settings.
- `model`: a direct per-spawn model selector, with optional `reasoning_effort`, only when the harness does not require named workers.

To share a worker with implementation, use the exact same selector in `plan_review.workers` and `ship_it.workers`. To use a separate review worker, configure different selectors. Never combine `agent` and `model`, duplicate a named worker's settings in `kickoff.yaml`, or persist the current orchestrator.

Resolve the active harness and worker before dispatching:

1. Honor an explicit worker choice supplied for this task.
2. Read and validate `plan_review.workers.<harness>` when it exists.
3. When no review selector exists but `ship_it.workers.<harness>` does, discover the existing selector and ask whether to reuse it or configure a separate review worker. If the user chooses reuse, copy only that exact selector into `plan_review.workers.<harness>`.
4. If named workers are supported but none is selected, discover available native workers before asking the user to select or confirm one. If none is suitable, ask for the name, model, supported reasoning level, and personal or project scope, explain the native definition that must be created, create the smallest valid definition, and validate it.
5. If the harness dispatches directly by model, ask for the model and supported reasoning level, validate them, and store only `model` plus optional `reasoning_effort`.
6. Update only the active harness entry in the existing `kickoff.yaml`, preserving all other keys, including `ship_it` and other harnesses.

Do not create `.agent/` or `.agents/` solely for worker configuration when the repository has no such convention. Do not configure inactive harnesses. Do not ask for model or reasoning settings when the user selects an existing named worker.

Revalidate the saved selector before every review. If a named worker is unavailable or invalid, do not add overrides or substitute another worker silently; ask whether to repair it or choose a replacement. If the harness cannot spawn workers, do not create invalid configuration. Run in the current session only as an explicit fallback and state that the review was not independent.

Require the calling workflow to pass:

- This skill.
- The original work brief and acceptance criteria.
- The revised plan under review.
- The adversarial-review output and the disposition of each meaningful finding.
- Relevant repository instructions, conventions, source documents, and code references.
- A short instruction to assess whether the plan solves the problem with the least necessary complexity.

Do not accept the calling agent's private conclusions, expected findings, or preferred simplifications. Read the supplied evidence and inspect referenced repository files before judging the plan.

Tell the worker to make no implementation changes, spawn no additional workers, and return only the structured review below. Pass the complete adversarial review and finding dispositions as evidence, not as the expected conclusion.

If required inputs are missing, return `Needs context` and list only the missing material.

## Review Priority

Apply this order of precedence:

1. Explicit requirements and acceptance criteria.
2. Repository policies and established conventions.
3. Correctness, security, data integrity, compatibility, and operational safety.
4. Accepted adversarial-review concerns.
5. Simplicity and implementation economy.

Treat an accepted adversarial concern as an outcome that must remain protected, not necessarily as an implementation that must be preserved verbatim. Recommend a simpler mitigation only when it addresses the same concern. Never silently remove a requirement, repository constraint, risk control, or accepted finding to make the plan smaller.

## Review Method

Trace every proposed component, abstraction, dependency, phase, migration, configuration option, and cross-system interaction to at least one of:

- A current requirement or acceptance criterion.
- A demonstrated risk or failure mode.
- A repository policy or established local pattern.
- An accepted adversarial-review concern.

Challenge items that lack that traceability. Look especially for:

- New abstractions, services, layers, or dependencies where an existing pattern is sufficient.
- Speculative scale, reuse, extensibility, configurability, or edge cases not required now.
- Broad refactors bundled into a focused feature, bug fix, or improvement.
- Parallel mechanisms, compatibility paths, flags, or fallbacks without a concrete need.
- Excessive phase splitting or coordination overhead for a small change.
- Validation work that is duplicative rather than risk-based.
- Custom infrastructure that recreates repository capabilities.

Do not equate fewer files or fewer lines with better design. Keep complexity that reduces real risk, follows the codebase's architecture, or makes the required behavior clearer and safer.

For each concern, identify the smallest alternative that preserves behavior, constraints, and validation. Prefer deferring unrelated work over expanding the current scope.

## Classification

Classify each reviewed item as:

- `Keep`: The complexity is justified. Preserve it.
- `Simplify`: The same required outcome can be achieved with less machinery.
- `Remove/Defer`: The item has no demonstrated current value or belongs in separate follow-up work.
- `Conflict`: Simplification would weaken a requirement or risk control, or the supplied inputs disagree and need an owner decision.

Do not manufacture findings to appear useful. A lean plan may receive a `Lean` verdict with no simplification findings.

## Output Format

Return only a structured review:

```markdown
# Simplicity Review

## Verdict

<Lean / Simplification recommended / Needs decision / Needs context>

## Findings

| Classification | Plan area | Evidence | Recommendation | Preserved outcome |
| --- | --- | --- | --- | --- |
| Keep/Simplify/Remove or Defer/Conflict | <item> | <requirement, policy, risk, or source> | <specific action> | <behavior or safeguard retained> |

## Protected Complexity

- <non-obvious complexity that must remain and why>

## Plan Feedback For Revision

- <specific revision for the calling planner>

## Residual Risk

- <risk that remains after the recommended simplification>

## Confidence

<High / Medium / Low> - <one sentence reason>
```

Include only meaningful `Keep` items in `Protected Complexity`; do not inventory the whole plan. If the verdict is `Lean`, state why in one sentence and leave revision feedback empty.

## Handoff Back To Caller

Require the calling workflow to reconcile every `Simplify`, `Remove/Defer`, and `Conflict` finding. Feed accepted revision feedback back into the planner, preserve protected complexity, and record rejected feedback with a reason.

Do not start implementation while a material `Conflict` remains unresolved. Re-run this review only when revisions materially change the architecture, scope, or risk controls.
