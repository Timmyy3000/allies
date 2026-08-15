# Delivery Integrations

Use this reference when a ticket needs planning, implementation, review,
pull-request delivery, isolated worktrees, or multiple workers.

## Contents

- [Capability checks](#capability-checks)
- [Kickoff handoff](#kickoff-handoff)
- [Worktree isolation](#worktree-isolation)
- [Execution waves](#execution-waves)
- [Worker handoffs](#worker-handoffs)
- [Completion and resume](#completion-and-resume)

## Capability checks

Use `kickoff` for substantial implementation tickets, meaningful risk,
cross-repository work, or work that should end in a pull request. Let Kickoff
manage its planning, adversarial and simplicity reviews, implementation, review,
PR, and monitoring flow.

Check that required integrations are available before invoking them. Do not
install a missing integration, invent commands, or invoke overlapping workflow
skills independently without authorization. If an integration is unavailable,
fall back to direct serial execution and record the limitation.

## Kickoff handoff

Pass Kickoff:

- the epic and ticket paths;
- ticket ID for the suggested branch name;
- outcome and acceptance checks;
- affected repositories and project areas;
- completed dependencies;
- risks, validation expectations, and relevant specifications;
- worktree manager and any existing worktree path.

When Kickoff finishes, record its branch, worktree, commits, pull request,
validation, discoveries, and blockers. Verify ticket acceptance independently;
Kickoff completion does not automatically make the ticket `done`.

## Worktree isolation

Use one worktree per concurrent implementation ticket. Prefer Forest when it is
available and selected by the delivery workflow; otherwise use Git worktrees or
execute conflicting work serially.

Begin branch names with the ticket ID, for example:

```text
prj-001-short-description
```

When using Forest:

1. Inspect `forest status --json` first.
2. Never reuse another agent's dirty worktree.
3. Create one worktree per independent ticket.
4. Record the exact path Forest returns; never guess it.
5. Run the workflow inside that worktree.
6. Do not remove Forest worktrees with ordinary Git commands.
7. Diagnose inconsistent state with `forest doctor --json`.
8. Use `forest close` only after integration and authorized cleanup.

## Execution waves

Assign one coordinator for the epic. The coordinator owns `NOW.md`, assignments,
dependencies, integration order, epic status, and final acceptance.

Give each worker one ticket, a non-overlapping write boundary, relevant
instructions and specifications, expected validation, and a required handoff.
Run tickets in parallel only when dependencies are complete, contracts are
stable, worktrees are separate, and write boundaries do not overlap. Keep shared
contracts, central migrations, and conflicting configuration changes serial.

```text
Wave 1: shared foundation or contract
    ↓
Wave 2: independent implementation tickets
    ├── Ticket A
    ├── Ticket B
    └── Ticket C
    ↓
Wave 3: integration and end-to-end proof
```

Workers must not claim unrelated tickets, update another ticket, restructure the
board, or broaden shared contracts beyond their assignment.

## Worker handoffs

Require every worker to return:

```markdown
## Handoff
- Ticket:
- Result: completed, blocked, or review needed
- Changed areas:
- Validation:
- Evidence:
- Decisions discovered:
- Follow-ups:
- Blockers:
```

Treat the handoff as evidence to inspect, not automatic proof. The coordinator
must review the actual diff, rerun relevant validation, update the ticket, and
resolve integration conflicts.

## Completion and resume

Before closing an epic:

1. Confirm required tickets are `done`.
2. Run the complete exit-gate demonstration.
3. Record evidence and remaining risks.
4. Reconcile documentation, board state, and implementation.
5. Mark the epic `done` and activate the next epic.
6. Break down the next epic using what was learned.
7. Re-estimate later work when uncertainty has changed.
8. Update `NOW.md`.

When resuming, read instructions, `README.md`, `NOW.md`, the active epic, active
and ready tickets, referenced specifications, and current code state. Reconcile
the tracker before assigning new work. Keep statuses current, blockers explicit,
assignments fresh, and the distant backlog intentionally small.
