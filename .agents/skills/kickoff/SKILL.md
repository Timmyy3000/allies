---
name: kickoff
description: Start an IC engineering workflow from initial intent through planning, independent adversarial and simplicity reviews, implementation, pull request creation, and review monitoring. Use when the user invokes /kickoff or $kickoff, wants to start feature work, bug fixing, improvements, refactors, hotfixes, investigations, or explorations, or asks for a full human-reviewed plan or a fast agent-reviewed Markdown plan before execution. When worker configuration is missing, require first-use subagent configuration before routing work.
---

# Kickoff

Guide an engineer from an initial idea to a durable brief, proportionate plan, implementation, pull request, and monitored review loop.

Keep this skill thin. Own intake, repository context, worker-preference gating, planning-mode selection, routing, and any required plan approval. Delegate worker discovery and dispatch details to `adversarial-review`, `simplicity-review`, and `ship-it`; delegate plan creation, code review, and pull-request mechanics to `plan-it`, `code-review`, and `create-pr`.

## Rules

- Treat `/kickoff` as the user-facing invocation.
- Verify required workflow skills before routing work to them.
- Establish one isolated task worktree before writing planning artifacts.
- Create durable context before planning, implementation, or investigation.
- Ask only for information that materially changes scope, risk, priority, or execution.
- Prefer repository evidence over assumptions: read local instructions, templates, docs, tickets, specs, and nearby code when relevant.
- Default implementation delegation to `always`: use subagents unless the user explicitly chooses `never`/no subagents for the task. Resolve `auto` only when the user or repository default selects it.
- Keep implementation delegation separate from independent plan reviews. Choosing no implementation worker must not silently disable review quality or change the review skills' worker contract.
- Make missing worker configuration a first-use gate; do not silently use the current orchestrator, an arbitrary model, or a fallback worker.
- Use full planning for substantial, ambiguous, or risky work. Use fast planning only when explicitly requested or when the work is clearly small, bounded, and low risk.
- Do not start implementation until the full-path plan is approved or the fast-path plan has passed both independent reviews.
- Keep the work brief updated as decisions are made.
- After approval or fast-path review, continue through `ship-it`, PR creation, and review monitoring without routine confirmations.
- Stop only for a real blocker, required authority, failed authentication, unresolved product decision, first-use worker configuration, or explicit user pause.

## Dependency Check

Before intake, verify these skills are available:

- `plan-it`
- `adversarial-review`
- `simplicity-review`
- `ship-it`
- `code-review`
- `create-pr`

Check the active skill list, the configured agent skills directory, `~/.agents/skills/<skill-name>`, `<workspace>/.agents/skills/<skill-name>`, and the current skills repository when the user is working inside one.

If a required skill is missing, name it and stop before entering a dependent phase unless the user explicitly requests a partial read-only investigation. Suggest the full workflow installation:

```powershell
npx skills add Timmyy3000/skills --skill kickoff --skill adversarial-review --skill simplicity-review --skill plan-it --skill ship-it --skill code-review --skill create-pr
```

For local testing, use:

```powershell
npx skills add . --skill kickoff --skill adversarial-review --skill simplicity-review --skill plan-it --skill ship-it --skill code-review --skill create-pr --agent <agent-name>
```

## Worktree And Artifact Setup

Before writing the brief, discover the repository's conventions and choose:

- Worktree manager: `forest` (recommended) or ordinary `git`.
- Branch/worktree name: the user's name or `auto`.
- Base branch/ref, if different from the repository default.
- The folder for durable agent/planning artifacts.
- The per-task workspace for temporary coordination artifacts.

Use one isolated worktree per kickoff effort. Run planning, both reviews, and `ship-it` from that same worktree.

### Forest

When using Forest:

1. Run `forest status --json` before creating or selecting a worktree; use `forest status` if JSON is unavailable.
2. Never reuse another agent's dirty worktree.
3. Create the worktree with the selected branch and base ref, for example `forest add -b <branch-name> --from <base-ref> --agent <agent-name> --json`; if the user supplied a worktree name instead of a branch, use `forest add <worktree-name> --from <base-ref> --agent <agent-name> --json`. Omit `--from` for the repository default.
4. Mark activity from inside it with `forest mark --phase working --agent <agent-name> --note "kickoff planning"`.
5. If Forest reports inconsistent state, run `forest doctor --json` and report the findings; do not repair state manually.
6. Remove worktrees only through `forest close` when the user asks or integration is proven.

If Forest is unavailable, ask whether to install it, use ordinary Git worktrees, or continue without a worktree for a read-only investigation.

### Ordinary Git

When using ordinary Git, inspect `git status --short --branch` and `git worktree list --porcelain`, choose a repository-conforming path, and create a worktree with `git worktree add`. If no path convention exists, ask before creating one. Never use ordinary Git cleanup commands for Forest-managed worktrees.

### Folder Convention

Choose the first matching convention:

