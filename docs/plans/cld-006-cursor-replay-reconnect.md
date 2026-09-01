# CLD-006 Cursor Replay and Reconnect Plan

## Objective and scope

Make the Cloud activity timeline replayable from an authenticated, signed
conversation cursor and have the web Home workspace recover missed events without
duplicating visible Ally text. The slice keeps polling as transport, preserves the
existing Foundry event vocabulary, and does not change Foundry code, Hermes access,
or production deployment.

In scope: Cloud replay contract and retention-gap handling; typed Interface client
and mapper changes; web hydration/reconnect/projection behavior; compatibility with
the bounded tail snapshot and mobile compilation; focused tests and local-stack
evidence. Out of scope: SSE/WebSockets, message-history cursor changes, stop/retry
behavior already in the concurrent worktree, data retention jobs, and PR/merge.

Assumptions: Cloud's existing `serialize_cursor`/`parse_cursor` HMAC key and TTL
configuration remain the signing authority; `Activity.sequence` is the
conversation-global product order; Foundry attempt sequence remains attempt-local;
no schema migration is needed because the cursor is stateless over persisted
activities. Preserve all unrelated retry work already present in both worktrees.

## Contract and ownership

### Cloud API

Extend the existing authenticated endpoint (owned by Cloud; Interface calls only
Cloud):

`GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/activities`

Query parameters remain `limit` (1..200, default 200) and add `replay` (boolean,
default false) plus optional signed `cursor` (max 512 characters). `replay=false`
retains the current bounded latest-tail snapshot and its ordering. `replay=true`
returns ascending rows with `sequence > after_sequence` and `sequence <= high_water`
at most `limit` activities, plus:

```json
{
  "conversation_id": "uuid",
  "activities": [{"id":"uuid","message_id":"uuid","sequence":1,
    "conversation_turn_ordinal":2,"kind":"assistant_delta","text":"…",
    "state":"running","created_at":"2026-08-31T12:00:00Z"}],
  "state":"running",
  "last_contiguous_sequence":3,
  "last_contiguous_activity_sequence":7,
  "resume_cursor":"<signed cursor>",
  "next_cursor":"<signed cursor or null>",
  "oldest_sequence":1,
  "latest_sequence":7,
  "retention_gap":false
}
```

The activity cursor is a dedicated signed payload, not a message-history cursor:
`{"v":1,"t":"activity","c":"<conversation UUID>","a":<after_sequence>,
"h":<high_water_sequence>,"e":<expiry epoch>}`. The parser requires this exact
version/type/field shape, so message cursors (which use `before_sequence`) are not
interchangeable. `after_sequence` is forward-exclusive: the origin is `0`, a first
page requests `sequence > 0`, and each returned cursor sets `a` to the last returned
global Activity sequence. The server computes `h` once on the origin request. While
`after_sequence < h`, subsequent page requests constrain rows to `sequence <= h`,
so concurrent appends are left for the next forward poll. `next_cursor` is present
only when another row exists at or below `h`. Once a request reaches
`after_sequence >= h` (the end of a page session), Cloud refreshes `h` to the latest
sequence before querying, allowing the same resume cursor to pick up appends without
reopening earlier pages. The returned `resume_cursor` at the end of a session
therefore carries the refreshed high-water; an empty page returns that refreshed
cursor. A missing sequence inside the fixed range (`after_sequence < h`) is a
retention gap, not a reason to advance the high-water or skip rows.

The cursor uses the existing HMAC key rotation and bounded TTL, but has dedicated
activity serialization/parsing helpers. Malformed, tampered, cross-conversation,
wrong-version, wrong-type, or message-cursor input maps to 422 with code
`activity_cursor_invalid` and a generic privacy-safe body. A correctly signed but
expired activity cursor maps to 410 with code `activity_cursor_expired`; the body
does not echo the token or payload. A valid cursor older than
`oldest_sequence - 1`, or a missing sequence inside the fixed high-water range due
to retention, maps to 409 `activity_cursor_gap` and must not skip history. The
controller catches each named projection exception, includes 409/410/422 in
`error_responses`, and the generated OpenAPI must describe all three error codes.
Authorization is rechecked via the workspace capability boundary on every request;
foreign conversations remain 404. Query work stays bounded and uses the existing
indexed Activity sequence ordering without per-row relation fetches.

