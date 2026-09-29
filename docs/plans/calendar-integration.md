# Calendar Integration Plan

_Route: fast. HTML required: no (small change on an established pattern; Markdown is the accepted plan)._
_Branches: `ft/calendar` in Cloud, Foundry and Interface, each into `dev`._

## Objective

Let an Ally read and manage the workspace's Google Calendar, following the shipped Gmail
pattern: Cloud owns the Google credential and every call, Foundry only relays, and each
Google product is its own connection with its own per-Ally access. Never bundled with Gmail.

## Decisions

| ID | Decision | Source |
| --- | --- | --- |
| D1 | Calendar is its own `IntegrationSecret` row (`provider_key="calendar"`), connected, granted, and disconnected independently of Gmail. | Owner |
| D2 | Cloud-relayed tool like Gmail. The Google Workspace CLI is not used: it would put a Google credential on the Ally's volume and skip live grant checks. | Owner, after review |
| D3 | Scope `calendar.events` (+ `email` to name the account). Not `calendar`: no calendar settings or sharing. | Owner |
| D4 | Actions: `list_events`, `get_event`, `create_event`, `update_event`, `delete_event`, on the primary calendar only. | Owner |
| D5 | Grant levels `read` and `write`. The Ally access switch grants `write`. | Owner |
| D6 | A write that would notify other people (event with guests; update or delete of an event that has guests) needs a confirmation from an earlier user turn, bound to the exact request, usable once. Solo events go straight through with `sendUpdates=none`. | Owner |
| D7 | One kill switch for now: `ALLIES_GMAIL_ENABLED` covers all Google integrations. | Ponytail |
| D8 | Drive, Docs and Sheets are out of scope. | Owner |
| D9 | Ally tools default to full provider capability. Events also take colour (Google's 11 names, or default), recurrence, custom reminders, visibility, busy/free, a Google Meet link and guest permissions, on create and update, and reads return them. Detail-only changes on an event with guests stay confirmation-gated. | Owner, 2026-09-30 |

## Approach

- **Cloud:** `IntegrationSecret`, grants, connect sessions, the replay table and the
  callback are reused. The provider rides in the sealed connect handshake, so the existing
  redirect URI and callback path serve both products and no migration is needed. New
  `calendar_tool.py`, registered on the existing relay endpoint as integration `calendar`.
  Grant allowlists become a `(provider, level)` map.
- **Foundry:** the relay is already provider-blind. Add the `allies_calendar` Hermes tool
  and plugin, image copy lines, patch entries (activity names, toolset enablement) and
  `calendar_read` / `calendar_write` in the activity vocabulary (also mirrored in Cloud).
- **Interface:** provider-aware connection client, an Access row per product on the Ally
  profile, and a Connections row per product on the account page.

## Acceptance

- Connecting Calendar never changes Gmail state, and the reverse.
- A read grant cannot create, update or delete. No grant or no connection is denied.
- An event with guests is not changed until the user confirms in a later message; the
  confirmation cannot be replayed or reused for different fields.
- A retried tool call replays instead of writing twice; a lost write response is reported
  as unknown, never repeated.
- No Google credential reaches Foundry or the Ally's volume.

## Validation

- Cloud: `make check`, `make lint`, `make test APP=integrations`, then the full suite.
- Foundry: `make lint`, runtime and backend test suites, and the hand-edited Hermes patches
  applied in Dockerfile order to the pinned Hermes commit.
- Interface: `bun run typecheck`, `bun run lint`, `bun run test:run`, `bun run cloud:check`.
- Staging: connect Calendar for a test workspace, exercise read, solo write, guest write
  with confirmation, delete, revoke, and disconnect.

## Rollout order

1. Foundry (image gets the tool; inert until Cloud serves `calendar`).
2. Cloud (adds the routes and relay branch).
3. Interface (shows the rows).

Foundry needs an image rebuild and runtime release before the tool exists on a machine.
Google Console: enable the Calendar API and add the `calendar.events` scope to the consent
screen for the shared OAuth client. The redirect URI does not change.

## Risks and ceilings

- Attendee updates replace the guest list; Google may reset responses for existing guests.
- Primary calendar only; no recurring-event series edits beyond what `events.patch` does.
- The relay in `allies_calendar.py` is a copy of Gmail's. Extract a shared one at the third
  integration.
- `calendar.events` is a sensitive scope: verification is lighter than for Gmail or Drive.

## Unresolved

- Whether Calendar needs its own OAuth client or consent-screen branding. Default: shared.
