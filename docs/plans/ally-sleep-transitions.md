# Ally Sleep Transitions Plan

> **Route:** Fast. The change is a bounded presentation feature, but the repository requires a matching HTML plan because motion state and cross-platform playback benefit from visual review.

**Goal:** Deliver the approved thinking, sleeping, waking, and falling-asleep artwork to the active web PR and mobile worktree with one deterministic, offline playback contract.

**Working branches:** Update web PR 22 on `web/feat/chat-frames` and the existing mobile worktree on `mobile/dev/screen-expansion`, both against `dev`. Preserve the mobile branch's existing commit and do not merge or deploy as part of this work.

**Source decision:** The approved `considering_<shape>.svg` files become the production `thinking` artwork. The approved `idle`, `sleeping`, `waking`, and `falling-asleep` SVGs retain their authored CSS timing and fixed `470 470` view box. The local source set contains 20 SVGs, no scripts, and no external asset references.

## Feature Overview

- **Problem:** Web currently swaps independently animated SVG image documents at loop boundaries and treats sleep as a desaturated roster style. Mobile renders idle/thinking SVGs through `expo-image`, has no controlled animation clock, and has no ten-minute sleep treatment. Neither client can preserve the approved sleep/wake continuity.
- **Target users:** People viewing an Ally in the web Home roster or conversation, the mobile Ally roster or selected conversation, and existing mobile preview/onboarding surfaces.
- **Success outcome:** All four Ally shapes use the same local artwork and state sequencing on web and mobile; sleep remains a per-conversation presentation state; reduced motion is static; hidden or backgrounded renderers stop advancing.
- **Canonical evidence:** Repository instructions and plan template; `ENGINEERING_STYLE.md`; web and mobile app instructions; the Nabu Ally avatar specification and DSN-003; the approved local SVG set and motion-room prototype; current web Home/avatar code; current mobile conversation/avatar code; Expo SDK 57 WebView documentation.

### Current and target behavior

| Surface | Current behavior | Target behavior |
| --- | --- | --- |
| Shared artwork | Idle/thinking assets are duplicated between web public files and mobile assets. | `packages/ally-motion` checks in the 20 approved SVGs and generates one bundled document payload consumed by both clients. |
| Web renderer | `AllyAvatar` uses external `<img>` documents and a React timeout to defer idle/thinking switches. | A sandboxed `srcDoc` iframe runs the shared player. Only `allow-scripts` is granted; CSP blocks all asset/network loading. |
| Web sleep | A bound Ally becomes desaturated with a neutral dot ten minutes after its latest message or recent draft/message activity. | Keep the same predicate and dot treatment, but request public state `sleeping` in both the roster and selected conversation header. |
| Mobile renderer | `OnboardingAllyPreview` uses `expo-image` for idle/thinking and cannot own CSS animation time. | A local `react-native-webview` document runs the same player; the package version is installed through Expo and is supported by Expo Go. |
| Mobile sleep | No sleep state or clock. | A bound Ally sleeps in the roster and selected conversation ten minutes after its latest conversation message or most recent meaningful draft activity, independent of Machine state; other reusable preview callers keep their requested idle/thinking behavior. |

## Scope

### In Scope

- Publish `idle`, `thinking`, and `sleeping` as caller states for four canonical shapes.
- Keep `waking` and `falling-asleep` private transition phases chosen by the player.
- Bundle approved artwork and player code into a self-contained HTML document with no runtime asset request or remote script.
- Replace web external-image playback with a sandboxed iframe adapter and add `sleeping` to Home roster and conversation callers.
- Replace mobile roster, selected-conversation, and reusable preview artwork with one local WebView adapter and add equivalent inactivity ownership to the roster and selected conversation.
- Pause playback when a web avatar is offscreen or its document is hidden, and when a mobile avatar is outside a virtualized list's viewability window, its route is unfocused, or the app is backgrounded.
- Add focused state-machine, adapter, inactivity, reduced-motion, and pause/resume tests.

### Out of Scope

- Cloud, Foundry, Hermes, Fly, Machine power, leases, API schemas, persistence, analytics, or product copy changes.
- Public `waking` or `falling-asleep` props, animation speed controls, a user sleep setting, working/error/retry/approval visuals, or new artwork.
- Rebuilding onboarding entrance motion or converting the SVGs to GIF, Lottie, canvas, or native path animation.
- Merging or deploying either branch. Updating web PR 22 is part of this plan.

### Dependencies and Assumptions

