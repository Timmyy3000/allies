# CLD-006 Cursor Replay and Reconnect

## Status

- Type: feature / cross-repository recovery slice
- Implementation delegation: always
- Delegation source: kickoff default
- Planning worker: sol_planning_worker
- Planning worker source: `.agent/kickoff.yaml`
- Review worker: sol_review_worker
- Review worker source: `.agent/kickoff.yaml`
- Implementation worker: luna_execution_worker
- Implementation worker source: `.agent/kickoff.yaml`
- Planning mode: fast
- Worktree manager: Forest-managed existing preview worktrees
- Branches: `ft/local-staging-docker` (Cloud), `web/retry-message-recovery` (Interface), `dev` (Foundry reference)
- Worktree paths: Cloud `ft/local-staging-docker`, Interface `web/retry-message-recovery`, Foundry `dev` (Forest-managed preview worktrees)
- Task workspace: `docs/plans` in the Interface repository
- Created: 2026-08-31
- Target date: 2026-08-31 local validation
- Current phase: local implementation and preview validation

## Objective

Make the Cloud activity timeline replayable from a signed conversation cursor and let the web Interface reconnect and apply missed activity events without losing or duplicating visible Ally responses. Preserve the existing Foundry event vocabulary and local preview stack. Do not create or merge a PR.

## Context

The current MVP polls a bounded 200-row activity tail. A seeded long-running conversation exceeded that bound, so the Interface received only the tail and rendered raw assistant deltas individually instead of reconstructing turns. Cloud already persists globally ordered activity rows and has signed conversation cursor helpers for message history. Foundry already emits ordered `message.delta`, activity lifecycle, and terminal events; no Foundry protocol change is assumed.

## Requirements

- Define a signed, conversation-scoped activity replay cursor with expiry and authorization checks.
- Keep the existing bounded tail snapshot compatible for current consumers.
- Add bounded forward replay pages from the beginning or a supplied cursor, with explicit resume/next cursor and retention-gap signaling.
- Reuse Cloud's existing persisted Activity sequence and Foundry event projection; do not expose Hermes or runtime identifiers to the Interface.
- Integrate the web Cloud client and Home workspace so initial activity hydration consumes replay pages and ongoing status checks use the last cursor.
- Preserve current message ordering, turn concatenation, retry behavior, polling fallback, loading/error states, and Ally isolation.
- No PRs, merges, or production deployment.

## Acceptance Criteria

- A conversation with more than 200 activities hydrates all replayable activity pages and renders each assistant turn as one coherent response.
- Repeating a replay request with the same cursor does not duplicate activities or visible text.
- A cursor is scoped to its conversation, rejects tampering/expiry, and reports a retention gap instead of silently skipping history.
- A reconnect/poll after a cursor receives only activities after that cursor and advances the resume cursor monotonically.
- Existing tail snapshot callers and mobile client compilation remain compatible.
- Cloud and Interface focused tests, type checks, and live local-stack verification pass.

## Evidence And Sources

- Nabu `projects/allies/delivery/tickets/cloud/CLD-006.md` — replay, reconnect, retention, authorization, and evidence requirements.
- Nabu `projects/allies/engineering/specs/conversation-and-streaming.md` — Cloud is the product stream boundary; MVP polling is interim and CLD-006 owns cursor replay.
- Cloud `backend/activities/services/projection.py`, `backend/activities/api/register.py`, and `backend/chat/services/messages.py` — persisted sequence model, bounded snapshot, and signed cursor pattern.
- Interface `apps/web/app/home/home-workspace.tsx` and `packages/cloud-client/src/*` — current polling/projection boundary.
- Seeded long-running conversation exceeding the 200-activity bound; current bounded snapshot returns only the tail.

## Decisions

- Implement cursor replay over the existing authenticated Cloud activities endpoint before introducing browser SSE. SSE can follow once replay semantics are proven; it cannot replace durable replay.
- Use the existing HMAC cursor key configuration and conversation authorization boundary.
- Keep cursor replay forward-only for one conversation; older message history remains on the existing message cursor.
- Continue polling as the transport during this slice so the change is small and can be validated against the running preview.

## Risks

- Cursor semantics must not confuse attempt-local Foundry sequence with conversation-global product sequence.
- Replay page limits must remain bounded and avoid N+1 relation queries.
- Existing tests/mocks and the mobile client consume the same Cloud method; compatibility must be explicit.
- Retention is not currently deleting rows; the gap path must still be represented and tested for future retention.

## Open Questions

- Whether the later SSE transport should use the same replay endpoint and `Last-Event-ID` mapping is deferred until this cursor contract is validated.

## Plan

1. Add Cloud activity replay cursor parsing/serialization, response fields, query behavior, retention-gap errors, and focused tests.
2. Extend the typed Interface client and view model for replay metadata; hydrate replay pages and advance a per-conversation cursor while retaining polling fallback.
3. Add regression coverage for multi-page hydration, duplicate/stale cursors, reconnect advancement, and existing snapshot compatibility.
4. Run Cloud checks/tests, Interface tests/typecheck, regenerate/pin the local OpenAPI contract, restart only the active preview backend if needed, and verify a long-running seeded conversation plus a fresh turn in the browser.

## Execution Notes

- Existing preview worktrees are intentionally reused because the user requested real-time testing against the active Docker/dev-server stack and both contain unrelated in-progress retry work that must be preserved.
- No implementation changes from this kickoff should be committed or pushed until the user explicitly asks.

## Review Dispositions

- The independent adversarial review identified gaps around 409 gap mapping,
  cursor direction/origin semantics, attempt-local versus global continuity,
  expiry recovery, paging races, empty metadata, and replay bounds.
- The independent simplicity review confirmed the core approach and kept it
  stateless: a signed activity cursor with a fixed high-water mark, the existing
  projector, one explicit client budget, and no browser-only retention fixture.
- The revised plan incorporates these dispositions, including 409/410/422
  OpenAPI and API tests, a dedicated activity cursor payload, one-time expiry
  rehydration, and explicit empty-page semantics.
