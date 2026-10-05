# Alpha PWA and onboarding handoff todos

- [x] AT-032: verify the deployed `/app` route, PWA manifest start URL/scope, and logout navigation contract.
- [x] AT-032: route confirmed PWA logout to `/app` without rendering authenticated content after session loss.
- [x] AT-032: preserve the unconfirmed-logout signal on the `/app` destination and add focused regression coverage.
- [x] AT-033: make `/app` consume the app-wide selected light/dark theme rather than a local default.
- [x] AT-033: add focused light/dark theme parity regression coverage for `/app`.
- [x] AT-039: trace the signed-in creation, first-message, user-response, and final-chat state transitions.
- [x] AT-039: keep the handoff surface mounted through the first submitted response until the final conversation is ready, with no roster/list flash.
- [x] AT-039: preserve draft text, queued turns, Ally identity, and send idempotency across the transition.
- [x] AT-039: add focused regression coverage for the seamless signed-in handoff.
- [x] Validate web lint, web build, typecheck, focused account tests, and focused home/onboarding smoke tests.
- [x] Deliver a focused PR to `dev`, verify its head/base/check state, and start the required dedicated Luna monitor without merging.

Out of scope: AT-031 pending live mobile evidence; PR 1 conversation styling; PR 3 Luna/approval backend work; inline file previews.
