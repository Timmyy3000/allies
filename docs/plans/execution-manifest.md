# CLD-004 Execution Manifest

## Shared Context

- Work brief: `docs/plans/cld-004-kickoff.md`
- Accepted plan: `docs/plans/cld-004-conversation-and-message-lifecycle.md`
- Plan presentation: `docs/plans/cld-004-conversation-and-message-lifecycle.html`
- Repository instructions: `AGENTS.md`, `ENGINEERING_STYLE.md`
- Template: `docs/templates/PLAN_TEMPLATE.md`
- Worktree: `ft/cld-004`
- Required implementation mode: Ponytail Full; accepted requirements and safeguards take precedence.

## Task 1 — Cloud conversation and message lifecycle

### Objective

Implement the accepted CLD-004 plan: Conversation and Message persistence,
onboarding history, text-only acceptance, idempotency, bounded queueing,
authorization, pagination, lifecycle primitives, privacy-safe contracts, and
focused validation.

### Dependencies

- Existing Cloud Ally, Workspace, authorization, and CLD-003 onboarding behavior.
- No integrity-scan or persisted route-gate feature; rely on database foreign
  keys, uniqueness/check constraints, migration validation, and route tests.

### Owned Files Or Systems

- `backend/chat/**`
- Additive settings/registrar/migration wiring required for the chat app.
- Focused existing API/observability tests only where the plan names them.

### Acceptance Criteria

- All plan acceptance criteria pass.
- No provider/runtime identifiers leak into public contracts or diagnostics.
- PostgreSQL concurrency tests cover duplicate sends, ordering, queue limits,
  and lifecycle transitions.
- No attachments, execution gateway, streaming/replay, or speculative storage
  system is added.

### Validation

- Worker runs targeted tests while implementing.
- Orchestrator reruns `make check`, `make lint`, and the focused chat test target,
  plus migration/OpenAPI and full relevant test validation from the plan.

### Required Result

- Files changed
- Tests and results
- Assumptions
- Blockers
- Integration notes
