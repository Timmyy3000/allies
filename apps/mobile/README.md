# Allies mobile

Expo / React Native client for Allies. The current mobile implementation includes
the local onboarding UI slice and the INT-008 native auth/account boundary on branch
`mobile/int-008-google-auth-account`.

This file is an agent handoff and a living mirror of the mobile implementation. The
full implementation record is maintained in Nabu at:

`projects/allies/engineering/specs/interface/mobile-onboarding-implementation.md`

When this README and Nabu disagree, do not silently choose one. Check the code and
tests for the current behavior, record the reconciliation in the Nabu handoff, then
update this README in the same change.

## First intake for a mobile task

Before changing code, an agent must read:

1. The repository root `AGENTS.md`.
2. [`apps/mobile/AGENTS.md`](./AGENTS.md), including the required Expo SDK 57
   documentation rule.
3. This README.
4. Nabu `projects/allies/index.md`.
5. Nabu `projects/allies/engineering/guides/interface-development.md`.
6. The relevant product/specification notes for the flow being changed. For this
   onboarding slice, start with:
   - `projects/allies/product/creating-your-first-ally.md`
   - `projects/allies/engineering/specs/waitlist/INT-009-frontend-handoff.md`
   - `projects/allies/engineering/specs/waitlist/INT-009-responsive-waitlist-preview.md`
   - `projects/allies/engineering/specs/waitlist/proposed-copy-and-experience.md`
   - `projects/allies/engineering/specs/interface/mobile-onboarding-implementation.md`
   - `projects/allies/engineering/specs/interface/INT-008-mobile-google-auth-and-account.md`
   - `projects/allies/engineering/specs/interface/AUTH-002-cloud-native-session-contract.md`

Use Nabu's native MCP tools first. Search before assuming that a product decision,
asset, contract, or implementation note does not already exist. Never expose Nabu
credentials, cookies, bearer tokens, invite URLs, or private data in source,
terminal output, commits, or agent responses.

## Nabu and README synchronization contract

Nabu is the shared source of truth for Allies product, architecture, specifications,
decisions, and cross-agent handoffs. This README is the local, immediately visible
mobile entry point. It should remain short enough to use during intake, but it must
describe the current mobile boundary and link to the detailed Nabu record.

During local exploration, the README and Nabu do not need to change for every small
edit. At each meaningful commit/release boundary:

1. Finish the scoped code change and run its validation.
2. Update this README with the corresponding mobile-facing behavior, paths, commands,
   and status, then commit the README together with the code.
3. Push the commit.
4. Read the current Nabu handoff, make a revision-aware update containing the commit
   SHA, behavior, validation, and remaining boundary or risk, then re-read it to
   verify the write.
5. If the commit is published through EAS Update, record the channel and update
   message/group identifier in Nabu. The README should describe the behavior, not
   become a noisy log of every OTA publish.

When a change affects product language, architecture, Cloud contracts, or an accepted
decision, update the appropriate canonical Nabu product/spec/decision note as well as
the implementation handoff. The implementation handoff and this README must not be
used to silently replace an accepted product or engineering contract.

If Nabu is unreachable:

- Continue with an otherwise safe, scoped mobile task when the local code, this
  README, and existing tests provide enough context.
- Update this README with a dated `Nabu sync pending` entry that says what was
  checked, what could not be read or written, and which changes need reconciliation.
- Do not invent Nabu content, claim that a remote update succeeded, or put credentials
  into a local fallback.
- Retry Nabu when it becomes available, reconcile conflicts against the latest
revision, then remove the pending entry only after both records have been verified.

## Reusable release handoff skill

The repository includes `$allies-mobile-release-handoff` at
`.agents/skills/allies-mobile-release-handoff/`. Use it when a mobile change is ready
to release. It guides agents through validation, the OTA-versus-native-build decision,
README and Nabu synchronization, focused commits, EAS metadata capture, and final
verification. It does not grant permission to commit, push, publish an OTA, or create
a build when the current request has not authorized those actions.

## Current scope and boundary