1. Explicit repo instructions or templates (`AGENTS.md`, `CLAUDE.md`, contributing/planning docs, and similar).
2. Existing plan folders such as `docs/agent-plans/`, `docs/plans/`, `plans/`, `planning/`, or `agent-plans/`.
3. An existing `.agents/` or `.agent/` folder, preferring the one that already contains workflow or planning files.
4. If none exists, ask before creating a convention; suggest `.agent/kickoff/` as a conservative default.

Do not create `.agent/` or `.agents/` merely because this skill mentions them.

### Task Workspace

Prefer an existing per-task convention. Otherwise use the directory selected for the brief without inventing another nested convention. Keep it inside the kickoff worktree, record its exact path in the brief, and pass it to `ship-it`. Preserve durable plans and repository-required records; let `ship-it` clean only temporary artifacts it clearly owns.

## Required Worker Configuration Gate

Run this gate before selecting the planning mode or invoking a review or implementation skill.

1. Determine the active harness and whether it can spawn workers. Locate the repository's existing `kickoff.yaml` using the folder convention; do not create a new agent folder solely for configuration.
2. Resolve implementation delegation in this order: explicit task choice, saved `implementation_delegation_default`, then the workflow fallback `always`. Accept `subagents` as `always` and `solo` as `never`, but record only `always`, `auto`, or `never`.
3. If the user explicitly says no subagents for this task, resolve implementation delegation to `never` and do not ask for an implementation worker. A lasting instruction such as "never use subagents" may be saved as the repository default; a task-specific choice must not change it.
4. Unless the user separately declines worker-based reviews, require first-use review configuration when `plan_review.workers.<harness>` is missing. When implementation delegation resolves to `always`, also require `ship_it.workers.<harness>` before proceeding. Present the default clearly: "Use subagents: yes (default; say no to opt out)." Ask which review worker/model and, when implementation delegation is `always`, which implementation worker/model to use, or whether the exact same selector should be reused for both. In `auto`, let `ship-it` decide whether a worker is worthwhile and require its bootstrap only if it selects delegation.
5. Before asking, let the owning skill discover available native workers. Use `adversarial-review` for review-worker bootstrap and `ship-it`'s `references/delegation.md` for implementation-worker bootstrap. Those skills own selector shapes, model/reasoning validation, native worker creation, persistence, and revalidation; do not duplicate their detailed dispatch contracts here.
6. If a valid selector already exists, confirm or reuse it rather than asking for its model again. If a harness dispatches directly by model, collect only the supported model and optional reasoning setting. Never persist the current orchestrator as a worker.
7. If workers are required by the resolved `always` mode but the active harness cannot spawn them, stop and ask the user to choose a supported harness or explicitly opt out. Do not silently fall back to orchestrator-only implementation. Review skills may use their documented current-session fallback only when that fallback is explicitly accepted and recorded as non-independent.
8. Record the resolved delegation, review selector, implementation selector, and source of each in the brief. Pass them to the owning skills; they must preserve unrelated configuration and inactive harnesses.

The first-use prompt is mandatory when configuration is absent; lack of an explicit "yes" is not permission to skip it. An explicit no suppresses only the worker configuration it actually declines. Keep independent plan reviews enabled unless the user separately and explicitly declines worker-based reviews.

### Single Repository Configuration

Use one repository-level `kickoff.yaml`, under the discovered agent-workspace root, for this workflow. It may contain:

- `implementation_delegation_default`: an explicit lasting default.
- `plan_review.workers`: owned by `adversarial-review` and `simplicity-review`.
- `ship_it.workers`: owned by `ship-it`.

Do not create a separate `ship-it.yaml`, empty worker sections, inactive harness entries, or duplicated named-worker model settings. Preserve every unrelated key when updating the file. A fallback of `always` need not be written unless the user gives a lasting instruction.

## Intake

Classify the work as `feature`, `bug`, `improvement`, `refactor`, `hotfix`, `investigation`, or `exploration`.

Ask once for the smallest useful set of answers:

- Short title and work type, when not obvious.
- Objective and why it matters.
- Timeline or production target, if any.
- Constraints, owners, dependencies, affected repositories, and existing evidence.
- Implementation delegation choice (`always` default, `auto`, or explicit `never`).
- Planning mode (`auto`, `full`, or `fast`).
- Worktree manager, branch/worktree name, and base ref.
- The required worker configuration gate above when active selectors are missing.

Do not repeatedly pause for preferences that can be inferred safely. Resolve a task-specific choice first, then a saved repository preference, then the fallback default. Record both the value and its source.

For type-specific intake, ask only what applies:

- `feature`: actor, desired workflow, must-haves, out-of-scope behavior, states/permissions, rollout, and unacceptable failure modes.
- `bug`: actual versus expected behavior, impact/severity, reproduction/environment, evidence, first-seen timing, and urgency/rollback.
- `improvement`: current baseline, measurable target, before/after method, acceptable tradeoffs, and suspected scope.
- `refactor`: boundary, behavior invariants, payoff, preservation checks, migrations/compatibility, and excluded files or systems.
- `hotfix`: production impact, urgency, smallest fix, mitigation/rollback, release validation, and approvers.
- `investigation`: question, prompt/evidence, relevant systems, satisfactory answer, desired output, and whether code changes are allowed.
- `exploration`: hypothesis, timebox, evidence, decision criteria, prototype tolerance, and follow-up path.

