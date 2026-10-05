# Mobile post-onboarding notifications and Allies home implementation plan

> **For agentic workers:** This plan is executed inline in the current task. No subagents are used.

**Goal:** Restore the approved notification prompt visual, request native notification permission from its primary action, and continue both notification choices into the first mobile Allies home surface.

**Architecture:** Keep `OnboardingFlow` as the owner of the in-memory onboarding state. Add one small notification-permission adapter for the OS request and one presentation module for the roster. The roster receives the Ally already held by the flow; it does not create a second mock catalog or call Cloud.

**Tech Stack:** Expo SDK 57, React Native 0.86, TypeScript, Expo Notifications, Expo Image, React Native SVG, React Native Reanimated, React Native Safe Area Context, Vitest, Bun.

## Global Constraints

- Keep the Cloud path and local mock boundary unchanged. This screen does not add a roster API, push token registration, or notification delivery.
- Add `expo-notifications` only for the requested OS permission prompt. On Android, create the default channel before requesting permission so Android 13+ can show its prompt.
- Always advance after the user chooses Allow notifications or I’ll do this later. A denied or unavailable permission must not block the product walkthrough or be presented as granted.
- Restore the notification preview to the static approved skeleton bars. Do not retain a shimmer overlay that degrades the supplied visual.
- Reuse `OnboardingAllyPreview`, `PrimaryButton`, existing colors, loaded Open Runde fonts, safe-area layout, and existing flow state.
- Keep ordinary content inside the safe area. Use the existing 50px bottom breathing room for the roster action.
- This native dependency requires a new development/release build. The JavaScript/UI portion can use OTA only after a compatible binary includes the dependency.
- Keep this plan portable: no personal workstation paths, credentials, private URLs, or live user data.

## Feature Overview

- Problem: The post-onboarding notification screen currently ends the flow, uses a visually incorrect shimmer treatment, and does not request OS permission or lead to an Allies home.
- Target users: New users who have completed Ally creation and the first account handoff.
- Source docs/specs: Nabu `projects/allies/index.md`, `projects/allies/product/allies-product-design-spec.md`, `projects/allies/product/allies-first-product-requirements.md`, `projects/allies/engineering/specs/interface/mobile-onboarding-implementation.md`, the mobile README, and the supplied screen reference.
- Success outcome: The prompt matches the existing Allies visual language, the primary action opens the native permission prompt when available, both choices reach a roster screen, and the roster shows the newly created Ally with a clear create-another action.

## User Stories

1. As a new user, I want to choose whether Allies can notify me, so that I control notification access.
2. As a user who allows or declines notifications, I want to continue into the app, so that a permission choice never traps onboarding.
3. As a signed-in or locally seeded user, I want to see my Allies and create another one, so that the app has a clear home after setup.

## Scope

### In Scope

- Add an explicit `allies` destination after `notifications` in the local flow state.
- Restore the notification preview card to static `#D9D9D9` bars and preserve the supplied copy and button design.
- Add `expo-notifications` at the Expo SDK 57 compatible version and configure its plugin.
- Request permission from the Allow notifications action, including the Android channel prerequisite.
- Continue after either action, regardless of granted, denied, or unavailable result.
- Add a mobile Allies roster screen with the user avatar treatment, create-Ally control, search treatment, Ally row, preview text, time, presence dot, and orange Make an ally action.
- Add state and pure display helper tests plus mobile lint, typecheck, focused tests, and diff validation.

### Out of Scope

- Push-token registration, remote notification delivery, notification listeners, deep links, or notification settings synchronization.
- Durable Cloud Ally collection loading, account persistence, search behavior, conversation navigation, or a second mock data store.
- Changes to the existing onboarding shell, account sheet, Ally creation contract, or Cloud transport.

### Dependencies and Assumptions

