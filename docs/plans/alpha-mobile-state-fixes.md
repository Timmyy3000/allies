# Alpha mobile state fixes

## Outcome

Ship one web PR against `web/ft/finishing-touches` for AT-023, AT-004, AT-022, and AT-026 without changing the conversation contract or the existing top gradient.

## Evidence and constraints

- Nabu `projects/allies/delivery/alpha-test-tracker.md` is the defect source of truth.
- Figma node `315:3009` is an approximate 375x812 width reference: long user bubbles should remain visibly narrower than the message rail.
- Figma node `331:4214` is an approximate 375x812 spacing reference: reduce the empty top region, but keep the first content below the gradient.
- Exact Figma measurements are unavailable because the connected account lacks edit access and the local import does not contain these nodes.
- Preserve activity history; only its summary/current-state presentation changes.

## Implementation

1. **AT-023 — truthful activity lifecycle**
   - Update the production frame model/rendering in `apps/web/app/home/conversation-frame-model.ts` and `conversation-frame.tsx` so a group's summary uses its latest lifecycle entry, including terminal completion, while all entries remain available in the disclosure.
   - Ensure a completed group is historical rather than rendered as current when the turn is complete or the Ally is sleeping; keep reconnect/refresh behavior data-derived.
   - Add focused model/component tests for started → completed, sleep, refresh/replay, and preserved history.

2. **AT-004 — Android keyboard viewport**
   - Add the smallest conversation-shell viewport handling in `conversation-frame.tsx`/`conversation-frame.module.css` (and host CSS only if required): observe visual-viewport `resize` and `scroll` while the composer is focused, apply both `height` and `offsetTop`, keep the composer above the keyboard, and restore bottom-following scroll sensibly when the keyboard closes.
   - Avoid global resize state or a new dependency. Preserve manual scroll position when the user is not following the latest message.
   - Add component tests with a stubbed `visualViewport` for focus, shrink, pan/offset, restore, cleanup, and bottom-follow behavior.

3. **AT-022 and AT-026 — bounded mobile geometry**
   - Cap multiline production user bubbles on mobile at `min(255px, 76%)` while retaining content-fit short bubbles, wrapping, and desktop behavior.
   - Reduce `--chat-history-clearance` from 148px to 136px so the first message moves upward while retaining a 4px guard below the 132px safe-area-aware gradient.
   - Extend the 375x812 chat-frame geometry assertions for bubble width; verify the production-only 136px clearance against the adjacent 132px gradient declaration in review.

4. **Integrated validation and delivery**
   - Run `bun run test:run apps/web/app/home/conversation-frame.test.tsx apps/web/app/home/conversation-frame-model.test.ts apps/web/lib/allies/activity-presentation.test.ts`.
   - Run `CHAT_FRAMES_PORT=3107 CHAT_FRAME_RASTER=false bun run --cwd apps/web test:chat-frames` (PowerShell environment syntax when executed), then `bun --filter web typecheck`, `bun run lint:web`, and `bun run build:web`. These targets were selected after inspecting the root/app scripts and chat-frame Playwright configuration.
   - Perform separate Ponytail and correctness reviews, resolve P0-P2 findings, create the PR with `gh-axi`, verify head/base/checks, update the Nabu tracker to implemented/retest-needed using read-with-revision, conflict merge on 409/428, and readback verification, and establish the required five-minute PR monitor.
   - Prepare the Discord completion summary beginning `Codex here, Timi is still in class`; obtain action-time confirmation immediately before sending.

## Rollback

Revert the PR. The changes are limited to presentation/viewport behavior and focused tests; no data migration, API, or durable schema change is planned.
