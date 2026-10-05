# Beta settings UI

Route: fast. HTML plan: not needed; verify the rendered pages instead.

## Scope and approach

Hide the roster tabs by commenting out their controls; retain the ally list.
Enable the Recipes button with a dismissible, temporary coming-soon toast.
Replace the account presentation with a compact Settings page using the shared
40px BackButton, existing theme tokens and Open Runde typography. Preserve
profile, avatar and sign-out operations and their failure states.
Add an ally-specific Settings route showing avatar, name, label, job and
personality. Name, job and personality are read-only.

Design evidence: Aphrodite allies-current, chat 315:1612 / back control
315:1675: 40px circle, 18px icon, 20px mobile gutter, 16px body / 22px line height.
No named Settings frame was found; adapt those existing primitives.

## Boundaries and dependency

Work is isolated on web/ft/beta-settings-ui. Cloud remains authoritative.
The baseline client has no label field or label mutation. Build a label editor
with an explicit async save callback; do not claim persistence or invent an
endpoint. Connect it when the main task supplies the public label contract.
Generation, visibility and deletion belong to the main task.

## Acceptance and validation

- Ally list remains available on desktop and mobile; no tab controls.
- Recipes click announces exactly “Recipes are coming soon.”
- Both chat settings entry points lead to the selected ally's settings.
- Account edits, upload/retry/removal and logout retain existing behavior.
- Ally details retain newlines and wrap long content. Back returns to that chat.
- Label save UI preserves edits on failure and prevents duplicate submissions.
- Run bun run lint:web, bun run --cwd apps/web typecheck, focused Vitest
  account/home/settings tests, bun run build:web, and browser checks at mobile
  and desktop widths using fixture data, including dark mode.

## Risks and rollback

Label persistence is blocked on the main task's contract. Do not enable a fake
save. Verify Settings separately from exact historical chat-frame snapshots.
Revert this isolated branch's changes to roll back; no backend data changes.

## Delivery evidence

- Web lint passed (34 existing warnings); focused lint of new Settings and
  Recipes files passed with no warnings.
- Web TypeScript check and production build passed.
- 128 focused tests passed: account (8), conversation frame (36), home (78),
  Recipes (1), settings details (2), settings session/read/retry (3).
- Production Playwright beta settings checks passed on desktop and iPhone-sized
  Chromium. Navigation, toast, tab removal, read-only details, no overflow and
  no page errors were verified. Dark/light account and dark ally screenshots
  are under apps/web/test-results/home-smoke and were visually inspected.
- Correctness review checked workspace-scoped reads, session gating, failure
  handling, duplicate-save protection, keyboard controls and back destinations.
  Separate simplicity review retained existing account operations, reused
  BackButton/theme/avatar primitives and added no dependencies.
- Enkii v1.3.0 release inspected. Existing v0.2 workflow remains unchanged;
  no CI upgrade or remote publication was performed in this local side task.

### Main-task integration

`AllySettingsDetails` accepts `label` and `onSaveLabel(label): Promise<void>`.
In settings-client.tsx, supply the Cloud-owned label and the new authenticated
mutation once the public client supports it; invalidate the workspace ally
queries after success. The callback must reject when persistence fails.
Until then the route explicitly reports label editing as unavailable.

## Dev-base correction

Rebased onto current origin/dev d34fe376cb4d0ecd818bfe1307f278a235b56f0d
on 2026-09-10. The prior ef9ddf1 base was stale. Kept dev's activity,
approval, routine and attachment behavior while resolving conflicts.
Activity presentation/stream, frame model, approvals and attachment sources
match dev exactly. The rebased change passed 191 focused tests, web lint
(48 existing warnings), and production build including TypeScript checking.
The local production preview runs on port 3000 against staging Cloud.

## Accepted finishing changes

The owner accepted regular (400) system typography for chat messages, activity,
thinking, queue and composer text. Markdown emphasis remains distinct.
Roster previews select the latest nonempty Ally-authored text, including durable
assistant replies; newer user text is excluded. Reads scan at most four pages
of 20 messages. If that bounded window has no reply and history remains, the
preview says "Open conversation" rather than claiming there has been no reply.
Latest-message timestamps and activity still drive presence.

Final validation: production build including TypeScript passed; 85 focused
Home/preview tests and four desktop/mobile Settings/chat browser tests passed.
Scoped lint passed with the pre-existing conversationQuery dependency warning.
Earlier account, activity and approval validation remains applicable to
unchanged surfaces. User approved the result and requested a PR into dev.

## Dev integration — 11 September 2026

Merged origin/dev at 276795b (#51) at the owner's request. This brings revision-safe label editing, per-Ally roster visibility, shared Cloud contract/client validation, and Enkii 1.3.0. The prior label-API limitation is resolved. Chat settings opens the imported editor; View ally details preserves the existing avatar/name/job/personality page, which now displays the actual label. Conversation header route fallbacks remain available. There are no Ally deletion commits or delete-Ally client method in this dev revision; deletion cannot be imported yet.

Validation: 136 Home/frame tests, 24 Cloud-client tests, five settings-page tests, contract verification, production build/TypeScript, and four desktop/mobile settings/label browser checks pass. Updated the keyboard-focus test to include the added details link. Separate correctness and simplicity reviews checked conflict resolution, save revision handling, route preservation, and absence of duplicate editor state. No outstanding merge findings.

## Enkii follow-up — 11 September 2026

Addressed PR #50's three code findings: exclude suffix-only durable replies from roster previews so older history can supply a complete answer; retry both failed settings queries in one action while waiting for an uncached workspace before fetching its Ally; remove the duplicate word in the onboarding heading. Updated the PWA smoke check to target the visible roster link instead of the intentionally hidden tab.

Validation: 99 focused Home/preview/settings unit tests and production build/TypeScript pass. Regression coverage exercises partial replies followed by older history and both cached-workspace and uncached-workspace retry paths. Separate local correctness and simplicity passes checked query dependencies, unchanged session recovery, pagination continuation, and minimal scope; no outstanding findings.

Browser validation: five desktop/mobile/WebKit settings-navigation and PWA-install checks pass against the rebuilt production server on port 3000.