- Expo SDK 57 recommends `expo-notifications` `~57.0.16`.
- The existing EAS/dev binary may not contain the new native module. A new native build is required before testing the OS prompt on a physical device or emulator.
- The current flow already owns the completed Ally name, shape, color, and greeting. The roster displays that record as the first local Ally until the durable workspace endpoint is wired.
- Nabu defines the long-term Allies home and a global notification preference, but does not require delivery infrastructure for this visual slice.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/lib/notifications/notification-permission.ts` | `requestNotificationPermission` | `function requestNotificationPermission(): Promise<void>` | No user data; uses the current native platform | Resolves after the request attempt | Creates the Android default channel, requests OS permission, and allows caller cleanup/continuation if the platform rejects |
| `apps/mobile/src/features/onboarding/onboarding-post-setup.tsx` | `OnboardingNotificationsScreen` | `OnboardingNotificationsScreen(props): JSX.Element` | Existing Ally shape/color and optional async action callbacks | Notification prompt | Invokes one action at a time; no permission result is represented as success in UI |
| `apps/mobile/src/features/onboarding/onboarding-allies-screen.tsx` | `OnboardingAlliesScreen` | `OnboardingAlliesScreen(props): JSX.Element` | Existing Ally identity, color, and greeting; create callback | Roster surface | Resets only the flow when the create action is selected |
| `apps/mobile/src/features/onboarding/onboarding-preview.ts` | `getRosterPreview` | `function getRosterPreview(greeting: string, maximumLength?: number): string` | Treats greeting as untrusted display text; normalizes whitespace and bounds output | Single-line preview with ellipsis when needed | Pure; no I/O |

### API and Transport Contracts

Not applicable. This slice does not add a Cloud endpoint or change a Cloud request. The native permission API is an operating-system boundary, not an Allies network contract.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `OnboardingStep` | `apps/mobile/src/features/onboarding/onboarding-state.ts` | Existing steps plus `allies` | Flow starts at `welcome`; `notifications` advances to `allies` | `allies` is terminal in this local walkthrough; back returns to `notifications` | In-memory only |
| `OnboardingAlliesScreenProps` | `apps/mobile/src/features/onboarding/onboarding-allies-screen.tsx` | `allyName`, `allyShape`, `selectedColor`, `greeting`, `onCreateAlly` | Name and greeting have defensive fallbacks; color falls back to brand orange | Displays only the flow-owned Ally; no fake second record | Replace the input with the durable workspace collection when that contract is enabled |
| `OnboardingNotificationsScreenProps` | `apps/mobile/src/features/onboarding/onboarding-post-setup.tsx` | `allyShape`, `selectedColor`, `onAllow`, `onSkip` | Action callbacks accept sync or async functions | A busy guard prevents duplicate permission prompts | No permission state is persisted in this slice |

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Allow notifications | `onAllow(): void | Promise<void>` | `notifications -> allies` after the request attempt | Button -> native adapter; no Cloud mapping | Android channel is created first; granted, denied, and native failures all continue |
| I’ll do this later | `onSkip(): void` | `notifications -> allies` | No external call | Immediate continuation without a permission request |
| Make an ally | `onCreateAlly(): void` | `allies -> welcome` with `INITIAL_ONBOARDING_FLOW` | No external call | Starts a fresh local creation flow |
| Ally preview | `getRosterPreview(greeting)` | Existing greeting -> bounded one-line preview | Flow greeting -> display-only text | Empty greeting uses a short fallback |

## Phases

### Phase 1 - Flow contract and visual rollback

- Goal: Make the requested destination explicit and remove the notification-card regression.
- Work items: Extend the step union/maps, add `allies` transition tests, replace shimmer blocks with static bars, and update the synchronized plan.
- Impacted files: `onboarding-state.ts`, `onboarding-state.test.ts`, `onboarding-post-setup.tsx`, `shiny-text.tsx`, `onboarding-motion.ts`, and related tests.
- Exit criteria: Focused onboarding tests prove `notifications -> allies`; no notification screen imports the block shimmer.

### Phase 2 - Native permission boundary

- Goal: Make the primary notification action call the OS permission flow safely.
- Work items: Install the Expo SDK 57 compatible package, add the config plugin, create the small adapter, wire async allow/skip callbacks, and advance in a `finally` path.
- Impacted files: `apps/mobile/package.json`, lockfile, `apps/mobile/app.json`, `onboarding-flow.tsx`, `onboarding-post-setup.tsx`, and the permission adapter.
- Exit criteria: The app bundles with the module; allow requests permission in a compatible native build; denied and failure paths still reach `allies`.

### Phase 3 - Allies roster surface

- Goal: Present the first finished-app home screen after onboarding.
- Work items: Add the roster screen with the existing Ally renderer, responsive safe-area layout, reference controls, preview truncation, presence treatment, and reusable CTA; make the CTA restart onboarding locally.
- Impacted files: `onboarding-allies-screen.tsx`, `onboarding-flow.tsx`, `onboarding-preview.ts`, and focused tests.
- Exit criteria: Both notification paths render the roster with the selected Ally identity/color and the Make an ally action starts a fresh flow.

### Phase 4 - Verification

- Goal: Prove the change is reviewable and does not regress onboarding.
- Work items: Run focused tests, mobile lint, mobile typecheck, Expo config validation, and diff validation.
- Impacted files: Mobile runtime and tests only.
- Exit criteria: All listed checks exit successfully; native prompt remains a manual check in a rebuilt binary.

## Acceptance Criteria

1. The notification preview uses the approved static layout and `#D9D9D9` skeleton bars without a visually dominant shimmer overlay.
2. Tapping Allow notifications creates the Android channel when needed and calls the native notification permission request.
3. Tapping I’ll do this later does not request permission.
4. Granted, denied, or failed native permission requests all continue to the Allies roster.
5. The roster shows the completed Ally's selected color, shape, name, and a bounded greeting preview.
6. The roster includes the supplied visual treatments for profile initials, create-Ally control, search control, presence dot, last-message time, and orange Make an ally action.
7. Make an ally resets the local flow to the welcome screen without adding another data model.
8. No push token, network request, password, or durable fake catalog is introduced.
9. Focused tests, mobile lint, mobile typecheck, Expo config validation, and `git diff --check` pass.

