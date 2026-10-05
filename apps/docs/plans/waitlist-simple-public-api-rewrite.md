# Simple Waitlist Public API Rewrite Plan

> Planning mode: fast Markdown plan, authored by the orchestrator at the product owner's explicit request. No planning worker or Lavish artifact was used.

## Feature Overview

- Problem: the waitlist preview is implemented as a resumable anonymous workflow protocol, while the intended product is a short disposable registration funnel.
- Target users: visitors creating an Ally preview and joining the waitlist.
- Source evidence: the `allies-cloud` `dev` checkout, the current Interface waitlist flow, and the product owner's clarified four-step journey.
- Success outcome: a refresh starts over; Save creates one entry and one greeting; final email submission links the reply and email to that entry.

## Why the Current Version Feels Overengineered

The current Cloud contract optimizes for durable anonymous resume, concurrent retries, and recovery from an uncertain AI result. That produces:

- session bootstrap and capability-cookie rotation;
- CSRF and origin handling around cookie-authenticated public endpoints;
- separate create, restore, configure, greet, reply, and join operations;
- revision compare-and-set on every mutation;
- seven exposed lifecycle states;
- a `WaitlistOperation` receipt for idempotency and leases;
- greeting polling and unknown-outcome reconciliation;
- a frontend proxy that rewrites origins, cookies, and CSRF;
- a 469-line Interface flow controller mirroring the backend protocol.

Those mechanisms are coherent for a resumable workflow, but resumability is now explicitly unwanted. The refresh-reset requirement directly conflicts with the capability-bound restore model, which is why session rotation and cookie rewriting kept growing.

## Scope

### In Scope

- Replace the browser session/draft protocol with a disposable per-page attempt.
- Submit all Ally configuration only when the visitor presses Save.
- Create the waitlist entry and generate its greeting in one public request.
- Hold the returned opaque attempt token in React memory only.
- Show the email modal when the visitor sends a reply.
- Submit the reply, email, and consent together to complete the entry.
- Remove waitlist cookies, CSRF, restore, revisions, lifecycle polling, and the stateful Interface facade from this funnel.
- Keep bounded validation, AI output validation, rate limiting, consent evidence, and retention cleanup.

### Out of Scope

- Restoring unfinished work after refresh.
- Creating an account, production Ally, Workspace, or conversation.
- Sending the visitor reply to OpenAI or any runtime.
- Generalizing the API for future onboarding products.

### Decisions

- Do not persist the reply until the visitor submits their email. The final request stores reply, email, and consent atomically.
- Existing staging draft data is disposable. Replace the schema directly; do not retain a compatibility model or data migration.

## Target Contract

### 1. Create preview

`POST /api/v1/waitlist/entries`

Authentication: public. Trusted-origin CORS, request-size limits, and a bounded creation/generation rate limit. No cookie and no CSRF.

```json
{
  "attempt_id": "client-generated-random-id",
  "name": "Sally",
  "appearance_catalog_version": "v1",
  "appearance_key": "rolly:ff4560",
  "job": "Personal task manager",
  "personality": "Concise and encouraging"
}
```

```json
{
  "status": "success",
  "data": {
    "attempt_token": "opaque-one-time-token",
    "greeting": "Hello — I’m ready to help you plan your day. What should we start with?"
  }
}
```

Cloud creates the row before calling OpenAI, generates exactly one greeting, validates it, and stores it. Repeating the same `attempt_id` returns the same row/greeting rather than generating another one. The server stores only a digest of `attempt_token`.

### 2. Complete registration

`POST /api/v1/waitlist/entries/complete`

```json
{
  "attempt_token": "opaque-one-time-token",
  "reply": "Help me plan this week.",
  "email": "person@example.com",
  "consent_version": "waitlist-v1"
}
```

```json
{
  "status": "success",
  "data": {
    "email": "p****n@example.com"
  }
}
```

Cloud validates the token, normalizes the email, stores reply/email/consent atomically, marks the entry joined, and invalidates the token for further mutation. The reply is never sent to OpenAI.

## Frontend Interaction Shape