- `react-native-webview` is added with `npx expo install react-native-webview`; Expo SDK 57 recommends `13.16.1` and includes it in Expo Go.
- The generated payload is about 0.78 MB before bundler compression. This is the accepted cost of offline, identical artwork; build/export output must make any material regression visible.
- The generator converts approved CSS `d` keyframes to SVG-native SMIL because WebKit does not interpolate CSS path data. The player pauses and seeks SMIL alongside WAAPI. Chromium/WebKit geometry tests prove the converted eye motion; native WebView SMIL/WAAPI behavior remains a device-verification item.
- The web branch is the first integration point for the shared package. Carry the exact package files to the mobile branch before adding the native adapter; do not independently edit two runtime copies.
- The Nabu avatar note still describes sleep as desaturation with no asset and lists only idle/thinking as public states. The user's newer accepted direction supersedes that text for this delivery; update the canonical note after implementation is validated.

## Contracts and State Ownership

### Shared package contracts

| Location | Symbol | Contract |
| --- | --- | --- |
| `packages/ally-motion/src/index.ts` | `AllyMotionState` | Public state union: `idle | thinking | sleeping`. Unknown input resolves to `idle`. |
| `packages/ally-motion/src/index.ts` | `AllyMotionShape` | `boxy | ghosty | rocky | rolly`; callers continue to validate appearance before rendering. |
| `packages/ally-motion/src/index.ts` | `AllyPlayback` | `{ state, reduced, paused? }`; re-requesting the active state does not restart its loop. |
| `packages/ally-motion/src/index.ts` | `createAllyDocument(shape, playback): string` | Returns one self-contained HTML document containing only approved local SVG, inline player code, an inline-style allowance, and CSP `default-src 'none'`. Escapes `<` in serialized configuration. |
| `packages/ally-motion/src/index.ts` | `allyPlaybackScript(playback): string` | Produces the native host-to-WebView update call and a final truthy expression required by WebView injection. |
| `packages/ally-motion/scripts/generate.mjs` | generation step | Reads exactly five named assets for each of four shapes plus the player, validates source, converts approved CSS eye-path keyframes to SVG-native SMIL, and regenerates the checked-in typed payload. Missing, extra-state, scripted, externally referenced, or wrong-view-box input fails validation. |
| `apps/web/scripts/export-ally-artwork.mjs` | static export | Uses the same normalized source to emit public static/reduced files. Mobile receives the generated package and reduced assets byte-for-byte rather than maintaining separate art. |

`packages/ally-motion/src/player.js` is the only transition owner. Host components never ask for or persist private phases. Its durations are `idle 4000 ms`, `thinking 4502.083 ms`, `sleeping 9600 ms`, `waking 1400 ms`, `falling-asleep 1400 ms`, with a `420 ms` wake-entry pose bridge. A sleep-to-awake request takes about `1820 ms` from sampled sleep pose through the end of the authored waking beat. The player pauses and seeks SVG SMIL and WAAPI timelines from the same elapsed clock.

### Transition contract

<table>
<thead><tr><th>Current condition</th><th>Latest request</th><th>Required sequence</th></tr></thead>
<tbody>
<tr><td>Idle or thinking loop</td><td>Other awake state</td><td>Finish the current loop at its neutral end frame, then start the latest requested awake loop.</td></tr>
<tr><td>Idle or thinking loop</td><td>Sleeping</td><td>Finish the current awake loop, play falling-asleep for 1.4 seconds, then loop sleeping.</td></tr>
<tr><td>Sleeping loop</td><td>Idle or thinking</td><td>Immediately sample the current sleep pose; bridge head, eyes, eyelids, and departing Zs into the waking start for about 420 ms; then play the complete 1.4-second authored waking phase and enter the latest awake request, about 1.82 seconds total.</td></tr>
<tr><td>Waking or falling asleep</td><td>Any public state</td><td>Latest request wins after the current private phase reaches a coherent endpoint. If direction reverses, traverse the opposite private phase rather than cutting between unrelated poses.</td></tr>
<tr><td>Any state with reduced motion</td><td>Any public state</td><td>Switch immediately to a representative static pose: idle/sleeping at their stable start and thinking at the approved midpoint. Schedule no RAF and play no bridge.</td></tr>
<tr><td>Paused, hidden, offscreen, or backgrounded</td><td>Any state</td><td>Retain requested and elapsed state but schedule no RAF. Resume with a zero first-frame delta so background time is not replayed.</td></tr>
</tbody>
</table>

### Client ownership and failure behavior

