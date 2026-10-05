# INT-009 Frontend API Integration

## Status

- Type: feature
- Implementation delegation: always
- Delegation source: explicit user instruction
- Planning mode: full
- Worktree manager: Forest
- Branch: `ft/int-009-frontend-api-integration`
- Worktree path: `C:\Users\USER\Documents\allies\allies-interface\.forest\worktrees\ft\int-009-frontend-api-integration`
- Task workspace: `C:\Users\USER\Documents\allies\allies-interface\.forest\worktrees\ft\int-009-frontend-api-integration\docs\plans`
- Base: `web/dev/onboarding` at merge commit `cf4a4f1` including `origin/dev` commit `66f56c8`
- Review worker: `luna_worker` (`gpt-5.6-luna`, `xhigh`)
- Implementation worker: `luna_worker` (`gpt-5.6-luna`, `xhigh`)
- Created: 2026-08-15
- Target date: not specified
- Current phase: contract confirmed; plan revision and independent review

## Objective

Connect the existing web onboarding experience to the Allies Cloud waitlist boundary in the smallest safe increment, preserving the current visual foundation while making durable draft, greeting, pending-reply, join, restore, loading, and recoverable-error behavior testable and ready for the published CLD-008 contract.

## Context

The current branch contains the static responsive onboarding/story UI and, after merging `origin/dev` at `66f56c8`, the shared Cloud client, browser transport, environment validation, session provider, pinned OpenAPI snapshot, and workspace test/build tooling. The staging contract at `https://cloud.staging.yourallies.io/api/v1/openapi.json` is now confirmed and pinned locally; it exposes the full `/api/v1/waitlist/*` surface. The corresponding public Cloud implementation branch is `codex/cld-008-waitlist` at `a071fa4`, which confirms the snapshot field names and default-off/consent/origin configuration. The accepted UI work also remains available on `origin/web/feat/waitlist-ally-avatar` at `69f5794`; it is a selective source for reusable Ally/onboarding components, assets, store, and tests, not a branch to merge wholesale because its history predates and removes parts of the current Cloud/client foundation.

Nabu is the source of truth for the accepted INT-009 and CLD-008 requirements. The frontend handoff names the waitlist endpoint sequence and requires Cloud-only calls, authenticated browser requests, CSRF/idempotency headers for mutations, revision-aware reconciliation, truthful pending replies, masked joined confirmation, and no browser persistence of durable Cloud state or credentials.

## Requirements

- Preserve the existing responsive story and Ally presentation seam; do not introduce a second avatar/story renderer.
- Keep Cloud authoritative for draft configuration, revision, lifecycle, greeting, reply, join state, and timestamps.
- Use the shared typed Cloud client generated from the pinned staging OpenAPI contract; do not duplicate or silently hard-code the backend contract.
- Route web waitlist requests through a same-origin `/api/v1/waitlist/*` facade that forwards to Cloud. This preserves Cloud's `/api/` and `/api/v1/waitlist/` cookie paths while keeping the browser on the trusted Interface origin; the facade forwards browser `Origin`/`Referer` and never invents a client-side `Origin` header.
- Start the browser session with the waitlist session operation and send credentialed requests with the staging contract's `csrftoken`/`X-CSRFToken` and stable idempotency behavior required by the handoff. Because Cloud scopes `csrftoken` to `/api/`, the same-origin facade derives `X-CSRFToken` from the incoming API-path cookie; the browser never needs to read that path-scoped cookie from the onboarding document.
- Keep the waitlist feature disabled by default; enable it only through explicit web configuration and fail closed when the active consent version is absent.
- Preserve unsaved input on failures and reconcile stale revisions from Cloud before allowing another mutation.
- Render greeting/model output as untrusted plain text and render the attempted reply as sending, then pending only after Cloud acknowledgement.
- Keep the Ally, greeting, pending reply, and masked email visible after joining and after refresh restoration.
- Cover keyboard, touch, reduced motion, narrow screens, loading, throttling, temporary unavailability, validation, stale state, and retry paths.
- Do not create an account, production Ally, conversation, runtime binding, execution, or direct provider/runtime call.

