# Web Ally profile (DSN-005 v3)

Route: fast. Branch `web/ft/ally-profile` → `dev`. Depends on Cloud PR
alliesai/allies-cloud#63 (optional `appearance` on the settings PATCH).

## Scope

Replace the web Ally settings sheet (`app/home/ally-settings-dialog.tsx`) with
the accepted DSN-005 v3 profile. Everything shown must be backed by Cloud today.

| Section | Behaviour | Cloud contract |
| --- | --- | --- |
| Identity | Avatar, name, label pill | `GET /workspaces/{w}/allies/{a}` (already loaded) |
| Edit label sheet | One field, 2–3 words, Save | `PATCH …/settings` (existing revision fence) |
| Change look sheet | Colour and shape from the existing catalog | `PATCH …/settings` with `appearance` (#63) |
| About | Collapsible Job and Personality, read-only | same Ally payload |
| Routines | ≤3 cards, then "View all N" expands in place; tap opens existing `RoutineDetail` | `GET /workspaces/{w}/routines?ally_id=` |
| Delete a routine | "Delete in chat" closes the profile and sends an identified request to the Ally | existing chat send |
| Access | Gmail row with a per-Ally toggle (read grant); "Connect Gmail" when not connected | `GET/POST …/integrations/gmail`, `/grants`, `/connect` |
| Gmail return | `/integrations/gmail/callback` completes the exchange and returns to the Ally | `GET /integrations/gmail/callback` |
| Delete Ally | Row at the bottom opens the existing typed-confirmation flow | unchanged |

Out of scope: editing name, job, or personality (view-only by decision);
services other than Gmail; the mobile profile (separate `mobile/` PR); account
settings (DSN-006, next episode).

## Approach

- `packages/cloud-client`: pin the OpenAPI snapshot from Cloud `b2a57b7`
  (generated). Add optional `appearance` to `AllySettingsInput`. Add
  `getGmailConnection`, `beginGmailConnect`, `setGmailGrant`, and
  `completeGmailConnect` with strict zod mappers. A null status means
  "not connected".
- `apps/web/app/home/ally-profile.tsx` (new) renders the profile inside the
  existing `BottomSheet` shell. The label save and delete logic currently in
  `ally-settings-dialog.tsx` moves unchanged into sub-views, so the conflict,
  unknown-outcome, and deletion polling behaviour is preserved.
- Toggling access sends `level: "read"` or `"none"`. The toggle is optimistic
  with rollback on failure, and duplicate taps are ignored while a request is
  in flight. Send is never granted from the profile; send stays behind in-chat
  consent.
- Connect: the `Idempotency-Key` is generated per click, and the browser is
  sent to `auth_url` only when the host is `accounts.google.com` over https.
- Callback page: reads `code` and `state`, calls Cloud once, shows
  connected/failed, and links back. The `code` is never logged.

## States (INT-02)

- Routines: loading skeleton, empty (section hidden), error with Try again.
- Access: loading, not connected (Connect), connected with toggle,
  saving, failed (rolled back, inline message), and provider unavailable (503).
- Label and look: saving, conflict (refetch and keep draft), failure.

## Acceptance

- The profile matches the Pencil frames YTMnL, hkSVl, r5V6EK, jbmso, qwWPl, and
  Mkpuj at mobile widths and stays centred at a maximum of 480px on desktop.
- No helper subtitles. Only label and look are editable.
- A stale revision on the label or look shows the conflict message and does not
  overwrite.
- The access toggle never shows a state that Cloud did not confirm after the
  request settles.
- Keyboard: every control is reachable, sheets trap focus, and Esc closes them.
  Reduced motion disables the expand and sheet animations.

## Validation

`bun run typecheck`, `bun run lint:web`, `bun run test:run` (new tests for
the cloud-client Gmail mappers, the grant toggle rollback, the look save
payload, and routines states), `bun run build:web`, and a manual check in the
browser against the Pencil frames.

## Risks

- #63 must merge before this lands. Until then the look save returns 422; the
  sheet shows its failure state.
- The Gmail redirect URI must point at `/integrations/gmail/callback` in
  each environment (Cloud `ALLIES_GMAIL_REDIRECT_URI`). This is recorded in
  the PR.
- PR size: roughly 700 lines of hand-written code, plus generated files.
  Kept together because the profile is one screen; the Gmail client and
  callback page are the natural split if review asks for it.

## Revision after adversarial review (ADV-001…009, all accepted)

Delivery is split into two stacked PRs (ADV-009):

- **PR A — `web/ft/ally-profile`:** cloud-client `appearance` input and the
  pinned snapshot; the profile with identity, label sheet, look sheet, About,
  routines, and the Delete Ally row. No Access section.
- **PR B — `web/ft/ally-access-gmail`** (based on A): the Gmail client
  methods, the Access section, and the callback page.

Contract decisions:

- **ADV-001:** Connect from the profile sends
  `{entry_point:"in_chat", ally_id, grant_level:"read"}`, following the DSN-005
  decision that connecting grants this Ally access in one step. A test asserts
  the request body.
- **ADV-004:** The toggle is on when the grant level is `read` or `send`.
  Turning it on from `none` sends `read`. Turning it on when the Ally already
  has `send` does nothing, so `send` is never downgraded. Turning it off sends
  `none`, which removes `send` too. A test covers this.
- **ADV-002:** Before navigating to Google, store `{workspaceId, allyId}` in
  sessionStorage under `connect_session_id`. The callback page reads the
  target, accepts it only as an internal `/home/<uuid>` path, and otherwise
  goes to `/home`.
- **ADV-003:** The callback page uses a ref latch so the exchange runs once.
  It calls `history.replaceState` to strip `code` and `state` before the
  request, sets `Referrer-Policy: no-referrer` through route metadata, and
  loads no third-party assets. A 409 or 422 triggers a status re-check: if
  Gmail is connected it shows success, otherwise it shows "That link expired.
  Try connecting again."
- **ADV-005:** Error mapping for Access:
  - `refresh_revoked` → the row shows Reconnect.
  - `scope_insufficient` → Reconnect, which asks for scopes again.
  - 403 `grant_denied` or no write capability → toggle disabled.
  - 503 → "Gmail isn't responding. Try again."
  - 401 → the existing session-ended handling.
- **ADV-006:** The Idempotency-Key is `crypto.randomUUID()`, and Connect is
  disabled while a request is in flight.
- **ADV-007:** Verified that `AllySettingsRequest` uses `extra="forbid"`, so
  before #63 the look save fails with 422 and never silently drops the change.
  PR A merges only after #63 is deployed.
- **ADV-008:** Unit tests for the `auth_url` guard (https only, host exactly
  `accounts.google.com`, reject userinfo and lookalike hosts) and for the
  callback latch and error mapping.
- Disconnect stays on the account Connections page (DSN-006) and is not part
  of the profile.
