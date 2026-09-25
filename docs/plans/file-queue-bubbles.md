# Queued file/photo messages render as editable bubbles with a dead Cancel

## Scope

Web conversation only (`apps/web/app/home`). No Cloud, Foundry, mobile, or contract changes.
Bug: a file/photo message sent while the Ally is thinking renders as a normal green
timeline bubble containing the composer-style `Ready · size` card plus a black
`Cancel` pill (see report screenshot: `Futur I und Futur II.pdf`, `Ready · 76.6 kB`,
`Cancel`, `I want ot understrnad Futur 1` above `Thinking..`). That in-bubble
`Cancel` cancels the transfer and restores the draft but never removes the queued
message, leaving an orphan queue item plus a duplicated draft. File messages are
also stripped from the footer `QueueStack`, so text queues show without their file
siblings and ordering looks broken.

## Owner correction (accepted 2026-09-24)

Queued messages with attachments belong in the queued pill UI above the composer
— with attachment thumbnails like ChatGPT's queued row — not as timeline text
bubbles. This supersedes the adversarial outcome that kept all file messages as
timeline bubbles for progress display. Revised rule: a queued file message
renders in exactly one place — the footer `QueueStack` pill with thumbnails —
unless its transfer is actively uploading, checking, or failed, in which case it
keeps the timeline progress bubble with its retry/cancel controls.

## Approach

1. Route every in-bubble `Cancel` for a queued file message through the existing
   `removeQueuedMessage` path (`home-workspace.tsx:2807`), which already does
   transfer-cancel + queue-removal + draft-restore for local file messages.
   Local (pre-admission) Cancel delegates fully; cloud (post-admission) Cancel
   keeps its `files.cancel` + draft-restore in `render()` (it owns the draft
   payload mapping) and then calls through for `deleteQueuedMessage`
   tombstoning, cancel-before-delete so an in-flight upload cannot complete
   against a deleted queue.
2. Render queued file messages as `QueueStack` pills with thumbnails instead of
   timeline bubbles. `buildQueuedFrameMessages` carries per-file previews
   (`id`, `name`, `src` for local items, `ready` for remote fetch gating);
   `QueueStack` renders up to 3 thumbnails plus an overflow count through a
   `renderQueueAttachments` callback so workspace/ally scoping stays out of the
   frame model. Only messages with an actively uploading, checking, or failed
   transfer keep the timeline progress bubble (via `queuedAttachmentQueueIds`).
3. Queued file bubbles that remain (active transfers) keep the `Queued` status
   label; bubble rows stay read-only once prepared/admitted, and `pending()`
   renders photo thumbnails via the shared `FileThumbnail`.
4. Cover with focused tests: in-bubble Cancel removes the queue item without
   duplicating the draft; queued file pills carry previews and render thumbs;
   the bubble/queue split keeps actively transferring messages in the timeline
   and waiting ones in the queue; no later message is dispatched before an
   earlier uploading file message.

## Affected surfaces

- `apps/web/app/home/home-workspace.tsx` (`queuedAttachmentQueueIds`,
  `transferMessageIds`, `frameModel`, `messageAttachments`,
  `renderQueueAttachments`, `removeQueuedMessage`, `buildQueuedFrameMessages`)
- `apps/web/app/home/conversation-frame-model.ts`
  (`ProductionQueuedMessageModel`, new `QueuedAttachmentPreview`)
- `apps/web/app/home/conversation-frame.tsx` (`renderQueueAttachments` prop)
- `apps/web/app/home/conversation-frame-primitives.tsx` (`QueueStack`)
- `apps/web/app/home/conversation-frame.module.css` (`.frameQueueThumbs`)
- `apps/web/app/home/attachments/use-conversation-files.tsx`
  (`render()` transfer actions, `pending()` thumbnails, exported
  `FileThumbnail`)
- Tests beside each file; chat-frame fixtures only if a new visual state is added.

## Acceptance

- [ ] In-bubble Cancel on a queued file/photo message removes it from the queue,
      cancels its transfer, and restores exactly one draft (no orphan, no duplicate).
- [ ] A queued file message renders in the footer queue pill with thumbnails
      (up to 3 + overflow count), never as a timeline bubble, unless its
      transfer is uploading, checking, or failed.
