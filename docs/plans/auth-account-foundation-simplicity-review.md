# AUTH-001 Simplicity Review

> Alignment update — 2026-08-11: the recommendation against a speculative
> ChatGPT placeholder remains in force. The adapter earns a concrete module
> only if ordinary consumer eligibility passes and OpenAI then supplies the
> official project contract; otherwise ChatGPT is removed from AUTH-001.

## Verdict

Simplification recommended.

## Findings And Dispositions

| Classification | Finding | Disposition |
| --- | --- | --- |
| Simplify | A placeholder `providers/chatgpt.py` adds an unimplementable provider footprint. | Accepted. No ChatGPT module or provider-specific settings are created. The closed enabled-provider catalog excludes and rejects ChatGPT until a complete official contract is supplied. |
| Simplify | Refresh-token `sequence` and parent lineage are not required for one-time rotation/reuse detection. | Accepted. Retain unique keyed digest, family, used/expiry state, conditional one-unused-token constraint, digest history, and row locks; remove lineage fields. |
| Simplify | A JWT key ring and `kid` rollover are speculative without an approved rotation requirement. | Accepted. Use one dedicated environment-provided HS256 key, separate from Django's secret. Planned rotation invalidates at most the ten-minute access window while family state remains authoritative. |
| Simplify | A dedicated profile-update throttle has no demonstrated provider/session/storage abuse case. | Accepted. Retain authentication, CSRF/origin, body-size, and display-name validation; remove the special throttle setting/test. |

## Protected Complexity

- Browser-bound, one-time, purpose-aware OIDC flows remain necessary for login-CSRF, replay, mix-up, and authenticated linking.
- Session family authority, per-request active-family reads, digest history, and row-locked rotation remain necessary for immediate revocation and reuse containment.
- Explicit cookie/CSRF/CORS/proxy/cache behavior remains necessary for the cookie-authenticated boundary.
- Private R2 storage, bounded byte/image verification, locked publication, and cleanup remain necessary for avatar safety.
- SQLite compatibility plus PostgreSQL migration/concurrency CI and live Workspace authorization remain necessary for data and tenant isolation.

## Residual Risk

- ChatGPT remains outside implementation unless ordinary consumer eligibility
  passes; an included provider then remains blocked until a complete official
  project-specific identity-provider contract is available.
- Production cache, origin topology, R2 policy, and secret ownership remain owner decisions before Phase 0 can exit.

## Review Metadata

- Reviewer: fresh independent Codex worker
- Model: `gpt-5.6-terra`
- Reasoning effort: `xhigh`
- Date: 2026-08-09
