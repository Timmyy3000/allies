# Simplicity Review

## Verdict

Simplification recommended

## Findings

| Classification | Plan area | Evidence | Recommendation | Preserved outcome |
| --- | --- | --- | --- | --- |
| Simplify | Provider-level automatic session restoration | The plan already requires auth routes to restore explicitly and prohibits unsolicited `/me` requests on the public route (`docs/plans/int-007-web-google-auth-account.md:50`, `:218-219`, `:238-240`). The existing `restoreOnMount` mode is used only by `AppProviders` and duplicates explicit restoration through initialization branches, an effect, and race handling (`apps/web/app/providers.tsx:26`; `apps/web/lib/session/session-context.tsx:20-69`). | Remove `restoreOnMount` and its mount effect. Initialize context as `unknown`; let `/auth/return` and `/account` invoke the existing explicit `restore()` once, which transitions through `restoring`. Retain targeted cache writes/removal, logout generation handling, and the regression proving the public landing route sends no `/me` request. | Refresh/revisit restores valid sessions without a signed-out flash; public pages remain request-free; logout still wins races; TanStack Query remains the sole account DTO cache. |
| Remove or Defer | Local avatar preview object URL | The accepted brief requires the complete avatar lifecycle, truthful completion, input preservation, and prior-avatar retention, but not a pre-upload image preview (`docs/plans/int-007-web-google-auth-account-brief.md:31-40`, `:48-50`). The plan adds a preview object URL and replacement/unmount cleanup solely as proposed state (`docs/plans/int-007-web-google-auth-account.md:206`, `:221`, `:264`, `:337`). | Remove the preview object URL from `AvatarActionState` and its cleanup work. Keep the selected `File`, show its safe filename/status if useful, and continue displaying the prior server-confirmed avatar until Cloud completion succeeds. Add a preview later only with a demonstrated product requirement. | File retry remains possible, the existing avatar remains truthful during upload, and no UI claims completion before Cloud verification. |

## Protected Complexity

- Keep the provider-lifetime in-memory CSRF owner, validated response-header capture, shared bootstrap/refresh gates, and operation-wide two-invocation budget. These directly preserve the accepted blocker and replay findings (`docs/plans/int-007-web-google-auth-account.md:62-71`, `:82-93`).
- Keep the bounded direct-upload timeout, caller-cancellation distinction, resource cleanup, and race tests. The raw object-store PUT bypasses the existing controlled Cloud transport and otherwise may remain pending indefinitely (`docs/plans/int-007-web-google-auth-account.md:74`, `:104`, `:264`).
- Keep proactive avatar-read renewal through TanStack Query, including rescheduling, cancellation, failure stop, and manual recovery. `staleTime` alone does not refresh a mounted signed URL (`docs/plans/int-007-web-google-auth-account.md:67`, `:106`, `:265`).
- Keep the real-browser exact-header/CORS probe and external release blocker. The verified `Content-Length` mismatch cannot be safely hidden or normalized by Interface (`docs/plans/int-007-web-google-auth-account.md:47-49`, `:191`, `:263`, `:276`).

## Plan Feedback For Revision

- Replace the `restoreOnMount` provider mode with one explicit route-owned restoration path and remove its duplicated initialization, effect, configuration, and race-test branches.
- Delete local avatar preview URL state and cleanup from the contract, phases, tests, and state-management notes; retain selected-file retry and the previous confirmed avatar.

## Residual Risk

- Every protected auth entry route must invoke explicit restoration exactly once and render `unknown/restoring` without briefly presenting a signed-out action.
- Removing the local preview slightly reduces pre-upload visual feedback, but filename, pending state, and the existing confirmed avatar satisfy the current accepted scope.

## Confidence

High - the recommendations trace the revised plan against the accepted INT-007 contract, adversarial dispositions, repository policy, and the current session/query implementation without weakening any required security, data-integrity, accessibility, or release safeguard.