For an empty conversation, replay returns `activities: []`, `state: "completed"`,
`oldest_sequence: null`, `latest_sequence: null`,
`last_contiguous_activity_sequence: 0`, `last_contiguous_sequence: 0`,
`retention_gap: false`, `next_cursor: null`, and a signed origin
`resume_cursor` (`a=0,h=0`) so polling can begin without a special case. Default
tail snapshots keep cursor fields null and retain existing state semantics.

`last_contiguous_sequence` remains the legacy attempt-local Foundry receipt
continuity value for compatibility. `last_contiguous_activity_sequence` is the
new conversation-global Activity continuity value and is the only continuity field
the Interface uses. It must continue across turns even when Foundry attempt and
generation sequences reset; its origin is 0 and it advances only through contiguous
persisted global Activity rows.

### Interface shapes and state

Update `@allies/cloud-client` to accept replay options while retaining the current
`getActivities(workspaceId, conversationId, limit?, signal?)` call compatibility (or
an equivalent overload), and map additive response metadata as nullable/optional
fields for old Cloud responses. Expose `resumeCursor`, `nextCursor`,
`oldestSequence`, `latestSequence`, `lastContiguousActivitySequence`, and
`retentionGap` only in the view model; keep the legacy attempt-local field available
but unused for replay continuity. Model 410 expired, 409 gap, and 422 invalid
cursor errors as distinct normalized Cloud errors.

In `apps/web/app/home/home-workspace.tsx`, own one replay cursor per conversation:

1. On conversation selection, request bounded replay pages from the beginning until
   `nextCursor` is null. The client uses deterministic guards of at most 64 pages and
   4 MiB of UTF-8 activity JSON/text for one hydration; exceeding either stops with
   a visible bounded-replay repair error rather than looping.
2. Feed every page through the existing activity projection, deduping by global
   product sequence and grouping assistant deltas by `message_id` and
   `conversation_turn_ordinal`; never use Foundry attempt-local continuity as the
   product cursor.
3. Persist the latest `resumeCursor` in feature state/ref. Poll with
   `replay=true,cursor=<last cursor>` so reconnect receives only forward events and
   advances monotonically. Keep the existing bounded-tail call as compatibility and
   fallback when no replay cursor is available; preserve cancellation, visibility,
   poll budget, loading/error/retry, terminal, and follow-latest behavior.
4. On 410 `activity_cursor_expired`, clear that cursor and restart from the origin
   once automatically. On 409 `activity_cursor_gap`, clear only the affected cursor,
   preserve the already rendered timeline, and show a repair/check-again state; a
   user-triggered check may retry from origin but must never silently jump to latest.
   On 422 `activity_cursor_invalid`, stop automatic retries and show a generic
   unavailable state (the client records only the safe error category). Abort stale
   requests when switching Allies so one conversation cannot mutate another's
   projection.

No Interface code calls Foundry, Hermes, Fly, or runtime addresses. Foundry remains
reference-only: retain `execution.accepted`, `message.delta`, activity lifecycle,
and terminal event names and their attempt-local ordering.

## Phases

### Phase 1 — Cloud replay boundary

- Update `backend/activities/services/projection.py` (`ActivitySnapshot`, cursor
  helpers, `read_activity_snapshot`) and `backend/activities/api/{schemas,register}.py`
  with the contract above; keep default snapshot behavior unchanged.
- Use `ProjectionCursorGap`/existing privacy-safe error mapping and explicit bounds.
- Add service/API tests in `backend/activities/tests/test_cld005.py` for first and
  multi-page replay, same-cursor repeat, exact `a=0` forward-exclusive boundaries,
  dedicated activity cursor version/type/field parsing and non-interchangeability
  with message cursors, tamper/malformed/wrong-conversation (422), expiry (410),
  retention gap (409), monotonic resume/next values, empty/null/zero metadata,
  fixed high-water behavior under concurrent append, retention inside a page range,
  authorization, and 200-row snapshot compatibility. Add API assertions for the
  privacy-safe error envelope and generated OpenAPI 409/410/422 responses. Add
  cross-attempt tests proving global Activity continuity/cursors advance when
  attempt-local sequences reset. Add no migration unless `makemigrations --check`
  proves one is required.
- Exit: Cloud focused tests and OpenAPI generation expose the additive query,
  metadata, and named error contracts with no Foundry protocol diff.

### Phase 2 — Typed client and web recovery

- Update `packages/cloud-client/src/client.ts`, `src/mappers/allies.ts`,
  `src/activity-projection.ts`, generated OpenAPI artifacts, and focused client tests
  to parse/send replay options and preserve dedupe/turn concatenation semantics;
  verify global continuity rather than the legacy attempt-local field.
