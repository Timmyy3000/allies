# Stream conversation approvals

## Scope

Use approval summaries already carried by conversation activity events to update the web approval UI immediately. Keep REST as the source for initial history, full approval details, decisions, and recovery when live activity delivery is unavailable.

## Approach

- Reduce approval-bearing activity snapshots and SSE events into a conversation-scoped, sequence-aware approval projection.
- Merge that projection with the initial REST approval list without allowing stale pending data to replace terminal state.
- Stop summary/detail interval polling while activity SSE is connected; resume bounded conditional reconciliation when it disconnects.
- Continue fetching full approval details once when the user opens an approval.

## Affected surfaces

- Web conversation activity handling.
- Web approval list and detail queries.
- Unit and component coverage for ordering, deduplication, reconnect fallback, and decision state.

## Acceptance and validation

- A streamed pending approval appears without another approval-list request.
- Streamed status changes update the existing approval once and do not regress terminal state.
- Initial load restores historical approvals through REST.
- Polling is absent while SSE is connected and resumes for unresolved approvals after disconnection.
- Opening an approval still fetches its authoritative detail.
- Focused tests, workspace type-check, web lint, and the relevant home smoke suite pass.

## Risks and rollback

Out-of-order or replayed activity events could regress status; sequence-aware reduction plus terminal-state precedence prevents that. Reverting the feature commit restores conditional REST polling without changing Cloud contracts.

## Unresolved decisions

None. The existing activity event contract already includes the required approval summary.