- [ ] A later message cannot overtake an earlier uploading file message to the
      same Ally; retry preserves successful uploads and resends explicitly.
- [ ] Queued photos show thumbnails, queued PDFs show icon + name tooltip,
      matching the sent-state rendering.

## Validation

- `bun run lint:web` in the worktree.
- Focused vitest: `home-workspace.test.tsx`, `conversation-frame-model.test.ts`,
  `conversation-frame.test.tsx`, attachment tests.
- `bun run --cwd apps/web test:chat-frames` only if fixtures change.
- Manual: send text, then a PDF + text while thinking; Cancel the file message;
  confirm one draft restore and an empty queue.

## Risks

- Touching queue/failure paths risks double-send or lost drafts; mitigated by
  routing through the single tested `removeQueuedMessage` path and asserting
  single-draft-restore in tests.
- Per INT-01 no backend rules are duplicated; all send/cancel calls stay on the
  existing Cloud contract.

## Rollback

Revert branch `web/fix/file-queue-bubbles`; no migrations or contract changes.

## Unresolved decisions

- None remaining; thumbnail-strip vs chip resolved by the owner toward
  thumbnails (max 3 + overflow count) in the queue pill.

## Follow-up revision (2026-09-25, uncommitted at plan time, now implemented)

Owner reports on the first revision: (a) queue-pill text renders centered
instead of left; (b) an uploading file message flickers — bubble during upload,
then back to the pill when finished.

Root causes found: (a) the thumbs wrapper inherited the pill's `flex: 1` span
rule, squeezing the text span into the pill's center — fixed with a
`span.frameQueueThumbs` flex override; (b) the bubble/pill split keyed only on
local transfer records, so cloud uploading/checking/failed messages without a
local record were misclassified as waiting pills and lost their timeline
retry/cancel — fixed by also treating active `preparation`
(`uploading`/`failed`/`needs_retry`) and in-flight remote file states
(`pending`/`receiving`/`validating`/`failed`/`rejected`) as timeline bubbles.
Pills now render lightweight thumbnails internally (`img` for local `src`,
file icon otherwise; remote-ready thumbs open the existing preview modal), so
no session-scoped renderer crosses the frame-model boundary.

Enkii P1s (both accepted and fixed): P1-1 as above; P1-2 — pill trash on cloud
file messages called only `deleteQueuedMessage`, dropping attachments with no
transfer-cancel or draft restore — fixed with cancel-before-delete
(`files.cancel` with `revision`, fail-closed on stale revision, then
`deleteQueuedMessage`) reusing the in-bubble draft mapping.

Validation added: pill-thumbnail rendering tests, preparation-aware split
tests, and a pill-trash integration test asserting cancel-before-delete
ordering plus single draft restore.

## Adversarial review (non-independent, in-session — original revision)

Independent `codex/sol_review_worker` and generic `reviewer` workers were both
unavailable in this harness (dispatch failures recorded in chat); the owner
chose a luna reviewer, which is also unavailable, so this review ran
in-session and is labeled non-independent.

Verdict: Needs revision — accepted into the approach above.

- ADV-001 (Major): the first draft moved file messages out of the timeline into
  `QueueStack`, which would regress INT-106 per-file progress (`render()` shows
  Uploading % / Checking / Ready; `timelineMessages` deliberately includes
  queued file items). Fixed by keeping progress bubbles and adding the queued
  label instead.
- ADV-002 (Major): cloud Cancel needs cancel-before-delete ordering
  (`files.cancel` with `revision`, then `deleteQueuedMessage`) so an in-flight
  upload cannot complete against a tombstoned queue; stale-revision failure
  must keep the queue item. Folded into step 1.
- ADV-003 (Minor): `MessageViewModel` already carries `files`; only local
  `QueuedMessage.fileTransferId` needs a manager lookup. Narrowed the model
  addition to optional `fileSummary` derived from existing data.
- ADV-004 (Minor): `pending()` is reachable only for immediate+file sends;
  enhance thumbnails there only, do not rebuild it.
- ADV-005 (Question, answered): photos vs PDFs already branch in
  `FileThumbnail`; no separate photo path needed.
- ADV-006 (Minor): dispatch is already FIFO single-flight; tests assert UI
  single-representation + order on top.

Simplicity review skipped with reason: the revision removes machinery rather
than adding it (single removal path, derived data, no new contracts).