- Update `apps/web/app/home/home-workspace.tsx` and its tests to hydrate all replay
  pages, retain a per-conversation cursor, poll forward from it, recover after
  disconnect, and render one coherent assistant turn for long conversations. Add
  tests for multi-page high-water hydration, append-after-high-water delivery on
  the next poll, duplicate/stale/out-of-order pages, 410 origin restart, 409 repair
  state, 422 non-looping failure, deterministic page/byte guards, and conversation
  isolation.
  Preserve current retry work, polling fallback, loading/error/empty/terminal states,
  and accessible retry/check-again controls. Do not change mobile UI; ensure the
  shared client still compiles for mobile.
- Exit: multi-page, duplicate, stale/out-of-order, reconnect, cursor-gap, and
  conversation-isolation tests pass; no direct runtime dependency is introduced.

### Phase 3 — Local-stack evidence and handoff

- Regenerate and verify the pinned Cloud OpenAPI snapshot, restart only the active
  preview backend if the running stack needs the new route, and exercise one fresh
  turn plus a seeded long-running conversation in the browser.
- Capture sanitized evidence of page cursors, monotonic forward polling, no repeated
  visible text, and the retention-gap repair state. Do not commit, push, merge, open
  a PR, or deploy.

## Acceptance criteria

1. A conversation with more than 200 activities hydrates every replayable page up
   to the explicit 64-page/4 MiB bounded contract and renders each assistant turn as
   one coherent response in product order.
2. Repeating a replay request or polling response never duplicates activities or
   visible text; the stored resume cursor advances monotonically.
3. Dedicated activity cursors are signed, expiring, conversation-scoped, and
   authorization-checked with exact forward-exclusive `after_sequence` math from
   origin 0; message cursors are rejected as non-interchangeable. Malformed/tampered
   input returns privacy-safe 422, expiry returns 410, and a retention gap returns
   explicit 409 repair semantics without skipped history.
4. Reconnect/poll from a cursor returns only activities after that cursor, while
   default bounded-tail callers remain compatible.
5. Concurrent Ally conversations remain isolated; stale requests cannot overwrite a
   newly selected conversation; Foundry event vocabulary and attempt-local ordering
   are unchanged.
6. Cloud and Interface focused tests, type checks, OpenAPI verification, and live
   local-stack checks pass; mobile client compilation remains green.

## Validation basis

Cloud (from the Cloud worktree):

```text
make check
make lint
make test APP=activities/tests/test_cld005.py
```

Also run the relevant API/OpenAPI tests (for example
`backend/config/tests/test_api_contract.py`) and `make test APP=activities/tests`
when the focused suite is green.

Interface (from `allies-interface`):

```text
bun run cloud:check
bun run test:run -- packages/cloud-client/test/activity-projection.test.ts packages/cloud-client/test/allies.test.ts apps/web/app/home/home-workspace.test.tsx
bun run typecheck
bun run lint:web
bun --filter mobile typecheck
bun run build:web
```

Run the local preview/browser verification only after these deterministic checks;
record request/response evidence without credentials, private URLs, or customer
content.

## Risks, rollback, and open decisions

- Risk: confusing attempt-local Foundry sequence with conversation-global Activity
  sequence can drop or reorder turns. Mitigation: expose and test separate legacy
  attempt-local and global Activity continuity fields; cursor and client dedupe use
  only `Activity.sequence`; retain cross-attempt tests.
- Risk: unbounded replay/page loops or relation queries. Mitigation: fixed signed
  high-water, Cloud limit/indexed query bounds, and deterministic 64-page/4 MiB
  client guards with explicit tests.
- Risk: older clients/mocks omit new fields or do not understand query parameters.
  Mitigation: additive optional response fields, unchanged default tail semantics,
  compatibility overload, distinct normalized 409/410/422 error handling,
  regenerated OpenAPI, and mobile typecheck.
- Risk: retention begins deleting rows later. Mitigation: preserve explicit 409 gap
  contract and repair-from-origin behavior now; do not invent a retention job in this
  slice.
- Rollback: disable replay use in the web feature and continue default 200-row tail
  polling; revert only the additive Cloud/client contract changes if the preview
  cannot serve them. No data migration or Foundry rollback is expected.
- Open decision (deferred): whether a future SSE `Last-Event-ID` maps directly to
  this cursor endpoint. Resolve only after this polling/replay contract is validated.