```text
local form state
  → Save
  → POST /waitlist/entries
  → show stored greeting
  → visitor presses Send
  → open email modal (no network request)
  → submit email
  → POST /waitlist/entries/complete
  → show joined confirmation
```

Frontend state becomes one small hook/reducer:

```text
editing → saving → greeting → collecting_email → joining → joined
                 ↘ error/retry             ↘ error/retry
```

Refresh naturally resets the flow because configuration and `attempt_token` live only in memory.

## Phases

### Phase 1 — Replace the Cloud contract

- Add the two endpoints and compact request/response schemas.
- Reuse the existing OpenAI provider and output validation.
- Replace capability-bound authorization with a hashed per-attempt token.
- Keep one bounded retry identity (`attempt_id`) only for the costly create/greeting request.
- Simplify the model to entry data, greeting, optional completion data, token digest, and timestamps.
- Delete the session, restore, configuration, greeting, reply, and join endpoints in the same cutover.
- Exit: API tests prove one greeting call, safe duplicate Save, atomic completion, invalid-token rejection, rate limits, and no reply-to-AI path.

### Phase 2 — Replace the Interface protocol

- Replace `WaitlistFlowProvider` with a small local mutation hook.
- Submit configuration only from Save.
- Keep `attempt_token` in component/context memory only.
- Open the email modal locally when Send is pressed; complete after email submission.
- Remove draft restore, revisions, lifecycle reconciliation, polling, idempotency maps, and retry receipts from the client.
- Delete the waitlist facade and call Cloud directly under configured CORS.
- Exit: refresh returns to the first onboarding step, and repeated full registrations work in the same tab.

### Phase 3 — Complete the clean cutover

- Regenerate the Cloud client from the new OpenAPI contract.
- Run one end-to-end staging registration and verify one OpenAI request.
- Remove superseded Cloud routes, capability/session code used only by waitlist, operation receipts, and obsolete tests.
- Remove the uncommitted `POST /waitlist/session` experiment rather than deploying it.
- Exit: no Interface request references `/waitlist/session`, `/draft/configuration`, `/draft/greeting`, `/draft/reply`, or `/draft/join`.

## Acceptance Criteria

1. A visitor can complete the configured four-step product journey with two public API mutations.
2. Save creates one database entry and at most one OpenAI greeting for its `attempt_id`.
3. Refresh clears the Interface state and starts a new attempt without cookie deletion or session rotation.
4. Sending a reply opens the email modal immediately and does not call OpenAI.
5. Email submission stores reply, normalized email, consent, and joined timestamp on the same entry.
6. A stolen/guessed database ID is insufficient to complete an entry; only the opaque attempt token works.
7. Direct duplicate requests do not duplicate AI generation or joined entries.
8. The browser no longer needs waitlist capability cookies, CSRF handling, restore polling, or the stateful local facade.

## Focused Validation

### Cloud

- API tests for create, duplicate create, provider failure/retry, invalid output, rate limiting, completion, duplicate completion, invalid token, consent, and email normalization.
- Assert provider call count is exactly one for repeated `attempt_id`.
- Assert reply is absent from every provider request.
- Run the repository's locked Cloud checks (`make check`, focused waitlist tests, and OpenAPI contract tests).

### Interface

- Hook/component tests for Save, greeting success/error/retry, Send → email modal, completion, and refresh reset.
- Contract test that only the two new paths are called.
- Run `bun run test:run`, `bun run typecheck`, `bun run lint:web`, and `bun run build:web`.
- Manual desktop drawer, mobile `/onboarding`, localhost, and phone-over-Wi-Fi checks.

## Risks, Rollback, and Estimate

- AI latency remains intrinsic to Save. Keep the existing bounded provider timeout and show an honest retry state.
- A single combined create/greeting response needs `attempt_id` replay so a lost response does not create a second paid generation.
- Existing draft rows are intentionally dropped by the replacement migration.
- Rollback is a code/database deployment rollback, not an in-process compatibility path. No old waitlist routes, models, or client methods remain available.
- Estimated implementation: 2–4 focused engineering days, including Cloud contract/model work, Interface replacement, generated client update, tests, and staging verification.
