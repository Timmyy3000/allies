# Steer any queued message

Route: fast. Grant: land ("land this fix into nightly").

## Problem

Users expect every queued message to offer **Steer**. Today Steer only appears for the
head of the browser's local outbox. The browser drains that outbox into Cloud almost
immediately, so in practice messages sit in Cloud's queue, which has Remove but no Steer.

## Outcome

Every Cloud-queued user message (not yet claimed, not uploading files) shows Steer and
Remove. Steer makes that message the next turn and stops the active turn. The browser
outbox shows no Steer; its items reach Cloud within moments.

## Approach

Cloud (`services/cloud/backend/chat`):
- Add nullable `Message.steered_at` (migration).
- `_claim_next_turn_locked` orders steered messages first (latest steer wins), then
  `sequence`, `id`.
- New `POST /workspaces/{w}/conversations/{c}/messages/{m}/steer`, service
  `steer_queued_message`. Requires WORKSPACE_WRITE, the message to be a live, unclaimed
  user send in the conversation, and an active turn; else 409 `steer_unavailable`.
  Sets `steered_at`, then stops the active turn with `_stop_turn`. Idempotent: repeating
  on an already-steered or already-claimed message returns success without a second stop.
- Remove the old text-based `POST /conversations/{c}/steer` endpoint and
  `steer_conversation` (only caller is the web local-outbox path being deleted).

Client: regenerate OpenAPI (`bun run cloud:fetch` or update the JSON, then
`bun run cloud:generate`); replace `steerConversation` with `steerQueuedMessage`.

Web (`apps/web/app/home`):
- Queue item model carries `steerable: boolean`. `QueueStack` renders Steer per item
  where `steerable` and a turn is in progress, replacing the single `actionId`.
- Cloud-queued items: `steerable` when not uploading and not the active message.
- Delete the local-outbox steer path (`steerQueuedMessage` lock dance,
  `steerableQueuedMessageId`, `STEER_ERROR` if unused).

## Acceptance

- Cloud test: two queued messages behind an active turn; steering the second stops the
  active turn and the second is claimed next; the first runs after.
- Cloud tests: 409 without active turn, 404/409 for claimed/foreign/deleted message,
  idempotent repeat.
- Web test: every Cloud-queued item renders Steer while a turn runs; click calls the
  client with that message id.

## Validation

Cloud: `uv run python manage.py makemigrations --check --dry-run`, `uv run pytest chat`,
`uv run ruff check .`, `uv run ruff format --check .`.
Web: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint`,
`bun run build:web`.

## Risks

- Mobile app may call the removed endpoint: verified no caller outside web.
- Stop then claim race: `complete_turn` already claims next under the conversation lock,
  so ordering by `steered_at` is enough.
