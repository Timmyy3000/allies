# AUTH-001 Adversarial Review

> Alignment update — 2026-08-11: the accepted Nabu PRD names Sign in with
> ChatGPT, but the owner's later accessibility rule is authoritative. ChatGPT
> is excluded before code unless an ordinary consumer account can authenticate
> without API, developer/partner, paid-business/workspace, or invite
> entitlements across the launch audience. If included, the adapter also
> remains fail-closed until the project receives the official client contract.

## Verdict

Needs revision.

## Findings And Dispositions

| Severity | Finding | Disposition |
| --- | --- | --- |
| Major | Callback state was not bound to the initiating browser/session, leaving login-CSRF and provider-mix-up risk. | Accepted. Add an HttpOnly, short-lived flow cookie whose digest is persisted and checked in constant time. Bind provider, redirect, purpose, and authenticated session for linking. |
| Major | Authenticated identity linking was required but absent from the API and flow contracts. | Accepted. Add a typed `link` start flow and purpose-aware callback that preserves the initiating user/session and rejects subject collisions. |
| Major | Family revocation did not explicitly invalidate already-issued access JWTs. | Accepted. Split `SessionFamily` from one-time `RefreshToken`; cookie authentication checks the `sid` family state on every request. Logout accepts either valid access or refresh context and is idempotent. |
| Major | Exact uniqueness constraints and the first custom-user migration graph were underspecified. | Accepted. Name all durable constraints and require `AUTH_USER_MODEL` before the first persistent migration; `workspaces/0001` depends on `auths/0001`. |
| Major | Cookie, CSRF, CORS, throttling, proxy, and cache-failure behavior lacked a testable configuration matrix. | Accepted. Add same-site production and local-development matrices, exact cookie scopes, CSRF bootstrap/header behavior, rate keys/limits, and fail-closed production validation. Cross-site deployment remains an owner decision requiring an explicit alternate matrix. |
| Major | Operator revocation, audit taxonomy, cleanup scheduling, retry, and visibility were not executable. | Accepted. Add bounded management commands, structured redacted events, metrics, external scheduling ownership, continuation, and failure behavior. |
| Major | SQLite could not prove row-lock correctness and the planned coverage/PostgreSQL dependencies were missing. | Accepted. Add deliberate test dependencies and a PostgreSQL CI lane for migrations and races; retain SQLite compatibility tests. |
| Major | The artifact lacked typed service/transport contracts and used a file layout that conflicted with the repository registrar convention. | Accepted. Add the executable contract plan and use `api/controllers.py`, `api/register.py`, and `config/api.py`. |
| Major | Avatar decode limits, I/O bounds, race transitions, and signed-read expiry behavior were incomplete. | Accepted. Add exact byte/pixel/dimension/time limits, verify outside the transaction, lock before state transition, concurrency tests, and disclose that issued reads remain valid until their five-minute expiry. |
| Minor | The claim that R2 does not support `Content-MD5` was inaccurate. | Accepted. Remove the claim. Keep bounded server-side SHA-256 and image decoding as the publication authority; optionally sign `Content-MD5` only as an early transport check after implementation verification. |
| Question | Disabled ChatGPT is safe but cannot satisfy the earlier release criterion that explicitly required ChatGPT sign-in. | Superseded by the owner's ordinary-user accessibility rule. Prove consumer eligibility first; exclude ChatGPT and revise Nabu if it fails, or require the full official contract if it passes. |

## Strengths Preserved

- Identity remains keyed by verified `(provider, subject)`, never email.
- Workspace authority stays out of JWTs and is resolved from live Cloud records.
- Provider handling stays behind a narrow port and never scrapes consumer sessions.
- Refresh rotation, private object storage, byte verification, query guards, and additive rollback remain explicit.

## Review Metadata

- Reviewer: independent Codex worker
- Model: `gpt-5.6-terra`
- Reasoning effort: `xhigh`
- Date: 2026-08-09