- **Shared player:** Owns elapsed time, active/private phase, latest requested public state, pose sampling, WAAPI handles, and coherent transition endpoints. It keeps no product data and emits no network request.
- **Web adapter:** `AllyArtwork` creates `srcDoc` once per shape, sends state/reduced/pause updates through `postMessage`, and observes intersection. The iframe has an opaque sandbox origin and accepts messages only from its parent window. The existing outer `AllyAvatar` continues to own shape/color validation, shell geometry, size, labels, and reduced-motion preference.
- **Mobile adapter:** `OnboardingAllyPreview` keeps the same public sizing, color-shell, and accessibility contract while a native `AllyArtwork` wraps local HTML in `WebView`. It sends updates only after ready, rejects navigation away from the local document, disables scrolling and interaction, and derives pause from list viewability, conversation scroll position, route focus, and `AppState`. Mobile lists mount WebViews only inside their virtualization window, and the inline thinking indicator pauses when the reader scrolls away from the latest message.
- **Inactivity:** Web preserves `isAllySleeping(ally, latestMessage, now, recentActivityAt)` and its ten-minute/30-second-clock semantics. Mobile adds the same pure predicate beside conversation-state helpers. Only `provisioningState === 'bound'` with a finite latest-message timestamp may sleep. Meaningful non-whitespace draft edits update `recentActivityAt`; whitespace-only changes do not. A new accepted message supplies a fresh persisted timestamp. No sleep state exists when there is no message.
- **Failure:** Invalid appearance keeps the existing visible `?` placeholder. Reduced motion bypasses native WebView playback and renders an exported static SVG `Image` for the same shape and requested state. A terminated native content process reloads once, then uses that same static image if it fails again. Any player/WebView failure leaves the colored shell and nearby Ally name usable and cannot block conversation controls. Unknown state input falls back to idle; there is no cross-shape fallback.
- **Accessibility:** The outer component remains decorative by default or exposes the caller's existing accessible label. The iframe/WebView is not focusable or separately announced, state changes are not live-announced, and reduced motion stops continuous and transition animation.

## Phases

### Phase 1 - Establish and test the shared runtime

- Add `packages/ally-motion` with the 20 approved assets, CSS-path-to-SMIL normalizer, generator, generated payload, public document helpers, and one player that seeks WAAPI and SVG SMIL together.
- Rename the approved `considering_<shape>.svg` files to `thinking_<shape>.svg` in the package; do not keep the superseded production thinking artwork.
- Add package tests that execute the bundled player under fake RAF/WAAPI time and assert neutral awake switches, sleep entry, prompt wake with blend, rapid reversal/latest-wins behavior, immediate reduced state, and frozen paused/hidden time.
- Add document-generation tests for CSP, configuration escaping, all 20 assets, no external references, and deterministic regeneration.
- **Exit:** Shared tests pass; regenerated output is clean; package contents are byte-identical in both worktrees.

### Phase 2 - Integrate web Home and remove the old playback owner

- Add the workspace dependency to `apps/web` and create `apps/web/components/ally-artwork.tsx` as the sandboxed iframe adapter.
- Refactor `apps/web/components/ally-avatar.tsx` so the shared player owns loop timing. Preserve color, shell sizing, appearance validation, explicit motion modes, and existing callers. Remove the obsolete React timeout/preload owner and unused public-file asset lookup once the debug playground reads the shared contract.
- Extend `AllyFrameAvatar` and `ConversationFrame` state types to include `sleeping`. Drive both the roster avatar and selected conversation header from the existing inactivity predicate, with thinking/getting-ready taking precedence.
- Keep the existing neutral presence dot and desaturation treatment unless visual inspection shows it obscures the approved sleeping artwork; state meaning must not depend on color alone.
- **Exit:** Existing ten-minute and wake-on-draft behavior remains covered, the current chat-frame tests stay green, and browser inspection shows no SVG or script network request.

### Phase 3 - Integrate mobile roster, conversation sleep, and lifecycle pause