## Acceptance Criteria

1. The onboarding CTA enters a real, testable creation flow without changing the existing story’s visual behavior.
2. Required configuration fields map to the Cloud draft boundary and preserve the last successful revision after refresh.
3. Greeting generation is requested only after required configuration is durable; success and failure states are explicit.
4. Reply submission shows sending before Cloud success and pending after success; failed persistence keeps the exact input and exposes retry.
5. Joining preserves the complete preview and displays only a masked email confirmation.
6. Waitlist network operations use the pinned staging OpenAPI contract and generated client types; the same-origin facade preserves the exact `csrftoken` cookie path and adds `X-CSRFToken` upstream from the incoming API request cookie for unsafe requests.
7. The UI explicitly excludes sign-in and authenticated account creation; no `/api/v1/auths/*` or Google flow begins from the waitlist CTA.
8. Greeting, reply, and join snapshots are mapped to allowlisted view models (`text`, `policy_version`, `generated_at`, `status`, `recorded_at`, `email`, `joined_at`) and unknown fields are not rendered.
9. Appearance serializes as catalog `v1` plus an opaque key derived from the selected shape/color; personality serializes selected traits and note into the one Cloud personality string without exceeding the contract limit.
10. Relevant Vitest unit/component tests, type checks, lint, Cloud contract verification, web build, and browser/manual smoke evidence are recorded. Playwright is not added in this wave because the accepted Interface baseline keeps Vitest as the repository test runner.

## Evidence And Sources

- Nabu: `projects/allies/index.md`
- Nabu: `projects/allies/engineering/specs/waitlist/INT-009-frontend-handoff.md`
- Nabu: `projects/allies/engineering/specs/waitlist/INT-009-responsive-waitlist-preview.md`
- Nabu: `projects/allies/engineering/specs/waitlist/CLD-008-cloud-waitlist-draft.md`
- Nabu: `projects/allies/delivery/tickets/interface/INT-009.md`
- Repository: `AGENTS.md`, `ENGINEERING_STYLE.md`, `docs/templates/PLAN_TEMPLATE.md`, `README.md`
- Repository baseline: `cf4a4f1` (`web/dev/onboarding` merged with `origin/dev` at `66f56c8`)
- UI source branch: `origin/web/feat/waitlist-ally-avatar` at `69f5794` (selective import only)
- Repository API evidence: `packages/cloud-client/openapi/allies-cloud-0.1.0.json` fetched from staging on 2026-08-15, with waitlist paths and generated types.
- Staging API evidence: `https://cloud.staging.yourallies.io/api/v1/docs#/` and `https://cloud.staging.yourallies.io/api/v1/openapi.json`.
- Cloud implementation evidence: public `codex/cld-008-waitlist@a071fa4`, especially `backend/waitlist/api/controllers.py`, `backend/waitlist/services/drafts.py`, `backend/waitlist/capabilities.py`, and `.env.example`.

## Decisions