Implemented here is the mobile presentation and local interaction slice for:

`welcome -> name -> look -> job -> personality -> preview`

The onboarding creation flow is intentionally local for now. `apps/mobile/src/app/index.tsx`
renders `OnboardingFlow`; it owns local state and generates a static local greeting.
This slice does **not** yet create an Ally in Cloud, call a greeting-generation API,
persist onboarding progress, or complete the waitlist flow. The initial INT-008
native session/account boundary is now implemented separately; live Cloud sign-in
remains disabled until the accepted native routes are deployed and enabled.

The current mobile onboarding implementation is a UI handoff, not a replacement for
the accepted web/waitlist contract. Final copy and choreography remain subject to
the canonical product/design notes.

## INT-008 native Google auth and personal account

The accepted implementation handoff is maintained in Nabu at
`projects/allies/engineering/specs/interface/INT-008-mobile-google-auth-and-account.md`.
The local implementation is deliberately thin around the shared Cloud client:

- `src/features/auth/google-sign-in.ts` runs one in-memory PKCE S256 attempt through
  the system browser, verifies the returned state and exact redirect, and exchanges
  only the one-time Cloud code.
- `src/lib/session/native-session-adapter.ts` owns access-token memory, serialized
  refresh rotation, restore, revocation, logout uncertainty, and terminal cleanup.
- `src/lib/session/secure-session-store.ts` persists only the current opaque refresh
  token in Expo SecureStore. Access tokens, verifiers, state, exchange codes, URLs,
  and account DTOs are not persisted.
- `src/lib/cloud/native-cloud-client.ts` reuses the shared transport and injects a
  bearer only for the exact authenticated routes `GET /api/v1/auths/me`, `PATCH
  /api/v1/auths/me/profile`, the avatar prepare/complete/read/delete routes, and
  `GET /api/v1/workspaces/{workspace_id}`. Native auth and direct object-storage
  requests remain cookie-free and bearer-free where required.
- `src/app/sign-in.tsx`, `src/app/auth/return.tsx`, and `src/app/account.tsx` provide
  the public sign-in entry, safe cold-return fallback, guarded account surface,
  profile-name editing, personal Workspace details, and avatar controls.
- `src/features/account/avatar-upload.ts` bounds avatar files at 10 MiB, hashes the
  actual bytes, uses the exact signed upload URL/headers, and completes only after a
  successful direct upload. It never adds a Cloud bearer to object storage.

### Local configuration

Copy `apps/mobile/.env.example` to an ignored local environment file and replace the
placeholder return URL with the exact HTTPS URL registered with Cloud and the mobile
platform. The current Nabu handoff records that the native routes are merged in Cloud
but are not yet present in live staging/production schemas; therefore an unconfigured
build truthfully shows sign-in as unavailable rather than falling back to browser
cookies or a WebView. `app.config.ts` derives Android App Links and iOS Associated
Domains from that same exact URL when it is supplied at build time. The domain's
Android `assetlinks.json`, iOS `apple-app-site-association`, platform registration,
and Cloud enablement gate must still be completed before device proof.

The auth/account dependency and config changes are native. They require a new EAS
binary with app/runtime version `1.0.2`; the installed `1.0.1` APK cannot receive the
new SecureStore/ImagePicker/auth configuration through OTA. After the compatible APK
exists, later JavaScript-only account/UI changes can use the normal preview OTA path.

## EAS build and OTA workflow

The repository is configured for Expo EAS Update and is now linked to the Allies EAS
project. The first preview build has completed. The current setup is:

- `expo-updates` installed at the SDK-compatible version;
- `runtimeVersion` using the `appVersion` policy;
- update checks enabled on app load;
- `eas.json` `preview` profile producing an internal Android APK on the `preview`
  channel;
- `eas.json` `production` profile targeting the `production` channel.

### One-time project linking and first install

Run from `apps/mobile` after authenticating to the Allies Expo account:

```text
bunx eas-cli login
bunx eas-cli update:configure --platform android
bunx eas-cli build --platform android --profile preview
```