- Install `react-native-webview` with Expo's version resolver and add the shared workspace dependency.
- Replace the artwork layer inside `OnboardingAllyPreview` with a local WebView adapter while preserving shell animation, sizes, appearance mapping, and labels across the Ally roster, selected conversation, mock conversation, and onboarding/preview callers.
- Add the pure ten-minute predicate under `apps/mobile/src/features/allies`. In `apps/mobile/src/app/allies/index.tsx`, derive roster sleep from each bound Ally's latest preview message. In `apps/mobile/src/app/allies/[allyId]/index.tsx`, derive the latest message from the merged ascending conversation, update recent activity on meaningful draft edits, let active queued/running work request thinking, and otherwise request sleeping or idle.
- Pass list viewability, conversation scroll position, navigation focus, and `AppState` to the adapter so offscreen or backgrounded native playback pauses and resumes without elapsed-time jumps; pause the inline thinking indicator when the reader leaves the latest messages and preserve list virtualization rather than eagerly mounting a WebView for every Ally.
- Use generated same-shape/same-state static SVGs for reduced motion and after one failed native content-process reload. Keep exporter output and the package byte-identical between worktrees.
- **Exit:** Focused tests cover inactivity boundaries and draft resets; Expo Go renders the local document without navigation/network access; onboarding callers still default to idle/thinking.

### Phase 4 - Cross-platform proof and knowledge reconciliation

- Exercise all shapes through idle, thinking, sleep entry, sleeping, prompt wake, rapid reversal, reduced motion, offscreen/background, and resume.
- Verify actual iOS and Android WebViews when devices are available because desktop browsers cannot prove native SVG path/WAAPI behavior. Record unsupported CSS `d` interpolation as an explicit limitation; do not substitute an eye fade or silently alter the approved artwork. Device proof may remain a named handoff item when no physical/simulator device is available.
- Compare package-generated output and public states across branches, measure web build/mobile export impact, and inspect diffs for duplicated runtime or legacy asset-network paths.
- Update the canonical Nabu Ally avatar note from idle/thinking plus desaturation to the accepted three-public-state/private-transition contract after validation.
- **Exit:** Automated checks pass, device limitations are honestly recorded, Nabu matches accepted implementation, and neither branch is merged or deployed.

## Acceptance Criteria

1. Each canonical shape renders approved idle, refined thinking, and sleeping loops from local bundled artwork on web and mobile.
2. Idle/thinking changes wait for the current neutral loop boundary without a restart or stutter.
3. Sleep entry finishes the awake loop, plays falling-asleep for 1.4 seconds, and then loops sleeping.
4. Waking starts promptly from the sampled sleep pose, completes its approximately 420 ms bridge followed by the full 1.4-second authored waking phase, and enters the latest requested awake state after about 1.82 seconds total.
5. Rapid requests are bounded to one latest public request and always reach a coherent endpoint before reversing.
6. Reduced motion renders a stable requested pose immediately and schedules no continuous animation or transition.
7. Web sleep still requires a bound Ally, a latest conversation message, and ten minutes without newer message or meaningful draft/message activity; Machine state remains irrelevant.
8. Mobile implements the same predicate and wakes immediately on meaningful draft activity or active conversation work.
9. Web iframe sandbox/CSP and mobile local WebView make no asset or script network request and cannot navigate to remote content.
10. Hidden/offscreen web avatars and offscreen, scrolled-away, unfocused, or backgrounded mobile avatars stop advancing and resume without catching up elapsed wall time; inline thinking pauses away from the latest message and virtualized mobile lists do not eagerly mount an unbounded set of WebViews.
11. Reduced-motion native callers and a WebView that fails again after one content-process reload render the exported static SVG for the same requested state and shape.
12. Existing appearance validation, shell color/size, decorative-label behavior, onboarding callers, chat controls, and conversation behavior remain intact; a renderer failure cannot block or replace conversation controls.

## Validation Plan

### Automated checks

Run from each affected worktree as applicable:

```bash
bun run --cwd packages/ally-motion generate
git diff --exit-code -- packages/ally-motion/src/generated.ts
bun run test:run -- packages/ally-motion/src/player.test.ts
bun --filter web test:ally-motion
bun apps/web/scripts/export-ally-artwork.mjs
```

Web branch:

```bash
bun run test:run -- apps/web/components/ally-avatar.test.ts apps/web/app/home/home-workspace.test.tsx apps/web/app/home/conversation-frame.test.tsx
bun run lint:web
bun --filter web typecheck
bun run build:web
```

Mobile branch:

```bash
bun run test:run -- apps/mobile/src/features/allies/ally-sleep.test.ts packages/ally-motion/src/player.test.ts
bun run lint:mobile
bun --filter mobile typecheck
bun run bundle:mobile
```

From `apps/mobile`, also run `bunx expo export --platform android --output-dir dist/android` so the Android bundle resolves the workspace package and WebView dependency; `bun run bundle:mobile` covers the iOS export.

### Behavioral proof