## Backend Considerations

Not applicable. Cloud remains the owner of durable Ally collections and global notification preferences. When that collection is enabled, replace the flow-local single record with the typed workspace-scoped query; do not add a parallel long-term catalog.

## Frontend Considerations

### Data Path

- User action entry: Notification prompt action.
- Client route/component: `OnboardingNotificationsScreen -> OnboardingFlow -> OnboardingAlliesScreen`.
- Client API route/proxy: None.
- Backend endpoint: None.
- Response -> UI model mapping: Existing flow `allyName`, `allyShape`, `selectedColor`, and mock greeting pass directly into the roster.
- Error/loading/retry path: The permission action is guarded against duplicate presses; native request failure is swallowed by the flow continuation path so setup cannot dead-end. No success copy claims permission was granted.

### State Management Considerations

- State ownership: `OnboardingFlow` owns the step and Ally identity; the notification screen owns only its short-lived busy state.
- Source of truth vs derived state: The roster derives one display row from flow state; preview text is bounded and normalized at the display boundary.
- Caching/invalidation: None.
- Concurrency and dedupe: Disable both notification actions while the allow request is in flight. The flow transition is idempotent at the UI level because the screen unmounts after completion.
- Accessibility: Keep button roles/labels, meaningful Ally labels, and do not use color alone to communicate the selected Ally.

## Test Plan

- Unit tests: `allies` step transitions, greeting preview whitespace/length behavior, existing onboarding regressions, and motion constants that remain in use.
- Integration/API tests: Not applicable; native permission manual evidence is required in a rebuilt binary.
- Regression checks: Mobile onboarding test suite, mock greeting test, mobile lint, mobile typecheck, Expo config resolution, and `git diff --check`.
- Manual verification checklist: Reach the prompt; confirm static card appearance; tap Later and verify the roster; restart and tap Allow; confirm the OS prompt in a rebuilt Android/iOS binary; choose either result; verify roster identity/color/name/preview; tap Make an ally and verify the welcome screen.
- Commands:
  - `bun test apps/mobile/src/features/onboarding`
  - `bun --filter mobile lint`
  - `bun --filter mobile typecheck`
  - `bunx expo config --type public --json`
  - `git diff --check`

## Risks and Mitigations

- Risk: Adding `expo-notifications` changes the native dependency graph and cannot be delivered by OTA alone. Mitigation: Keep the change isolated, validate Expo config, and require a new compatible binary before device testing.
- Risk: Permission APIs may reject on an unsupported runtime or an already-denied device. Mitigation: Always continue to the roster and never display a false granted state.
- Risk: The local roster could become a second long-term data model. Mitigation: Display only the flow-owned completed Ally and document replacement by the durable Cloud collection.
- Risk: The old shimmer abstraction becomes unused after visual rollback. Mitigation: Remove only its notification-specific export/import and preserve the existing `ShinyText` thinking effect.
- Rollback: Remove the native adapter/plugin and roster branch, restore `notifications` as the terminal step, and keep the existing onboarding screens intact.