The configure command writes the real EAS project/update URL and project ID into the
Expo configuration. Commit those generated project-link fields; never replace them
with a guessed ID or put an access token in the repository. Install the resulting APK
on the Android device once.

The current Android application ID is `com.daviddll.allies`. Treat it as permanent;
changing it later creates a different Android application.

### Publishing an OTA UI update

After a meaningful code change is committed and pushed, run:

```text
bunx eas-cli update --channel preview --environment preview --message "Short description of the change"
bunx eas-cli update --channel production --environment production --message "Short description of the change"
```

Use the `preview` command for the installed internal APK and the `production` command
only for a production binary. SDK 55 and later require the explicit `--environment`
flag for EAS Update. The installed preview app will check for the update when it
launches, download the compatible JavaScript/assets, and apply them after restart. No
APK reinstall is needed for normal JavaScript, styling, animation, or referenced-asset
changes. Do not publish from an uncommitted worktree; the update should always be
traceable to a commit.

### When a new APK is required

Publish a new native build whenever the native runtime changes, including adding,
removing, or upgrading a native dependency; changing Expo/React Native; modifying
native Android configuration, permissions, plugins, schemes, or app version; or
changing the runtime-version policy. OTA updates must remain compatible with the
native runtime already installed on the device.

The `preview` channel is for device testing. Production releases should use a separate
production build/channel and should not be published to `preview`. The EAS project is
now linked and the first preview APK artifact is available for installation.

### Current release metadata

This is the version state verified on 2026-08-21:

