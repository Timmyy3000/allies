---
name: adversarial-review
description: Run an independent adversarial review of an engineering work brief, implementation plan, investigation output, or delivery proposal through a configurable dedicated worker. Use when a workflow needs a fresh-agent critique before accepting a plan, especially from $kickoff after $plan-it creates a plan. Supports harness-native worker selection shared with or separated from implementation. Produces structured findings that can be fed back into planning, not implementation changes.
---

# Adversarial Review

Review a proposed plan or finding set from a skeptical, evidence-driven perspective. The output is meant to be read by the calling workflow and fed back into planning before execution.

Do not implement fixes. Do not rewrite the plan unless explicitly asked. Identify gaps, contradictions, weak assumptions, missing validation, and risks.

## Dedicated Review Worker

When the active harness can spawn workers, run this review in a fresh dedicated worker session. Keep the current agent as the orchestrator. A fresh session is required for independence even when the same worker is used for both review and implementation.

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

### First-Use Bootstrap

Resolve the active harness and worker before dispatching:

1. Honor an explicit worker choice supplied for this task.
2. Read and validate `plan_review.workers.<harness>` when it exists.
3. When no review selector exists but `ship_it.workers.<harness>` does, discover the existing selector and ask whether to reuse it or configure a separate review worker. If the user chooses reuse, copy only that exact selector into `plan_review.workers.<harness>`.
4. If named workers are supported but none is selected, discover available native workers before asking the user to select or confirm one. If none is suitable, ask for the name, model, supported reasoning level, and personal or project scope, explain the native definition that must be created, create the smallest valid definition, and validate it.
5. If the harness dispatches directly by model, ask for the model and supported reasoning level, validate them, and store only `model` plus optional `reasoning_effort`.
6. Update only the active harness entry in the existing `kickoff.yaml`, preserving all other keys, including `ship_it` and other harnesses.

Do not create `.agent/` or `.agents/` solely for worker configuration when the repository has no such convention. Do not configure inactive harnesses. Do not ask for model or reasoning settings when the user selects an existing named worker.

Revalidate the saved selector before every review. If a named worker is unavailable or invalid, do not add overrides or substitute another worker silently; ask whether to repair it or choose a replacement. If the harness cannot spawn workers, do not create invalid configuration. Run in the current session only as an explicit fallback and state that the review was not independent.

When dispatching, pass only:

- This skill.
- The work brief.
- The plan, investigation output, or proposal under review.
- Relevant source specs, tickets, logs, screenshots, docs, or code references.
- The specific question to answer.

Tell the worker to read the supplied artifacts, make no implementation changes, spawn no additional workers, and return only the structured review below. Do not pass private orchestrator conclusions, intended fixes, or expected findings. The point is an independent review, not confirmation.

## Review Goals

Evaluate whether the plan or proposal is good enough to proceed.

Look for:

- Requirements missing from the plan.
- Acceptance criteria that are vague, untestable, or absent.
- Phases that do not map back to the objective.
- Hidden dependencies, sequencing issues, or cross-repo coordination gaps.
- Risks around data integrity, permissions, migrations, rollout, rollback, performance, observability, support, and operations.
- Test plans that are missing, too broad, too narrow, or not tied to risk.
- Unproven assumptions or source material that was not used.
- Timeline claims that do not match scope or validation needs.
- Places where the plan is overbuilt for the stated goal.
- Places where the plan is under-scoped for production readiness.

## Work-Type Lenses

For `feature` work, challenge:

- User workflow coverage.
- Permission, empty, loading, error, retry, and edge states.
- Rollout, analytics, documentation, and support needs.
- Whether the plan describes what users can actually do when complete.

For `bug` work, challenge:

- Whether the bug is reproduced before fixing.
- Whether expected behavior is stated clearly.
- Whether there is a regression test or equivalent verification.
- Whether the fix could mask symptoms without addressing cause.
- Whether severity and release urgency match the proposed path.

For `improvement` work, challenge:

- Whether the baseline is known.
- Whether the target outcome is measurable.
- Whether the measurement method can prove before/after change.
- Whether tradeoffs are explicit.
- Whether the plan confuses activity with improvement.

For `refactor` work, challenge:

- Whether behavior-preservation boundaries are explicit.
- Whether tests prove no behavior changed.
- Whether the refactor scope is too broad.
- Whether rollout or migration risk exists despite "no behavior change" claims.

For `hotfix` work, challenge:

- Whether the plan is small enough for urgency.
- Whether rollback and mitigation paths are credible.
- Whether validation is sufficient for production risk.
- Whether follow-up cleanup is tracked separately.

For `investigation` work, challenge:

- Whether the stated question is actually answered.
- Whether evidence is cited and traceable.
- Whether confidence level is clear.
- Whether unknowns and follow-up questions are explicit.
- Whether recommended next steps are justified by the evidence.

For `exploration` work, challenge:

- Whether the timebox is clear.
- Whether decision criteria are clear.
- Whether prototype work is isolated from production work.
- Whether the output can support a decision.

## Severity

Classify findings:

- `Blocker`: proceeding is likely to fail, produce the wrong outcome, or create serious production/review risk.
- `Major`: should be fixed before execution unless the user explicitly accepts the risk.
- `Minor`: useful improvement, clarification, or tightening.
- `Question`: needs user or owner input.

Do not inflate severity. A finding is only a blocker when it materially prevents responsible execution.

## Output Format

Return only a structured review:

```markdown
# Adversarial Review

## Verdict

<Ready / Needs revision / Blocked>

## Findings

| Severity | Area | Finding | Evidence | Recommendation |
| --- | --- | --- | --- | --- |
| Blocker/Major/Minor/Question | <area> | <specific issue> | <brief source reference> | <actionable next step> |

## Missing Questions

- <question that must be answered, if any>

## Plan Feedback For Revision

- <specific change to feed back into the plan>

## Confidence

<High / Medium / Low> - <one sentence reason>
```

If there are no meaningful findings, say `Ready` and explain the residual risk or test gap in one sentence.

## Handoff Back To Caller

The calling workflow should read this output, update the work brief with accepted findings, and feed `Plan Feedback For Revision` back into the planner. After revising the plan and recording finding dispositions, pass the revised plan, this complete review, and those dispositions to `simplicity-review` before approval or execution.
