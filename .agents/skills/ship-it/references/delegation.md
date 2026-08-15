# Delegated Implementation

Use this reference only when `ship-it` resolves implementation delegation to `always` or when `auto` selects workers.

## Single Kickoff Configuration

Use one repo-level `kickoff.yaml` for this workflow:

- `implementation_delegation_default` optionally stores the user's lasting preference: `never`, `auto`, or `always`.
- `plan_review.workers` optionally stores one harness-native review selector per harness. It is owned by `adversarial-review` and `simplicity-review` and is shared by both.
- `ship_it.workers` stores one harness-native worker selector per harness only after delegated implementation needs one.

Use the agent-workspace root already selected by repository instructions and kickoff, such as `.agents/` or `.agent/`. Do not create either convention blindly.

Example worker configuration:

```yaml
version: 1
implementation_delegation_default: "auto"
plan_review:
  workers:
    codex:
      agent: "<review-worker-name>"
ship_it:
  workers:
    codex:
      agent: "<same-or-different-native-agent-name>"
    claude-code:
      agent: "<native-agent-name>"
    opencode:
      model: "<provider/model-id>"
      reasoning_effort: "<optional-harness-native-level>"
```

The lasting default is optional, and `plan_review` and `ship_it` are optional until their workers are configured. Never create the file or an empty section merely because fallback mode is `always`. The current session is the orchestrator and must not be persisted.

Each harness entry must use exactly one selector:

- `agent`: exact harness-native named agent. Its native definition is the sole source of truth for model, reasoning, instructions, and other settings.
- `model`: direct per-spawn model selection, with optional `reasoning_effort`, only when the harness has no named-agent requirement.

Never combine `agent` and `model`, duplicate a named agent's model settings in `kickoff.yaml`, or overwrite another harness's entry.

### Sharing Review And Implementation Workers

The review skills resolve `plan_review.workers`; `ship-it` resolves `ship_it.workers`. To use one worker for both, store the exact same selector in both active-harness entries. To use different workers, store different selectors. A named worker's native definition remains the only source of truth for its model, reasoning, instructions, and other settings. Preserve both sections when updating either one.

## First-Use Worker Bootstrap

When the current harness has no worker entry and delegation will be used:

1. Identify the active harness and its available subagent mechanism.
2. Discover named agents available to the current harness before asking for model settings.
3. If a suitable named agent exists, ask the user to select or confirm its exact name, validate it, and store only `agent`.
4. If named agents are supported but none is suitable, ask for agent name, model, supported reasoning level, and personal or project scope. Explain and create the smallest valid native definition, validate it, then store only `agent`.
5. If the harness dispatches directly by model, ask for model and supported reasoning level, validate them, then store `model` and optional `reasoning_effort`.
6. Update only the active harness entry in `kickoff.yaml`, preserving all other keys and harnesses.

Do not ask for a named agent's model or reasoning settings when selecting an existing agent. Do not ask the user to choose an orchestrator model or configure inactive harnesses.

Revalidate the saved selector before each delegated run. If a named agent is unavailable or invalid, do not add model overrides or substitute another worker silently. Ask whether to repair it or choose a replacement and update only the active harness entry.

If the harness cannot spawn workers:

- In `auto`, record that delegation was unavailable and continue with the orchestrator.
- In `always`, stop and ask the user to switch the task to `never` or `auto`, configure a supported worker mechanism, or use a supporting harness.

## Auto-Mode Decision

Lean toward delegation when one or more bounded tasks can run without blocking the orchestrator, especially when:

- Two or more tasks are dependency-ready and own separate files or systems.
- A focused implementation, test, documentation, migration-verification, or read-heavy task can run independently.
- Parallel execution reduces elapsed time without increasing integration risk.

Keep execution with the orchestrator when:

- The change is a single tiny edit.
- Candidate tasks modify the same files or shared contract.
- The next task depends immediately on unresolved output from the first.
- Task-packet creation and integration cost more than the work itself.

Record the auto decision and brief rationale in the work brief before implementation.

## Task Workspace

Reuse the task-workspace path handed off by kickoff or the repository's established agent-work convention. Do not place temporary worker artifacts beside a durable plan merely because it is nearby.

Create only the coordination artifacts needed for this task:

```text
<task-workspace>/
├── execution-manifest.md
└── worker-results/
```

Reference rather than duplicate the accepted plan, work brief, adversarial review, simplicity review, and repository instructions.

## Execution Manifest

Make the manifest the contract between orchestrator and workers:

```markdown
# Execution Manifest

## Shared Context

- Work brief: <path>
- Accepted plan: <path>
- Adversarial review or dispositions: <path or brief section>
- Simplicity review or dispositions: <path or brief section>
- Repository instructions: <paths>

## Task <ID>

### Objective

### Dependencies

### Owned Files Or Systems

### Required Context

### Acceptance Criteria

### Validation

### Required Result

- Files changed
- Tests and results
- Assumptions
- Blockers
- Integration notes
```

Create the smallest useful number of tasks. Do not split work merely to maximize worker count.

## Dispatch Contract

For each dependency-ready task:

- Spawn `agent` by its exact native name without model or reasoning overrides; otherwise spawn with the configured `model` and optional `reasoning_effort`.
- Prefer a fresh worker context where supported.
- Pass the task ID, manifest path, brief path, plan path, relevant review findings, applicable repository instructions, and exact task-workspace or worktree path.
- Tell the worker to read those artifacts before editing.
- Give exclusive file or system ownership.
- Prohibit scope expansion, unrelated edits, additional worker spawning, and silent architecture changes.
- Require the structured result listed in the manifest.

Do not rely on the orchestrator's conversation history as worker context. Durable artifacts and explicit work packets are the source of truth.

Run only independent tasks concurrently. Use sequential waves for dependencies and close completed worker sessions when they are no longer needed.

## Integration Contract

The orchestrator must:

1. Inspect each worker's result and actual diff.
2. Reject or correct work outside the assigned scope.
3. Resolve integration conflicts and shared decisions itself.
4. Run targeted validation after each accepted task.
5. Run integrated repository validation after all tasks land.
6. Record worker outcomes and any rejected assumptions in the work brief.

Worker-reported tests are evidence, not a substitute for orchestrator validation.

## Cleanup

Preserve:

- Accepted plans and repository-required planning archives.
- Work briefs and decisions the repository treats as durable.
- `kickoff.yaml` and required harness-native worker profiles.

Remove temporary `execution-manifest.md` and `worker-results/` only when all are true:

- They were created by the current `ship-it` run.
- They are not tracked or required by repository policy.
- The PR is ready, merged, canceled, or the user explicitly requests cleanup.
- Their exact paths have been verified inside the intended task workspace.

Never use broad recursive cleanup against an unresolved path. If ownership or retention is unclear, leave the artifacts and report them.