- Use Forest with one isolated worktree under `.forest/worktrees/`.
- Use `luna_worker` for independent adversarial/simplicity reviews and delegated implementation, backed by `gpt-5.6-luna` with `xhigh` reasoning.
- Use full planning because this crosses a public browser security boundary, durable state, retries/concurrency, and a cross-repository API contract.
- Treat the staging OpenAPI snapshot as the contract source and regenerate the shared client before adding waitlist methods; do not invent a parallel transport contract.
- Reuse the UI branch selectively while retaining the merged `dev` Cloud, session, guidance, and validation foundation; resolve shared files deliberately instead of taking deletions from the older UI branch.
- Branch browser CSRF preparation by request path: waitlist requests use the same-origin facade and the staging contract's `csrftoken`; the facade derives the mutation header from the API-path cookie, while existing auth requests retain their current `csrf_token` behavior until the separate auth contract is revised. Cover both paths with regression tests.
- Use a same-origin waitlist facade at the exact `/api/v1/waitlist/*` browser path so Cloud's host/path-scoped capability and CSRF cookies can be stored and sent by the browser without exposing the HttpOnly capability, requiring a document-level cookie read, or manually setting `Origin`.
- Treat `POST /api/v1/waitlist/draft` as bodyless because the generated contract declares no request body; the `{}` in the older handoff is superseded by the published contract.
- Exclude the UI branch's `sign-in.tsx` and sign-in step; the public waitlist CTA starts session/bootstrap and draft creation instead.
- Map Cloud snapshot payloads with the confirmed implementation shapes: greeting `{text, policy_version, generated_at}`, reply `{text, status: "pending", recorded_at}`, and join `{email, joined_at}`.
- Use explicit web configuration for `NEXT_PUBLIC_WAITLIST_ENABLED` and `NEXT_PUBLIC_WAITLIST_CONSENT_VERSION`; default disabled and fail closed at join when consent is empty.
- Pin the v1 appearance catalog and serializer fixtures: normalize the selected color to lowercase six-digit hex without `#`, serialize `appearance_key` as `${shape}:${hex}`, and send `appearance_catalog_version: "v1"`; serialize personality traits in the canonical `PERSONALITIES` order with `", "`, append `". Note: ${trimmedNote}"` only when a note exists, omit the field when both are empty, and reject rather than truncate values above the Cloud limit.
- Keep one waitlist flow controller: TanStack Query owns the authoritative Cloud snapshot, while React/feature-local interaction state owns unsaved fields, current step, pending action, and retry intent. Do not add a second general-purpose store or a browser queue; use one in-flight guard and one in-memory idempotency key per visible operation.
- Extend the existing `FieldIssue` type once with an optional validation reason code; do not introduce a parallel error hierarchy. Greeting invalidation is limited to changes in `name`, `job`, or the serialized personality; appearance-only edits do not invalidate it.
- Use Vitest and Testing Library for automated coverage; use browser/manual smoke only when staging admission is enabled and an authorized synthetic test is available.

## Risks

- The staging contract is available, but its broad `additionalProperties` response fields for greeting/reply/join need defensive allowlisted view-model mapping and plain-text rendering; the Cloud implementation branch confirms the expected fields.
- A read-only staging session probe from likely frontend origins currently returns `503`; this is an environment-availability signal, not a contract failure, so browser smoke must remain conditional and fixture/transport tests are required.
- The current web baseline imports a PNG from TypeScript without an asset declaration; the UI integration must add the smallest typed asset declaration or use the repository's supported asset path before claiming typecheck green.
- The current web app calls Cloud directly from the browser; without a same-origin facade the host-only `/api/` CSRF cookie is not readable from the onboarding document. The proxy path must preserve the cookie and derive the mutation header server-side; the proxy path and origin matrix must be tested before live mutations are enabled.
- The current onboarding component is a large static presentation file, so adding product state directly could create an unsafe coupling unless the presentation and flow seams stay narrow.
- Browser capability, CSRF, origin, and idempotency behavior can fail in ways that look like ordinary network errors; tests must preserve the distinctions required by the contract.
- The user experience can accidentally imply a delivered or executed reply; pending semantics need explicit assertions.
- The interface facade intentionally does not use an instance-local IP limiter because request headers are spoofable and instances are not a distributed boundary. CLD-008 owns the release gate through Cloud-side distributed admission and generation controls in `backend/waitlist/admission.py`, capability admission in `backend/waitlist/api/controllers.py`, and generation lease/budget enforcement in `backend/waitlist/services/generation.py`; keep the waitlist disabled until the Cloud implementation is deployed and those controls are verified.

## Exceptions

### INT-03 branch prefix

- **Rule:** INT-03 requires web-owned feature branches to use the `web/` prefix.
- **Scope:** This exception applies only to the existing head branch `ft/int-009-frontend-api-integration` and this replacement PR.
- **Reason:** The requested replacement PR must preserve the existing integration branch while changing its target to `web/dev/onboarding`.
- **Risk:** The `ft/` name does not communicate web ownership as clearly as the standard prefix.
- **Mitigation:** The PR targets `web/dev/onboarding`; repository guidance uses platform-prefixed branches for new work; Enkki is not configured to treat arbitrary `ft/**` branches as development targets.
- **Owner:** `@Timmyy3000`.
- **Revisit:** Use a `web/`-prefixed branch for the next web implementation and retire this exception when this integration branch is no longer needed.