| Item | Current value | Meaning |
| --- | --- | --- |
| App version | `1.0.2` | `expo.version`; this is also the next runtime version because the app uses the `appVersion` policy. A new native build is pending. |
| Package version | `1.0.2` | `apps/mobile/package.json` package metadata; it does not replace `expo.version`. |
| Expo SDK | SDK 57 (`expo ~57.0.9`; resolved app config `57.0.0`) | Native/runtime baseline for the current mobile app. |
| React Native | `0.86.2` | Native runtime dependency. |
| React | `19.2.3` | JavaScript runtime dependency. |
| `expo-updates` | `~57.0.16` | SDK-compatible OTA client included in the preview native build. |
| Reanimated | `4.5.1` | Existing motion runtime used by the onboarding UI. |
| EAS CLI | `22.2.0` | CLI version used for local configuration/authentication checks; it is not an app runtime dependency. |
| Android application ID | `com.daviddll.allies` | Permanent Android package identity for this app. |
| Previous preview build | `FINISHED` — EAS build `d0fc5e35-1a1c-4230-ac69-4078ac2e39cf` | [Android APK](https://expo.dev/artifacts/eas/VAcLE1_CJVuV_jvUH7FQLX5gyPewn_1dBcp8vXGZaqg.apk) for the superseded `1.0.0` runtime. |
| Last completed preview build | `FINISHED` — EAS build `e076bfe1-2846-4872-9a06-a71f9e0c573e` | [Installable Android APK](https://expo.dev/artifacts/eas/EjDEimT7CWWGBHP2tC61OhOzqnh4-KGbHVMSf7YBkfA.apk) on the `preview` channel; this is the `1.0.1` binary and does not contain INT-008 native modules. |
| Last completed build versions | App version `1.0.1`, runtime `1.0.1`, Android build version `2` | Values reported by the completed EAS build for commit `7b776e2`; `1.0.2` is the next required native runtime. |
| Production profile | `production` channel | Profile exists; no production build or publish has been performed. |
| EAS project link | Linked | `updates.url` and `extra.eas.projectId` are present in the Expo app config; credentials are not stored in the repository. |
| EAS app version source | `remote` | Future Android build numbers are managed by EAS; `preview` and `production` profiles auto-increment them. |

The preview APK includes `expo-updates`; installing a development build does not prove
OTA is active. The last completed `1.0.1` artifact is ready for device installation
and smoke testing, while `1.0.2` is the next native build for INT-008. After each APK
or OTA release, record the commit SHA, build ID or update group, artifact URL when
applicable, and EAS update channel/message at the release boundary.

### Version and release rules

- OTA-only JavaScript, styling, animation, and bundled-asset changes keep the current
  app/runtime version, are committed and pushed, and are published to the matching
  EAS channel.
- Native dependencies, Expo/React Native upgrades, native Android configuration,
  permissions, plugins, schemes, or any other native runtime change require a new
  build. The release gate is: bump `expo.version`, run `bunx expo config --type public`,
  confirm the resolved `runtimeVersion` changed, build that binary, and only then
  publish an OTA for the new runtime. Do not send an incompatible OTA to an older
  binary.
- EAS now owns Android build-number increments remotely for both preview and production
  profiles. This prevents repeated native builds from reusing the same developer-facing
  build number. It does not replace the `expo.version` runtime gate: native runtime
  changes still require a deliberate `expo.version` bump.
- Every meaningful release entry should capture: date, app version, runtime version,
  build or OTA channel, commit SHA, short change summary, validation result, and (for
  OTA releases) the EAS update message/group ID.

### Release history

- **2026-08-21 — OTA foundation prepared:** added SDK-compatible `expo-updates`, the
  `appVersion` runtime policy, launch-time update checks, and preview/production EAS
  profiles.
- **2026-08-21 — EAS project linked:** configured the EAS update URL/project ID and
  permanent Android application ID `com.daviddll.allies`; the first preview APK
  completed. No OTA publish has occurred yet.
- **2026-08-21 — Preview build completed:** EAS build
  `d0fc5e35-1a1c-4230-ac69-4078ac2e39cf` finished for app/runtime `1.0.0` and Android
  build version `1`. EAS recorded repository HEAD `66a3d955`; the build was initiated
  from a dirty working tree, so the final release must be committed and reconciled
  before it is treated as a reproducible handoff. Device installation is pending.
- **2026-08-21 — Conversation preview polish:** commit `f992d15` fixes Android
  descender-safe Ally-name layout and adds a fast, capped greeting typewriter reveal.
  Full validation passed with 28 test files and 147 tests; no OTA publish has occurred
  yet.
- **2026-08-21 — Preview OTA published:** commit `040b82f` was published to the
  `preview` channel for runtime `1.0.0` with update group
  `b05609a0-a82e-437e-b492-cdf213322d9b`. The Android update ID is
  `01a02293-ffc8-756e-a1f9-051d1b693720`; the message was `Fix conversation name
  clipping and greeting reveal`.
- **2026-08-21 — Version 1.0.1 prepared:** replaces the overlapping preview fades
  with a sequential name-then-greeting typewriter and configures a native Allies
  splash. The version bump is required because splash plugin changes affect native
  resources; a new preview APK is required.
- **2026-08-21 — Preview build 2 completed:** EAS build
  `e076bfe1-2846-4872-9a06-a71f9e0c573e` finished for app/runtime `1.0.1`, Android
  build version `2`, and commit `7b776e2`. [Install the APK](https://expo.dev/artifacts/eas/EjDEimT7CWWGBHP2tC61OhOzqnh4-KGbHVMSf7YBkfA.apk).
  The build includes the native splash and typewriter fixes; no `1.0.1` OTA has been
  published.
- **2026-08-21 — INT-008 native auth/account implementation prepared:** adds the
  Cloud native contract adapter, SecureStore session lifecycle, PKCE browser return,
  profile/Workspace/avatar surface, environment-driven Android/iOS app-link config,
  and SDK-compatible native dependencies. Version `1.0.2` is set because a new APK is
  required; no `1.0.2` build or OTA publish has occurred. Implementation commit:
  `8d791a9`.

### GitHub merges and installed devices

A GitHub push or merge changes the repository; it does not change an already-installed
APK by itself. The expected path is:

1. Merge the coworker’s commit and update the README in that same meaningful change.
2. For JavaScript/UI/assets only, publish the merged commit to the matching EAS
   channel with `eas update` and the correct environment.
3. The installed preview binary downloads the compatible update on launch and applies
   it after restart.
4. For native dependencies or native configuration, bump `expo.version`, create a new
   EAS build, and install the new binary instead of publishing an OTA.

There is no GitHub-to-EAS auto-publish workflow configured yet. A merge will therefore
not publish an update unless the device owner explicitly runs the EAS command. When
an OTA is published, record its channel, commit SHA, message, and update group in Nabu.

### Device-owner OTA action

The device owner is responsible for deciding when a merged visual update should reach
their phone and for running the publish command personally from `apps/mobile`:

```text
bunx eas-cli update --channel preview --environment preview --message "Describe the changes"
```

Coworkers and agents may prepare, review, commit, and push the code, but they must not
assume that a GitHub merge updates the device or publish an OTA on the owner's behalf.
This command is run once per ready batch of JavaScript/UI/asset changes, not after
every local edit. Native changes still require a new APK.

## Source map

### Flow and state

- `src/app/index.tsx` — mobile entry point for the current onboarding surface.
- `src/app/_layout.tsx` — fonts, splash lifecycle, providers, and signed-in route
  redirection.
- `app.config.ts` — derives native App Links/Associated Domains from the exact
  registered HTTPS return URL when build-time configuration is present.
- `src/lib/native-link-config.test.ts` — validates the native link allowlist shape
  and rejects unsafe return URLs.
- `src/features/onboarding/onboarding-flow.tsx` — owns the flow, local state,
  forward/back navigation, validation, accent color, and screen composition.
- `src/features/onboarding/onboarding-state.ts` — step, Ally shape/color,
  personality, form state, validation, progress, and local greeting helpers.
- Current Ally palette order is `#FF5800`, `#FD304F`, `#0D92FD`, `#BE9BF5`,
  `#3446E9`, `#A3F06F`, and `#FBE65F`.
- Progress values are name `0`, look `0.45`, job `0.7`, personality `0.9`, and
  preview `1`.
- `src/features/onboarding/onboarding-screen.tsx` — shared screen composition.
- `src/features/onboarding/onboarding-shell.tsx` — shared safe-area layout,
  header, footer, and screen chrome.
- `src/features/onboarding/onboarding-shell-config.ts` — per-step shell/header
  configuration.
- `src/features/onboarding/onboarding-header.tsx` and
  `src/features/onboarding/onboarding-progress.tsx` — fixed back control,
  progress ring, and persistent header accessory.

### Screen implementations

- `src/features/onboarding/ally-name-screen.tsx` — name input screen.
- `src/features/onboarding/onboarding-look-screen.tsx` — Ally shape carousel and
  color selector.
- `src/features/onboarding/onboarding-job-screen.tsx` — job/responsibility input
  placeholder for the next onboarding step.
- `src/features/onboarding/onboarding-personality-screen.tsx` — personality chips,
  helper tooltip, and personality editor.
- `src/features/onboarding/onboarding-preview-screen.tsx` — coming-alive,
  thinking, generated greeting, Ally handoff, name typing, and composer states.
- `src/features/onboarding/onboarding-ally-preview.tsx` and
  `src/features/onboarding/ally-character.tsx` — reusable Ally artwork and
  selected-color rendering.
- `src/app/sign-in.tsx`, `src/app/auth/return.tsx`, and `src/app/account.tsx` —
  native sign-in, cold-return fallback, and guarded personal account surface.
- `src/features/auth/` — in-memory PKCE/state flow and system-browser return parsing.
- `src/features/account/` — profile validation, account queries, and signed avatar
  upload lifecycle.
- `src/lib/session/` — SecureStore refresh port and serialized native session adapter.
- `src/lib/cloud/native-cloud-client.ts` — shared Cloud transport with an explicit
  authenticated route allowlist.

### Motion and reusable UI

- `src/features/onboarding/onboarding-motion.ts` — centralized onboarding copy,
  timing, easing, spring, and reduced-motion values.
- `src/features/onboarding/onboarding-layout.ts` — shared spacing, inset, carousel,
  accessory, and typography constants.
- `src/features/onboarding/onboarding-preview.ts` — preview timing, structured
  greeting parsing, handoff geometry, and preview typography constants.
- `src/features/onboarding/ally-entrance-motion.ts` — Ally entrance choreography.
- `src/features/onboarding/onboarding-typewriter-text.tsx` — structured progressive
  greeting renderer that preserves paragraph, heading, and hanging-indent bullet layout.
- `src/components/ui/shiny-text.tsx` — native masked gradient shine used for
  `Thinking`.
- `src/components/ui/keyboard-dismiss-view.tsx` and
  `src/components/ui/keyboard-dismiss.ts` — dismiss the keyboard when tapping
  outside an input while preserving input taps.
- `src/components/ui/primary-button.tsx` — shared wide action button.
- `src/components/ui/use-animated-color.ts` — lightweight color interpolation.

### Assets

- `assets/allies/fonts/OpenRunde-Medium.otf`
- `assets/allies/fonts/OpenRunde-Semibold.otf`
- `assets/allies/icons/back-chevron-icon.svg`
- `assets/allies/icons/paint.svg`
- `assets/allies/icons/placeholder-rolly.svg`
- `assets/allies/icons/send.svg`
- `assets/allies/icons/white-check.svg`
- `assets/allies/icons/allies-app-icon.png` — shared app icon and native splash mark.
- `assets/allies/characters/` — SVG Ally idle/thinking artwork and reduced-motion
  variants.
- `assets/allies/gifs/`, `assets/allies/webp/`, and `assets/allies/sprites/` —
  optimized artwork variants used where the animated/native path needs them.

### Native splash

- `expo-splash-screen` renders the existing Allies app icon at 180px on brand orange
  `#FF5800` using `contain` scaling.
- The root layout keeps the native splash visible only while Open Runde loads, then
  hides it with the platform-supported 350ms fade. There is no artificial timeout.
- Splash plugin changes are native configuration. The current app/runtime version is
  `1.0.2` because this INT-008 wave also adds native auth, SecureStore, ImagePicker,
  and build-time link configuration. The installed `1.0.1` binary cannot receive
  these changes through OTA alone.

## Implemented onboarding behavior

### Shared shell and progress

- The top safe-area content starts 36px below the status-bar content baseline.
- Every onboarding step uses the same 40x40 back-button circle and the same progress
  ring position. The shell owns this chrome so screens do not independently place or
  refresh their own header assets.
- Back navigation derives progress from the current step. Moving backward therefore
  removes progress for the step being left instead of keeping stale filler.
- The shell uses a 14px content inset for ordinary text and controls. Viewport-wide
  carousels intentionally escape that inset; their scroll content reaches the screen
  edges without a white side gutter.
- The central Allies logo remains the brand orange. The selected Ally color is used
  for onboarding accents such as the progress ring, active action button, selected
  name text, dots, check state, and personality controls.
- The placeholder Ally is 40x40 in the header on the look, job, and personality
  stages. The chosen colored Ally replaces it from the job-description stage through
  the rest of creation and preview.
- Shared footer actions are wide reusable buttons. Disabled actions use `#D9D9D9`
  with white text; enabled actions use the current onboarding accent. Color changes
  ease instead of switching instantly.

### Welcome and name

- The welcome CTA says `Meet your first ally`.
- The name prompt is `What do you want to name your ally?` and the empty field
  says `give me a name`.
- The name field is centered and uses Open Runde Semibold, 18px, 18px line height,
  and `-1px` letter spacing. The box reserves descender-safe vertical space so
  letters such as `y` are not clipped and the caret remains vertically centered.
- Typed name text uses the active Ally color. The Next button eases from disabled
  grey to the accent once at least one character is entered.
- Inputs are capped by their screen-specific maximums and tapping outside a field
  dismisses the keyboard.

### Ally look and color

- The shape carousel contains Ghosty, Rolly, Boxy, and Rocky. It is horizontally
  paged, centered on the viewport, and uses repeated pages with a middle starting
  copy so swiping in either direction feels continuous.
- The color palette is ordered orange, red, blue, purple, indigo, green, yellow:
  `#FF5800`, `#FD304F`, `#0D92FD`, `#BE9BF5`, `#3446E9`, `#A3F06F`, and `#FBE65F`.
- The carousel group is edge-to-edge and vertically centered. It does not inherit
  ordinary page padding. Rocky has a small neutral-artwork correction so its unique
  bounds are not clipped.
- A first-use nudge moves the carousel 24px and returns it to rest. If the user has
  not interacted, the nudge repeats every 5 seconds. Any drag or dot selection stops
  the nudges; timers and animation frames are cleaned up on unmount. Reduced motion
  disables the nudge.
- The color selector is also edge-to-edge. The color circles remain full-size while
  the chosen Ally artwork scales to about 70% of its neutral size, preserving the
  colored circle's visual presence. The selected state uses the supplied white check
  asset and a small pop-in animation.
- Color changes animate through a short eased transition. The selected color is
  state, not a one-off visual mutation, so it carries forward to later screens.
- The paint icon sits 6px to the left of `Swipe then pick a colour`. That hint sits
  36px above the color/action region, and the color row sits 36px above the Next
  button according to the layout constants.

### Job

- The job screen is the next placeholder stage after appearance selection.
- It uses the shared header, placeholder/selected Ally behavior, keyboard-safe text
  input, character limit, disabled/enabled action state, and outside-tap keyboard
  dismissal. Its Cloud persistence and final contract are not implemented in this
  local slice.

### Personality

- The question-mark control has a 36x36 outer circle and a 24x24 inner question-mark
  asset. The personality row aligns with the editor surface rather than starting at
  the viewport edge.
- The first gap from the question-mark control to the first chip is 12px; subsequent
  chip gaps are 8px. The chip row can scroll horizontally, while its initial content
  alignment remains inside the editor inset.
- The available personality chips are `Concise`, `Quirky`, `Analytical`, and `Funny`.
- The editor surface is the neutral grey `#F3F3F3` in the current implementation;
  any washed-out accent treatment must be made intentionally and reflected in both
  this README and Nabu if the product direction changes again.
- Selecting `Concise` writes `I want you to be concise` into the editor. Additional
  selections append comma-separated traits, for example
  `I want you to be concise, quirky`. Removing a selection rebuilds the generated
  sentence while preserving manually entered text only where the current screen
  contract allows it.
- Opening the personality help tooltip disables Save. The tooltip can be dismissed
  independently, and outside taps dismiss the keyboard without treating the tooltip
  as an input tap.

### Preview and first conversation surface

- `Coming alive....` uses a lightweight per-character wave. The letters move in a
  short staggered wave rather than appearing as a single unanimated label. Reduced
  motion renders the settled text directly.
- `Thinking` uses the native `ShinyText` component: a masked white gradient sweeps
  across the accent-colored text. The effect pauses when it is not active and has a
  reduced-motion static path.
- The thinking Ally is smaller (24x24) beside the thinking label. When generation
  completes, Reanimated measures the thinking row and header, then springs the Ally
  from its current position into the header instead of removing it and reappearing.
  The Ally name types in at 55ms per character after the handoff settles. The greeting
  waits for the name to finish before it starts.
- The final greeting is represented as structured blocks: paragraphs, a heading row,
  and bullet rows. The sparkle heading has its own row. Bullet markers use a fixed
  column and the text uses a separate flex column, so wrapped lines align under the
  bullet text instead of underneath the marker.
- Greeting text reveals progressively with a lightweight native typewriter. Only the
  currently revealed substring is rendered; longer greetings advance in small chunks
  so the complete reveal stays within roughly 2.4 seconds. Reduced motion renders the
  full name and greeting immediately.
- Greeting body text uses Open Runde Medium, 16px, 22px line height, and `-0.5px`
  letter spacing. Bold inline content uses Open Runde Semibold with the same size,
  line height, and letter spacing.
- The preview header Ally is 24x24, the name has a 12px gap from the Ally, and the
  greeting starts 18px below the header row. The name uses a 24px line box with
  Android font padding enabled so descenders such as `y` remain visible.
- The composer starts with a 100px radius and uses Open Runde Medium at 16px with
  16px line height and `-0.5px` letter spacing. It becomes less rounded as its
  content grows. Tapping outside it dismisses the keyboard. The send control uses
  the selected Ally color.

## Motion contract

Keep values in `onboarding-motion.ts` and preserve reduced-motion paths. Current
values include:

| Interaction | Current contract |
| --- | --- |
| Color transition | 220ms, cubic-bezier `[0.22, 1, 0.36, 1]` |
| Check pop | Initial scale `0.84`; spring damping `18`, stiffness `300`, mass `0.7` |
| Coming-alive wave | 1350ms cycle, 70ms character stagger, 4px amplitude |
| Carousel nudge | 24px; 300ms delay; 300ms return; repeat every 5000ms until interaction |
| Preview entrance | 2400ms staged entrance timing |
| Thinking shine | 1700ms sweep cycle |
| Ally name typewriter | 55ms per character, after the Ally handoff |
| Greeting typewriter | 12ms cadence; adaptive chunks with a 2400ms reveal budget |
| Avatar handoff | Reanimated spring, damping `24`, mass `0.82`, stiffness `190` |

Animate only the properties that need motion, prefer UI-thread Reanimated work for
per-frame work, and clean up timers, intervals, measurement callbacks, and animated
styles. Do not introduce a general animation framework for one more onboarding
interaction. Every meaningful animation needs a reduced-motion path.

## Validation

The latest completed local validation for the INT-008/mobile implementation was:

```text
bun run test:run       # 39 test files, 197 tests passed
bun run typecheck      # cloud-client, web, and mobile passed
bun run lint           # 0 errors; 8 existing web warnings
bun run build:web      # passed
bun run bundle:mobile  # Expo iOS export passed
bun run cloud:check    # OpenAPI snapshot verification/generation passed
git diff --cached --check
```

Focused onboarding tests cover state transitions, layout constants, motion values,
carousel behavior, structured preview blocks, keyboard dismissal, and Ally entrance
motion. The main focused files are `onboarding-state.test.ts`,
`onboarding-layout.test.ts`, `onboarding-motion.test.ts`, `onboarding-preview.test.ts`,
`onboarding-shell.test.ts`, `keyboard-dismiss.test.ts`, and
`ally-entrance-motion.test.ts`. Run the relevant focused test while iterating, then run the full checks before
handoff.

The Android emulator has previously shown a cold Expo development-launch input-focus
ANR around 20 seconds. Native logs eventually reached `Running "main"` without a
JavaScript module-resolution or fatal-exception error; this is not evidence that
device smoke testing is fully clean. Record new emulator evidence separately rather
than marking the app healthy based only on the eventual log line.

## How to continue safely

- Preserve the shared shell and flow-local state boundaries. Do not re-create the
  back button or progress ring inside individual screens.
- Keep carousel surfaces edge-to-edge while ordinary content keeps its inset.
- Reuse `useAnimatedColor`, existing Reanimated primitives, and current assets before
  adding a dependency.
- Keep user-facing copy, timing, spacing, and asset decisions in the owning feature
  modules with tests for stable values.
- Keep future Cloud creation, durable onboarding persistence, and conversation
  streaming behind their accepted Nabu contracts; the INT-008 auth/account boundary
  is already implemented and remains gated by Cloud deployment/enablement and
  platform return-link registration.
- Run mobile lint, typecheck, targeted tests, and the full test suite before handoff.
- Update Nabu and this README together after meaningful changes, following the sync
  contract above.

## Nabu sync log

Keep this section short and current. It is for operational visibility, not a second
decision log.

- 2026-08-21 — Nabu INT-008 spec, delivery ticket, and mobile handoff were
  synchronized with implementation commit `8d791a9`; the handoff records the
  `1.0.2` native-build gate and remaining Cloud/platform/device evidence. No
  `Nabu sync pending` item is open.
