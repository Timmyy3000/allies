---
name: ship-it
description: Execute a defined product or engineering problem from an accepted full or fast-path plan through implementation, pull request readiness, and review monitoring. Use when the user says "Ship it," asks to execute an agreed plan, or arrives from $kickoff with implementation delegation set to never, auto, or always. Support harness-agnostic worker configuration and delegated implementation without changing independent plan-review behavior.
---

# Ship It

Take a reviewed plan from execution handoff through implementation, local review, pull request creation, and review monitoring. Keep the current agent as orchestrator and use implementation workers only when the resolved delegation preference permits them.

## Required Handoff

Read and preserve these inputs when `kickoff` provides them:

- Accepted Lavish plan or reviewed fast-path Markdown plan.
- Work brief and task-workspace path.
- Adversarial and simplicity review decisions.
- Worktree manager, branch, and worktree path.
- Planning mode.
- Implementation delegation: `never`, `auto`, or `always`.
- Delegation source: task choice, repository default, or fallback default.
- Repository `kickoff.yaml` path when present.
- Validation expectations, risks, and open questions.

If invoked directly, find the existing brief and plan. If no executable plan exists, create a proportionate plan before implementation: route substantial, ambiguous, or risky work through the full planning and review workflow; allow a concise Markdown plan for small, clear, low-risk work. Do not replace a reviewed fast-path plan with HTML merely because this skill was invoked.

## Workflow

### 1. Confirm The Execution Contract

- Read the plan, brief, accepted review findings, repository instructions, and relevant source evidence.
- Confirm that requirements, acceptance criteria, scope, validation, and unresolved risks are executable.
- Do not reopen settled planning decisions unless repository evidence reveals a material conflict.

### 2. Prepare The Repository

- Continue inside the kickoff-provided worktree when one exists.
- When Forest manages the worktree, use Forest status and mark commands; do not manually rewrite or remove Forest state.
- Inspect the branch and working tree and preserve unrelated user changes.
- Create a feature branch by repository convention only when kickoff did not already create one.
- Keep all implementation, worker coordination, integration, and validation in the same task worktree.

### 3. Resolve Implementation Delegation

Treat implementation delegation as separate from adversarial and simplicity review. It controls only workers used to execute the accepted plan.

Resolve the mode in this order when kickoff did not already provide it:

1. Explicit task-specific user choice.
2. Saved `implementation_delegation_default` in the discovered repo-level `kickoff.yaml`.
3. `always`.

When a direct `ship-it` invocation contains an explicit lasting instruction, persist it in `kickoff.yaml` using kickoff's folder and preservation rules before resolving the task.

Apply the modes as follows:

- `never`: spawn no implementation workers. Execute in the current orchestrator.
- `auto`: lean toward workers when at least one bounded task can run independently without creating file or dependency conflicts. Record the decision and rationale.
- `always`: delegate at least one bounded implementation task. Do not silently fall back to orchestrator-only execution when workers are unavailable.

Accept legacy `solo` as `never` and `subagents` as `always`, but write only current values.

Read [references/delegation.md](references/delegation.md) completely when `auto` selects workers or the mode is `always`. Harness-native worker selectors live under `ship_it.workers` in that same `kickoff.yaml`. Do not create worker configuration when the resolved path does not use workers.

### 4. Decompose And Implement

Keep the current agent responsible for orchestration, dependency ordering, shared decisions, integration, and final validation.

For orchestrator-only execution:

- Maintain a short phase list mapped to the accepted plan.
- Implement each behavior with Red/Green TDD when practical.
- Run the smallest useful validation after each meaningful phase.

For delegated execution:

- Follow the worker discovery, configuration, manifest, dispatch, and integration contract in `references/delegation.md`.
- Create bounded work packets with explicit dependencies, file ownership, acceptance criteria, and validation.
- Dispatch only dependency-ready tasks. Run independent tasks in parallel and coupled tasks in sequential waves.
- Keep shared schemas, migrations, central configuration, architectural changes, and final integration with the orchestrator unless ownership is unambiguous.
- Review every worker result and patch before accepting it.

For both paths:

- Start each meaningful behavior change with a failing test when practical.
- Implement the smallest change that makes the test pass, then refactor only while green.
- If test-first work is impractical, record why and use the smallest equivalent pre-change validation.
- Commit focused intentional changes frequently by repository convention.
- Never stage unrelated files.
- Mark meaningful Forest phase transitions when Forest is available.

### 5. Validate The Integrated Result

- Run repository-required formatting, linting, type checks, tests, builds, and coverage checks.
- Run task-specific acceptance and regression validation from the plan.
- Re-run relevant checks after worker integration, even when workers reported them as passing.
- Record any validation that could not run and the exact reason.
- Invoke `code-review` before PR creation and resolve actionable blocking findings.

### 6. Open The Pull Request

- Invoke `create-pr` and follow its instructions completely.
- Target the repository's normal integration branch.
- Link implementation to the accepted plan and work brief.
- Report tests, delegated work when relevant, risks, rollout, and unresolved limitations.

### 7. Monitor Review

- Create or update a 5-minute PR monitor.
- Watch code review bot feedback, security review, CI, mergeability, and human comments.
- For actionable feedback, apply a scoped fix, validate, commit, push, and continue monitoring.
- Do not merge unless the user explicitly asks.

### 8. Finish And Clean Up

- Finish only when the PR is ready to merge, merged, explicitly canceled, or blocked by a concrete external condition.
- Report the PR URL, current status, validation, delegated-task outcome, and remaining blockers.
- Preserve durable plans, decisions, repository worker defaults, and required native worker profiles.
- Clean up only temporary coordination artifacts clearly created by this workflow, following the ownership and safety rules in `references/delegation.md`.
- Never remove a Forest worktree directly; use `forest close` only when the user asks or integration is proven and repository policy permits cleanup.

## Rules

- Default implementation delegation to `always` when kickoff supplies no explicit or saved preference.
- Never spawn implementation workers only when the user selected `never`/no subagents for the task or explicitly saved that repository default.
- Never treat implementation delegation as permission to skip independent plan reviews.
- Never persist an orchestrator model; the orchestrator is the current agent session.
- Never hardcode Codex, Claude Code, OpenCode, or provider-specific model names into the portable workflow.
- Never silently substitute or override a configured worker selector.
- Never let parallel workers own overlapping files or unresolved shared dependencies.
- Do not implement large work directly on `dev` or `main`.
- Do not abandon a kickoff-provided worktree.
- Do not batch all work into one large commit.
- Do not merge without explicit user approval.
- Do not finish merely because the PR exists.

## Create-PR Handoff

When ready to open the PR, invoke the local `create-pr` skill and provide the accepted plan, work brief, validation evidence, known risks, and implementation-delegation summary.

## Automation Handoff

After PR creation, create or update a monitor with a 5-minute cadence. Stop monitoring only when the PR is clear, ready, merged, explicitly canceled, or blocked by a concrete external condition.