- Use fake time to assert states immediately before and after `4000`, `4502.083`, `1400`, `420`, `1820`, and `9600` ms boundaries, including SMIL and WAAPI seeking from one clock.
- In the web animation playground, inspect all four shapes and request `idle -> thinking -> sleeping -> thinking`, then reverse during waking and falling asleep. Confirm iframe `data-state`, no focus target, and zero runtime requests.
- With reduced motion enabled, verify all three public states are distinct static poses and that color-shell updates stay immediate.
- Scroll web avatars offscreen and hide/show the tab; scroll a mobile list beyond its viewability window, move the selected conversation away from its latest thinking indicator, background/foreground the app, and navigate away/back. Confirm WebView mounts remain bounded and time freezes rather than jumps.
- Force one native content-process termination and then a repeat failure; confirm one reload followed by the same-shape/same-state static SVG. Confirm reduced motion never mounts a WebView.
- In Expo Go on iOS and Android when devices are available, inspect SMIL eye geometry and head/Z motion at small header and larger onboarding sizes. Confirm no clipping, white flash, scroll, touch capture, or remote navigation.

## Risks, Rollback, and Open Decisions

| Risk | Mitigation | Rollback or fallback |
| --- | --- | --- |
| Native WebViews differ on WAAPI or SVG SMIL timing. | Keep passing Chromium/WebKit geometry coverage and device-test both native platforms when available. | Report the native limitation and hold that platform's animation treatment for follow-up; do not replace approved eye motion with opacity fading. |
| The bundled generated module adds about 0.78 MB before compression. | Record web build and both mobile export sizes; generate once and avoid per-client copies. | Restore per-state static assets only if measured delivery cost is unacceptable, retaining the public state contract. |
| Many roster iframes/WebViews could consume resources. | Web uses intersection/document visibility; mobile preserves list virtualization, bounds WebView mounts to the viewability window, and pauses on viewability/focus/AppState. | Render static requested poses for non-primary avatars while keeping full playback in the selected conversation. |
| Host and player both attempt to own transitions. | Remove the web timeout/preload path and keep private phases out of component props. | Revert adapters and shared package together; do not leave two clocks active. |
| Web PR and mobile branch diverge in the shared package. | Land or carry one exact package change before platform adapters; regeneration must be clean in both worktrees. | Reapply the accepted package directory byte-for-byte, then rerun both platform checks. |
| Canonical Nabu text remains stale. | Update the existing avatar note only after implementation/device proof, preserving decision status and revision. | Do not create a competing note; record the mismatch until the canonical update is verified. |

No unresolved product decision blocks implementation. Exact native SMIL/WAAPI behavior is a validation result and may remain an explicit device-proof handoff item; no eye-fade fallback is approved.

## Evidence Index

- `AGENTS.md`, `ENGINEERING_STYLE.md`, `apps/web/AGENTS.md`, `apps/mobile/AGENTS.md`, and `docs/templates/PLAN_TEMPLATE.md`.
- `apps/web/components/ally-avatar.tsx` and tests; `apps/web/app/home/home-workspace.tsx` and tests; `apps/web/app/home/conversation-frame.tsx`; `apps/web/app/home/conversation-frame-primitives.tsx`.
- `apps/mobile/src/features/onboarding/onboarding-ally-preview.tsx`; `apps/mobile/src/app/allies/index.tsx`; `apps/mobile/src/app/allies/[allyId]/index.tsx`; `apps/mobile/src/features/allies/ally-sleep.ts` and its test; mobile artwork adapters and package scripts.
- `packages/ally-motion/src/player.js`, its focused test, generation/SMIL normalization scripts, `apps/web/scripts/export-ally-artwork.mjs`, and the Chromium/WebKit player geometry suite.
- Approved local motion source: four each of refined thinking (`considering`), idle, sleeping, waking, and falling-asleep SVGs plus the motion-room state prototype.
- Nabu `projects/allies/index.md`, `projects/allies/engineering/specs/waitlist/ally-avatar-component.md`, and `projects/allies/delivery/tickets/design/DSN-003.md`.
- Expo SDK 57 `react-native-webview` documentation, inspected 5 September 2026: supported in Expo Go, recommended `13.16.1`, install with Expo's resolver.


## Approved follow-up

Follow-up approved on 5 September: coloured web avatars use the full SVG canvas at 86% of the shell, matching mobile. Defer player mounting until initial conversation state is resolved; already-asleep Allies start in the sleep loop. Enlarge sleep Zs and move their travel inward. Give each initial idle/sleep loop an independent random phase while preserving authored transition endpoints. Validate loading-to-sleep initialization, unchanged player identity on later requests, mobile sizing parity, phase offsets, and existing browser geometry tests.
