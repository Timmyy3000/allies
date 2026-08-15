# Board Format

Use this reference when creating, breaking down, or reconciling a Task Master
board.

## Contents

- [Directory layout](#directory-layout)
- [README](#readme)
- [Statuses](#statuses)
- [NOW.md](#nowmd)
- [Epics](#epics)
- [Tickets](#tickets)
- [Breakdown and updates](#breakdown-and-updates)

## Directory layout

```text
.agents/roadmap/
├── README.md
├── NOW.md
└── epics/
    ├── 01-first-epic/
    │   ├── EPIC.md
    │   └── tasks/
    │       ├── PRJ-001-first-deliverable.md
    │       └── PRJ-002-second-deliverable.md
    └── 02-next-epic/
        └── EPIC.md
```

Use the project's existing ticket prefix when one exists. Otherwise derive a
short, stable prefix from the project name. Put a cross-repository board at the
shared project root and a contained board at the repository root.

## README

Explain:

- the board's purpose and the roadmaps, specifications, or decisions it follows;
- status meanings and evidence requirements;
- assignment, ownership, dependency, and worktree rules;
- which files are coordinator-owned;
- how another human or agent should resume the board.

## Statuses

| Status | Meaning |
| --- | --- |
| `backlog` | Understood but not ready. |
| `ready` | Clear, unblocked, and safe to begin. |
| `in-progress` | Actively owned by one person or agent. |
| `blocked` | Waiting for a named condition or decision. |
| `review` | Implemented but independently unverified. |
| `done` | Acceptance checks pass and evidence is recorded. |

Allow one active owner per ticket. When blocked, record the exact condition and
who or what can resolve it. Continue with another non-conflicting ready ticket
when possible.

## NOW.md

Keep `NOW.md` a pointer, not a second backlog. Update it whenever ownership,
status, blockers, the active epic, or the current exit gate changes.

```markdown
# Now

## Current epic
`01-example-epic`

## In progress
- `PRJ-001` — title — owner

## Ready next
- `PRJ-002` — title

## Blocked
- None.

## Current exit gate
One sentence describing the behavior that completes the epic.
```

## Epics

Make each epic answer one meaningful product or engineering question.

```markdown
---
id: EPIC-01
status: active
milestone: Short milestone name
owner: Project team
---

# Epic title

## Question
What important uncertainty does this epic resolve?

## Outcome
What working behavior should exist when it is complete?

## Included
- Required capability

## Not included
- Explicitly deferred work

## Exit gate
- [ ] Observable end-to-end condition
- [ ] Important failure or recovery behavior
- [ ] Required evidence is recorded

## Ticket order
1. `PRJ-001` — first dependency
2. `PRJ-002` — next deliverable
```

Complete an epic by demonstrating its exit gate, not merely by closing tickets.

## Tickets

A ticket should normally produce one reviewable pull request, independently
testable slice, infrastructure capability, validated decision, or repeatable
proof. Avoid tickets such as “build backend”; split by independently verifiable
outcomes without reducing work to individual files or trivial coding steps.

```markdown
---
id: PRJ-001
status: ready
epic: EPIC-01
repositories: [repository-name]
depends_on: []
assignee: null
workflow: null
worktree_manager: null
branch: null
worktree: null
updated: YYYY-MM-DD
---

# Deliverable title

## Outcome
What will be true when this ticket is complete?

## Work
- [ ] Concrete implementation step
- [ ] Focused tests or validation
- [ ] Required documentation update

## Acceptance
- [ ] Observable success behavior
- [ ] Important failure behavior
- [ ] Relevant checks pass

## Evidence
Record tests, commits, pull requests, demos, or operational checks.

## Handoff notes
Record discoveries, blockers, decisions, and follow-up work.
```

Name every repository or project area changed. Use `workspace` for work outside
a specific repository.

## Breakdown and updates

For the active epic, identify the serial foundation, independent branches,
integration points, final proof, and direct dependencies. Mark only unblocked,
sufficiently clear tickets as `ready`.

Before starting a ticket:

1. Re-read `NOW.md`, the epic, and the ticket.
2. Confirm every dependency is `done`.
3. Check for overlapping active work.
4. Assign one owner and set `in-progress`.
5. Record workflow, branch, and worktree when applicable.
6. Update `NOW.md`.

When new work appears, keep it in the ticket if small and required for
acceptance, create a ticket if independently deliverable, defer it if the exit
gate does not require it, and update durable documentation if it changes a
decision. Do not expand an epic silently.
