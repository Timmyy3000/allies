---
name: task-master
description: Create and maintain a lightweight file-based delivery board made of milestones, epics, and executable tickets. Use when the user invokes /task-master or asks Codex to break a project into trackable work, set up or update an epic tracker, select the next ticket, coordinate agents, plan safe parallel work, resume an ongoing project, or verify progress toward an MVP or release.
---

# Task Master

Turn a project roadmap into work that humans and agents can execute, verify, and
resume without reconstructing the plan from chat history.

Keep the board small, current, and based on observable outcomes. Treat Task
Master as the coordination layer; let specialized skills own planning,
implementation, review, and pull-request mechanics.

Do not start implementation unless the user's request authorizes it.

## Operations

Support these operations:

- `/task-master setup` — create a board from the current roadmap.
- `/task-master status` — reconcile the board with repository and project reality.
- `/task-master break-down <epic>` — create outcome-sized tickets.
- `/task-master start <ticket>` — claim and begin one ticket.
- `/task-master coordinate <epic>` — create a safe multi-agent execution wave.
- `/task-master close <ticket-or-epic>` — verify completion and advance the board.

When invoked without an operation, report the active epic, current work,
blockers, next ready ticket, and safe parallel work after reconciling the board.

## Operating Contract

- Read workspace and repository instructions, roadmaps, specifications,
  decisions, issues, plans, code, and tests before changing the board.
- Prefer one existing board. Do not overwrite it or create a competing tracker.
- Treat specifications as product truth, the board as execution truth, and code
  plus tests as implementation truth.
- Fully break down the active epic and, when useful, the next epic; keep distant
  milestones at outcome level until uncertainty is reduced.
- Give every epic an exit gate and every ticket acceptance checks and evidence.
- Keep one active owner per ticket. Make blockers, dependencies, and status
  explicit rather than inferring them from chat.
- Do not mark work done merely because code was written or a worker reported
  success; require acceptance evidence.
- Keep the board uncommitted by default, respect ignore rules, and ask before
  changing repository-wide ignore policy.

## Workflow

### 1. Inspect and choose scope

Read the local instructions and existing planning or task conventions first.
Use a project-level board when work crosses repositories, services, clients,
infrastructure, or runtime components. Use a repository-level board when the
work is independently contained in one repository.

Prefer the repository's existing `.agent`, `.agents`, planning, or task
convention. If no convention exists, use `.agents/roadmap/` only after checking
that creating it is appropriate.

Read [references/board-format.md](references/board-format.md) before creating
or materially changing board files.

### 2. Reconcile before planning work

Read `README.md`, `NOW.md`, the active epic, active tickets, ready tickets,
referenced specifications, and current code state. Confirm that recorded status,
ownership, dependencies, branches, worktrees, and evidence match reality.

If new work appears, keep it in the current ticket only when it is small and
required for acceptance. Otherwise create a ticket or defer it. Do not expand
an epic silently.

### 3. Build the delivery order

For the active epic, identify:

1. Serial foundation or contract work.
2. Independent implementation branches.
3. Integration points.
4. The final end-to-end proof.

Record direct dependencies in `depends_on`. Mark a ticket `ready` only when it
is clear, unblocked, assigned according to local convention, and safe to begin.
Do not add dependencies merely because ticket numbers are sequential.

### 4. Start or delegate work

Before starting a ticket, re-read `NOW.md`, the epic, and the ticket; confirm
that dependencies are `done`; check for overlapping active work; assign one
owner; record workflow, branch, and worktree; and update `NOW.md`.

For production code, meaningful risk, cross-repository work, or work that should
end in a pull request, use `kickoff` and pass it the epic, ticket, acceptance
checks, affected repositories, dependencies, risks, validation expectations,
and ticket ID. Read [references/integrations.md](references/integrations.md)
for the handoff and isolation contract.

When integrations are unavailable, fall back to direct serial execution rather
than installing a missing integration, inventing commands, or invoking
overlapping workflow skills independently.

### 5. Verify and advance

Move a ticket to `review` when implementation is finished but independently
unverified. Move it to `done` only after acceptance checks, tests, evidence,
documentation, and integration checks pass with no hidden blocker.

Before closing an epic, verify every required ticket is `done`, run the complete
exit-gate demonstration, record evidence and remaining risks, reconcile the
board with implementation, mark the epic `done`, activate the next epic, and
break down the next epic using what was learned.

## Coordination Rules

Assign one coordinator per epic. The coordinator owns `NOW.md`, assignments,
dependencies, integration order, epic status, and final acceptance.

Give each worker one ticket, a non-overlapping write boundary, relevant
instructions and specifications, expected validation, and a required handoff.
Run tickets in parallel only when dependencies are complete, contracts are
stable, worktrees are separate, and write boundaries do not overlap. Keep shared
contracts, central migrations, and conflicting configuration changes serial.

Workers must not claim unrelated tickets, update another ticket, restructure the
board, or broaden shared contracts beyond their assignment.

## References

- [Board format and templates](references/board-format.md)
- [Kickoff, worktrees, workers, and handoffs](references/integrations.md)
