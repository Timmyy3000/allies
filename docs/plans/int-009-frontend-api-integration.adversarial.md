# INT-009 adversarial review

Date: 2026-08-15  
Worker: `luna_worker` (`gpt-5.6-luna`, `xhigh`)  
Verdict: blocked pending plan revision; no P0 findings, but the following P1 findings must be resolved before implementation.

## P1 findings

1. **CSRF topology is not viable as a cookie-name change alone.** The Cloud cookie is scoped to the Cloud host and `/api/`; a browser page on a different frontend origin cannot read it through `document.cookie`. Define a same-origin proxy/rewrite or another safe CSRF channel, and add a browser test proving session bootstrap → cookie → mutation header.
2. **Origin/CORS behavior is underspecified.** Every waitlist operation requires trusted `Origin` or `Referer`; the browser must not set `Origin` manually. Add the deployment/origin matrix and trusted/rejected-origin coverage.
3. **Draft creation is bodyless in the pinned contract.** The plan must not describe `POST /api/v1/waitlist/draft` as sending `{}`; generate and test a bodyless POST.
4. **The UI source branch can reintroduce sign-in.** Exclude sign-in files/routes and route the CTA to waitlist session/create; assert that no `/auths/*` or Google flow starts.
5. **Greeting/reply/join response fields are open-ended.** Define explicit allowlisted view models; ignore or reject raw email and unknown model fields, and preserve plain-text rendering.
6. **UI-to-API mapping is missing.** Define the versioned appearance catalog mapping, personality serialization, null/omission semantics, and exact configuration fixtures.
7. **Consent is required but not configured.** Define the staging consent source and fail closed/disable join when no approved consent version is present.
8. **State model is incomplete.** `pending_claim` must remain restorable and visible after join; add bootstrap/restoring/failure/retry/joined-restored/expired/claimed states and focus/error behavior.
9. **Greeting invalidation is missing.** Define which configuration changes invalidate a generated greeting and how stale output is hidden.
10. **Concurrency/retry rules are incomplete.** Define per-operation locking, duplicate-click prevention, out-of-order response handling, same-key retries, and explicit `generation_outcome_unknown` recovery.

## P2 findings

- Preserve validation error `code` values in the Cloud error view model.
- Add Playwright dependency/config/CI or remove Playwright from acceptance; current Vitest globs do not include the sourced `*.spec.ts`.
- Add labels, descriptions, `aria-pressed`, live announcements, focus restoration, disabled mutation controls, and retry assertions.
- Define default-off/staging rollout, static fallback, and join remediation.
- Use mocked full-flow tests and synthetic data; never put cookies, email, reply text, or secrets in evidence.
- Scope CSRF behavior or add auth regression coverage because the adapter is shared with account auth.
- Archive/synchronize the Lavish HTML under the repository plan location before acceptance.

## Acceptable risk

Copy, assets, choreography, easing, and motion values may remain designer-owned. Temporary staging unavailability is acceptable only when represented by fixtures and not reported as successful live evidence.

## Evidence inspected

- `docs/plans/int-009-frontend-api-integration.md`
- `.lavish/int-009-frontend-api-integration.html`
- `packages/cloud-client/openapi/allies-cloud-0.1.0.json`
- `packages/cloud-client/src/generated/openapi.ts`
- `packages/cloud-client/src/errors.ts`
- `apps/web/lib/cloud/browser-request.ts`
- `origin/web/feat/waitlist-ally-avatar@69f5794`
- Nabu INT-009 frontend handoff and responsive waitlist specification
