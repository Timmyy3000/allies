# Web PWA installation plan

- **Route:** fast
- **Branch:** `web/feat/pwa-install` from `origin/dev`
- **Delivery:** one web PR to `dev`; no merge or deployment in this plan
- **HTML required:** no

## Outcome and scope

Add an online-only installable Allies web app whose manifest launches at `/app`. The existing `/` landing route, its visual treatment, CTA behavior, canonical metadata, and signed-in/onboarding-resume behavior remain unchanged.

At `/app`, restore the current browser session before choosing a screen. Unknown/restoring shows a neutral status, unavailable/failed restoration shows retry, signed-in replaces to `/home` without rendering the welcome screen, and signed-out shows the Figma `26:1338` welcome screen. A pending signed-in onboarding resume must continue through the existing `OnboardingHandoffScreen` instead of being redirected away. “Make your first ally” opens the existing `/onboarding` route at its name step. “Continue with Google” uses the existing CSRF-protected `beginSignIn` operation with a safe `/home` return.

On a settled `/home` roster, offer a gentle, accessible `Install Allies` / `Not now` invitation. Chromium uses the captured `beforeinstallprompt`; its listener synchronously calls `preventDefault()` and stores only the current event. Calling `prompt()` consumes and clears that event exactly once after `userChoice` settles, whether accepted, dismissed, or rejected, so repeated clicks cannot replay a stale prompt. iOS shows concise Share → Add to Home Screen instructions. `Not now` and a dismissed native prompt set one local timestamp with a seven-day cooldown. Hide the invitation in standalone mode, after `appinstalled`, while an Ally conversation or creation overlay is active, and when neither a native prompt nor supported iOS instructions are available. Installed-state claims are limited to those browser signals.

The manifest uses `/app` as `start_url`, `/` as scope so `/home` and onboarding remain in the installed app, `standalone` display, the existing Allies name/colors, and checked-in 192 px, 512 px, maskable 512 px, and Apple touch PNGs exported from the existing Allies SVG. Do not add a service worker, Cache API use, offline response, precache, push, sync, or background behavior; installation relies on the manifest and current browser installability rules. Backend, mobile/store packaging, analytics, and offline support are outside scope. No new runtime dependency is needed.

## Implementation lanes and affected surfaces

1. **Welcome route lane — one owner.** Add `apps/web/app/app/page.tsx`, `app-page-client.tsx`, `welcome.tsx`, `app.module.css`, and `app-page-client.test.tsx`. Keep the route-local Figma artwork isolated: reproduce the verified `CursorMark` path and the existing tracked blue/yellow/green/red Ally vector primitives without importing the large landing module or changing its rendering. Reuse the session, onboarding-resume, handoff, Cloud-operation, and sign-in error contracts already used by `home-page-client.tsx`, `onboarding-page-client.tsx`, and `sign-in-client.tsx`. Add a small shared Google sign-in control only if extraction leaves the existing `/sign-in` DOM and tests unchanged; otherwise keep the same operation contract route-local.

2. **PWA platform lane — one owner.** Add `apps/web/app/manifest.ts`, the raster assets under `apps/web/public/pwa/`, and a compact `apps/web/lib/pwa/pwa-install.tsx` with its focused test. The provider owns synchronous `beforeinstallprompt` cancellation/capture, one-use event clearing after `prompt()`/`userChoice`, standalone/iOS capability detection, `appinstalled`, and the versioned local cooldown key. The invitation consumes that state; it does not infer global installation or promise offline use. Keep browser globals behind effects and injectable helpers so SSR and jsdom are deterministic.

3. **Integration and browser-proof lane — integration owner after both lanes.** Mount the PWA provider once in `apps/web/app/providers.tsx`; replace the root metadata Apple SVG entry with the generated PNG in `apps/web/app/layout.tsx`; render the invitation from the ready branch of `apps/web/app/home/home-workspace.tsx` only when `!selectedAllyId && !createOverlayOpen`; and add the corresponding assertions to `home-workspace.test.tsx`. Extend `apps/web/tests/home-smoke/` with `pwa-install.spec.ts`. In `apps/web/playwright.home-smoke.config.ts`, add a focused desktop-WebKit project whose `testMatch` selects only `pwa-install.spec.ts`, leaving the existing Home smoke matrix unchanged. Narrowly update `.github/workflows/ci.yml` so web validation installs WebKit as well as Chromium and runs that focused project; the integration owner owns both configuration edits.

Lane owners must not edit another lane's files. The integration owner resolves imports and tests the combined state machine after both independent lanes land.

## Acceptance criteria

- `/` still renders the existing public landing and retains its signed-in redirect, logout recovery, and onboarding OAuth resume behavior.
- `/app` never flashes signed-out welcome content during session restoration; signed-in goes to `/home`, signed-out gets the responsive Figma welcome, restoration failure is retryable, and pending onboarding handoff wins over the home redirect.
- Both welcome actions work through existing routes/contracts: onboarding starts at name, while Google auth uses CSRF and returns safely to `/home`; visible redirect and error states prevent duplicate submission and remain accessible.
- The generated manifest has `start_url: "/app"`, `scope: "/"`, `display: "standalone"`, correct theme/background colors, and valid raster/maskable icon entries. The Apple touch icon is PNG.
- The production build exposes no Allies service-worker registration or offline shell; network failure remains ordinary browser failure.
- The Home invitation appears only after workspace readiness and only when install instructions are actionable. The captured Chromium event is synchronously cancelled, is consumed at most once, and is cleared after `userChoice` or prompt failure. Native acceptance, native dismissal, `Not now`, `appinstalled`, standalone display mode, and the seven-day boundary produce the specified visibility transitions. Storage denial fails closed without breaking Home.
- The invitation is keyboard/focus usable, has an announced dialog/instruction title where applicable, respects existing Home layout at phone and desktop widths, and does not cover primary roster controls.