## Work Brief

Create or update a durable Markdown brief after selecting the folder convention:

`<work-slug>.md`

Use this structure:

```markdown
# <Work Name>

## Status

- Type:
- Implementation delegation:
- Delegation source:
- Review worker:
- Review worker source:
- Implementation worker:
- Implementation worker source:
- Planning mode:
- Worktree manager:
- Branch:
- Worktree path:
- Task workspace:
- Created:
- Target date:
- Current phase:

## Objective

## Context

## Requirements

## Acceptance Criteria

## Evidence And Sources

## Decisions

## Risks

## Open Questions

## Plan

## Execution Notes
```

For investigations, use `Questions To Answer` and `Done Criteria` instead of `Requirements` and `Acceptance Criteria`. Use absolute dates and state whether a target looks feasible, risky, or unrealistic for the known scope and validation needs.

## Planning

Choose the mode after inspecting enough repository evidence:

- `auto`: choose `fast` only when behavior and acceptance criteria are clear, scope is narrow, repository patterns are established, no material product/architecture/security/data/compatibility decision is open, and validation plus rollback are concrete.
- `full`: use `plan-it` for a Lavish-backed plan, run both independent reviews, then ask the user to approve the reviewed plan.
- `fast`: write a concise Markdown plan, run both independent reviews, skip Lavish and the human plan-approval gate, then continue to `ship-it`.

Honor an explicit `fast` request but state the risk and keep the plan/reviews proportional. Never use fast-path handling to bypass approval for destructive actions, credentials, external side effects, unresolved product decisions, or other actions requiring authority. Upgrade `auto` to `full` when later evidence increases scope or risk.

For full planning, invoke `plan-it` with the brief, task workspace, work type, worker/delegation decisions, source evidence, timeline, constraints, and open decision points. Let `plan-it` own the Lavish artifact and its detailed content standard.

For fast planning, put the internal plan in the brief or the repository's established sibling plan location. Include objective/scope, the simplest viable approach, affected files/systems, acceptance criteria, focused validation, material risks, rollback, and unresolved decisions. Add type-appropriate evidence, regression, measurement, preservation, timebox, or follow-up criteria.

Do not force full planning for a small read-only investigation; a concise brief and final findings may be sufficient.

## Independent Plan Reviews

After the plan exists, invoke `adversarial-review` through its configured review worker in a fresh session when the harness supports workers. Pass only the skill, brief, plan, relevant evidence, active harness, task workspace, and `kickoff.yaml` path. The review skill owns worker bootstrap and structured output.

Read the result, record each meaningful finding's disposition in the brief, and resolve every `Blocker` and `Major` before continuing. In full mode, feed accepted revision feedback back to `plan-it`; in fast mode, revise the Markdown plan directly. If no fresh worker is available, use the review skill's explicit current-session fallback and state that independence was unavailable.

After adversarial findings are reconciled and the plan is revised, invoke `simplicity-review` through the same configured `plan_review.workers` entry in a new fresh session when supported. Pass the original brief, revised plan, complete adversarial output and dispositions, relevant evidence, active harness, task workspace, and config path. Reconcile every simplification, removal/deferment, and conflict; protect accepted safeguards and record rejected simplifications with rationale.

If a material conflict remains, ask only for the owner decision needed to resolve it. If the user asks to defer or continue investigating, record the current phase and findings in the brief instead of starting implementation.

Re-run simplicity review only when revisions materially change architecture, scope, or risk controls. Do not create review loops for wording or optional polish.

## Approval And Execution Handoff

For full mode, ask the user to approve or revise the reviewed plan. If revisions are requested, apply them through `plan-it` and repeat the required review/approval path. For fast mode, do not ask for plan approval; start execution after both reviews pass.

When execution is authorized, invoke `ship-it` with:

- The accepted Lavish plan or reviewed Markdown plan.
- The brief and task-workspace path.
- Adversarial/simplicity findings and dispositions.
- Worktree manager, branch, worktree path, and target branch.
- Resolved implementation delegation and source.
- Review and implementation selectors plus their configuration source.
- The `kickoff.yaml` path, validation expectations, risks, and open questions.

Let `ship-it` own bounded implementation delegation, integration, validation, `code-review`, `create-pr`, PR creation, and the five-minute review monitor. Do not add approval gates after full-path approval or fast-path review except for a real blocker, destructive action, credential/auth issue, required product decision, first-use worker configuration, or explicit user pause.

Kickoff is complete only when `ship-it` reports the PR ready to merge, merged, explicitly canceled, or blocked by a concrete external condition - not merely when a PR is opened.

## Phase Updates

At each phase transition, report the current phase, brief path, planning mode and reason, implementation delegation/source, resolved worker selectors/source, plan path and artifact type, open decisions, and the next skill being invoked.