## Open Questions

- Which deployed Interface origins should Cloud admit in `ALLIES_TRUSTED_ORIGINS` for local development, staging, and production? The client forwards browser headers; deployment configuration must provide the allowlist.
- What final consent version and joined-draft retention policy should production use? These remain release gates; this branch reads the active staging consent version from explicit web configuration and does not enable join without one.

## Implementation Shape

- `packages/cloud-client/src/client.ts`: add typed waitlist operations, response envelopes, allowlisted `WaitlistSnapshotViewModel`, join confirmation, and safe error mapping. Extend the existing `FieldIssue` with its validation reason code. `POST /draft` is bodyless; mutations accept revision and caller-owned idempotency keys.
- `apps/web/app/api/v1/waitlist/[...path]/route.ts`: forward only the waitlist path to the configured Cloud origin, preserving method/body, browser `Cookie`/`Origin`/`Referer`, safe response headers, status, and `Set-Cookie` values; derive `X-CSRFToken` from the path-scoped `csrftoken` cookie before forwarding. Do not log request bodies or cookies.
- `apps/web/lib/cloud/browser-request.ts`: rewrite only waitlist requests to the same-origin facade, use `credentials: include`, and never set `Origin` manually. Preserve the existing auth-path `csrf_token` behavior and test both branches; the facade owns the waitlist CSRF header because the browser document is outside the cookie path.
- `apps/web/lib/env.ts` and `.env.example`: parse explicit default-off waitlist enablement and public consent-version configuration; join fails closed if consent is absent.
- `apps/web/lib/waitlist/`: keep one flow controller around the gateway, snapshot mapping, pinned appearance catalog v1, deterministic personality serializer, lifecycle/recovery state, and per-operation in-flight/idempotency guards. TanStack Query owns the Cloud snapshot; React/feature-local state owns interaction only. No general-purpose second store, queue, or browser persistence.
- `apps/web/app/(onboarding)/`: selectively reuse the accepted avatar/story and configuration screens, exclude sign-in, and connect the existing CTA to waitlist bootstrap without a second renderer.
- Tests cover the typed client, same-origin facade, browser request preparation, gateway/state transitions, safe mappings, and onboarding accessibility/error paths with Vitest/Testing Library fixtures.
- The first API-backed entry point is the existing onboarding CTA and route; the implementation should preserve the current story renderer and place durable-flow state behind its existing presentation seams.

## Plan

Plan artifact: `.lavish/int-009-frontend-api-integration.html`; the reviewed HTML is synchronized under `docs/plans/` before acceptance, and that copy becomes the durable archive after approval.

## Execution Notes

- Updated `origin/dev` to `66f56c8` using a depth-repaired fetch because the checkout initially had shallow/grafted history.
- Merged `origin/dev` into `web/dev/onboarding` as `cf4a4f1` with no conflicts.
- Installed and verified Forest `v0.8.0`; initialized the repository and created the task worktree.
- Installed the published Lavish CLI globally; the exact forked Lavish package remains the required command source for plan artifacts.
- Fetched the accepted UI source branch at `69f5794` and confirmed that it must be selectively integrated because a wholesale merge would remove the current Cloud/client foundation.
- Fetched and pinned the staging OpenAPI at `https://cloud.staging.yourallies.io/api/v1/openapi.json`; generated waitlist types with `openapi-typescript`.
- Confirmed the staging CSRF cookie name is `csrftoken`; the waitlist facade must derive the mutation header from that path-scoped cookie while `apps/web/lib/cloud/browser-request.ts` preserves the existing auth `csrf_token` branch.
- A read-only `GET /api/v1/waitlist/session` probe returned `503` from staging for the checked frontend-origin candidates; no mutation was attempted.
- Inspected Cloud `codex/cld-008-waitlist@a071fa4`: waitlist is disabled by default, production requires consent/retention/origin configuration, create is bodyless at the HTTP boundary, and snapshot payload fields are explicit in `snapshot_for`.