## Focused validation

Add and run these exact tests with the repository-pinned Bun version (the ambient Bun observed during planning was `1.3.14`, while the repository and CI pin `1.2.20`):

```powershell
npx --yes --package bun@1.2.20 bun run test:run -- apps/web/app/app/app-page-client.test.tsx apps/web/lib/pwa/pwa-install.test.tsx apps/web/app/manifest.test.ts apps/web/app/home/home-workspace.test.tsx apps/web/app/sign-in/sign-in-client.test.tsx apps/web/app/page.test.tsx
npx --yes --package bun@1.2.20 bun run lint:web
npx --yes --package bun@1.2.20 bun --filter web typecheck
npx --yes --package bun@1.2.20 bun run build:web
npx --yes --package bun@1.2.20 bun run --cwd apps/web test:home-smoke
```

The new unit tests cover every `/app` session state, restore rejection/retry, no welcome flash, pending resume, both CTAs, manifest values, server-safe PWA initialization, synchronous `preventDefault`, capture before Home settles, accepted/dismissed/rejected `userChoice`, one-use clearing and repeat-click suppression, exact seven-day expiry, denied/corrupt storage, standalone/iOS detection, and listener cleanup. Existing root and sign-in tests are explicit regressions for the preserved `/` and auth behavior.

The production browser spec checks `/`, `/app`, and ready `/home` at the existing desktop and 375 px-class mobile projects; fetches the manifest and every icon; confirms no service worker is registered; and exercises invitation suppression/dismissal through synthetic browser events. The focused desktop-WebKit project verifies the iOS-instruction branch and standalone suppression with controlled navigator/media inputs. This proves browser rendering and state logic only: actual iPhone/iPad Add to Home Screen and OS-installed launch remain a named manual real-device check and must not be claimed from desktop WebKit emulation. In Chromium, use CDP manifest/installability diagnostics when available and report any browser-generated error instead of treating a synthetic prompt alone as installability proof. Visually inspect the Figma welcome at 375×812 plus desktop, the Home invitation, focus order, iOS instructions, and standalone suppression.

Before PR handoff, run the existing CI-equivalent web path: `bun run cloud:check`, `bun run typecheck`, `bun run test:run`, `bun run lint`, `bun run build:web`, `bun run --cwd apps/web test:home-smoke`, and the chat-frame Chromium command selected by `.github/workflows/ci.yml`. Do not claim these passed until executed against the integrated branch.

## Risks, rollback, and decisions

- Browser install APIs differ and `beforeinstallprompt` can fire before Home settles. The app-level listener must cancel and capture it synchronously; prompt consumption clears the stored event on every outcome, and tests cover early dispatch, repeated clicks, and listener cleanup.
- Browser installability requirements can change. Treat Chromium CDP diagnostics and real browser install UI as the acceptance evidence; do not add a service worker merely to satisfy obsolete heuristics.
- Session/auth duplication can drift. Reuse the current session and Cloud-operation contracts, keep return paths validated, and retain focused `/`, sign-in, onboarding-resume, and `/app` tests.
- Figma artwork reuse could change `/` or bloat the `/app` bundle. Keep route-local pure vectors and avoid importing or modifying the large landing module; visual proof compares only the new route to frame `26:1338`.
- Maskable safe-area cropping needs real browser inspection. Keep a dedicated padded maskable export rather than labeling the ordinary icon maskable.

No product decision remains open. Exact artwork extraction mechanics and icon-export tooling are implementation details, provided they add no runtime dependency, preserve `/`, and produce the checked-in assets and validation above. Rollback is additive: remove `/app`, the PWA provider/invitation, manifest, and generated icons, then restore the prior Apple metadata entry; `/` and backend behavior remain available throughout.

## Evidence basis

Planning inspected `AGENTS.md`, `ENGINEERING_STYLE.md`, `apps/web/AGENTS.md`, `.agent/pwa-install/episode-state.md`, `.agent/kickoff.yaml`, the `plan-it` worker contract, root/web READMEs and package scripts, `.github/workflows/ci.yml`, Vitest and Playwright configuration, installed Next.js 16.2.12 manifest/app-icon documentation, current root/session/sign-in/onboarding/Home code and tests, existing SVG assets, Nabu `projects/allies/index.md`, and `projects/allies/engineering/codebase-structure.md`. Nabu assigns browser/PWA behavior to Allies Interface; the accepted 2026-09-08 Web installation entry in `projects/allies/engineering/decisions/decision-log.md` (revision `b15c83cd…`) confirms the corrected no-service-worker, online-only boundary. The older scaffold inventory is not treated as current code evidence. Design evidence is Aphrodite/Figma frame `26:1338` plus the matching tracked Ally/cursor vectors identified in the current onboarding module.
