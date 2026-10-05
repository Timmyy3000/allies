# Mobile dark mode Plan

## Feature Overview

- Problem: Current mobile screens use fixed light colors, so the interface does
  not follow the device appearance setting.
- Target users: Allies mobile users who use light or dark device mode.
- Source docs/specs: `docs/superpowers/specs/2026-09-03-mobile-dark-mode-design.md`,
  `ENGINEERING_STYLE.md`, and the Allies mobile interface notes in Nabu.
- Success outcome: The current mobile routes keep their existing hierarchy and
  selected Ally accent colors while all specified surfaces, text, controls, and
  status-bar icons follow the device mode.

## Plan Hygiene and Evidence Boundaries

This plan contains repository-relative paths only. It introduces no API,
database, provider, account, or private operational contract.

## User Stories

1. As a mobile user, I want the app to follow my device appearance, so that it
   feels consistent with the rest of my device.
2. As a mobile user, I want active actions to retain the selected Ally color,
   so that color selection still has meaning in dark mode.
3. As a maintainer, I want shared semantic theme tokens, so that future screens
   do not add separate light and dark color branches.

Before implementation, capture a complete `git status --porcelain=v1
--untracked-files=all` snapshot in a local, uncommitted review note. Also
record hashes or diffs for pre-existing out-of-scope tracked files. After
implementation, compare the complete status snapshot and those hashes so that
new untracked paths and edits within already-dirty files are both visible.

## Scope

### In Scope

- Extend the existing `Colors` and `useTheme` boundary.
- Apply the theme to the current mobile routes and shared UI components.
- Keep enabled buttons on the current selected Ally accent.
- Use `#202020` for disabled or otherwise inactive button backgrounds in dark
  mode.
- Theme onboarding inputs, chat composers, modal surfaces, controls, text, and
  monochrome icons.
- Make the single root status bar follow the device mode.
- Add a small theme contract test and update affected behavior tests.

### Out of Scope

- Manual theme selection.
- New theme providers, styling libraries, or dependencies.
- Changes to Ally artwork, Ally colors, logos, provider logos, navigation,
  authentication, persistence, APIs, or splash-screen artwork.
- Restoring routes deleted by parallel work.
- Updating unrelated dirty files.

### Dependencies and Assumptions

- `userInterfaceStyle: automatic` is already configured in `apps/mobile/app.json`.
- React Native's existing `useColorScheme` hook remains reactive to device
  appearance changes.
- `expo-image` supports runtime `tintColor` for the existing monochrome SVG
  assets.
- The current worktree contains parallel uncommitted changes. Only the files
  listed in this plan are edited, and unrelated changes are preserved.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/constants/theme.ts` | `Colors` | `const Colors: Record<'light' \| 'dark', Theme>` | Exact light and dark semantic color values | Theme maps for both schemes | No side effects |
| `apps/mobile/src/constants/theme.ts` | `getTheme` | `function getTheme(scheme: ColorSchemeName): Theme` | `dark` selects dark; every other value selects light | One normalized theme map | No side effects |
| `apps/mobile/src/hooks/use-theme.ts` | `useTheme` | `function useTheme(): Theme` | Reads the existing device color-scheme hook | Current reactive theme map | Re-renders when the device scheme changes |
| `apps/mobile/src/components/ui/primary-button.tsx` | `PrimaryButton` | `PrimaryButtonProps` | Enabled buttons use `accentColor`; disabled buttons use the inactive theme color | Reusable pressable button | Keeps existing accent-color animation and disabled behavior |

### API and Transport Contracts

Not applicable. This is a local presentation change with no API or transport
change.

### Schema and Data Shapes

Not applicable. No persisted, cached, backend, or third-party data shape
changes.

### Frontend Interaction Shapes (if applicable)

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Device appearance | `useTheme(): Theme` | `light \| dark`; `unspecified` falls back to `light` | Device scheme -> theme tokens | No loading or permission state; existing screen state is preserved |
| Enabled action | `PrimaryButton` | Existing enabled/disabled state | Selected Ally accent -> animated background | Existing disabled behavior remains |

The theme update does not change loading, error, empty, permission, or retry
states. It only changes the derived colors used by the existing state.

## Phases

### Phase 1 - Theme contract and shared controls

- Goal: Establish one small, tested theme boundary and update shared controls.
- Work items:
  - Extend `Colors` with semantic tokens for app background, primary and
    supporting text, controls, onboarding inputs, chat input, modal, inactive
    buttons, progress track, and modal icons.
  - Add `getTheme` for the `dark`/light fallback and keep `useTheme` reactive.
  - Update the root layout to own the dynamic status bar.
  - Update `PrimaryButton` so every enabled action preserves the selected Ally
    accent and disabled actions use the themed inactive surface.
  - Update the shared bottom sheet and onboarding progress track.
  - Add `apps/mobile/src/constants/theme.test.ts` and update the existing
    button/layout tests where their ownership changes.
- Impacted files/systems:
  - `apps/mobile/src/constants/theme.ts`
  - `apps/mobile/src/constants/theme.test.ts`
  - `apps/mobile/src/hooks/use-theme.ts`
  - `apps/mobile/src/app/_layout.tsx`
  - `apps/mobile/src/components/ui/primary-button.tsx`
  - `apps/mobile/src/components/ui/bottom-sheet-modal.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-motion.ts`
  - `apps/mobile/src/features/onboarding/onboarding-motion.test.ts`
  - `apps/mobile/src/features/onboarding/onboarding-layout.ts`
  - `apps/mobile/src/features/onboarding/onboarding-layout.test.ts`
- Exit criteria: Exact token and button behavior tests pass, and no screen-level
  fixed status bar remains.

### Phase 2 - Apply tokens to current screens

- Goal: Remove fixed light-only presentation values from the current mobile
  routes without changing product behavior.
- Work items:
  - Theme welcome, onboarding shell/header/name/look/job/personality screens.
  - Theme preview conversation, account modal, post-setup, Allies list, sign-in,
    missing-Ally state, and mock Ally conversation.
  - Pass the current accent into `OnboardingAlliesScreen`; keep orange as its
    default when no selected Ally color exists.
  - Pass theme colors to existing monochrome back, search, settings, and X
    icons without duplicating assets.
  - Pass the selected Ally accent to the notification “I’ll do this later”
    action; it is enabled and therefore remains accent-colored.
  - Preserve selected Ally accents for active buttons, progress, links, swatches,
    send controls, and accent-derived personality controls.
  - Preserve supporting grey text and the account modal privacy/terms treatment.
- Impacted files/systems:
  - `apps/mobile/src/features/onboarding/onboarding-screen.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-shell.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-header.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-progress.tsx`
  - `apps/mobile/src/features/onboarding/ally-name-screen.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-look-screen.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-job-screen.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-personality-screen.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-preview-screen.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-post-setup.tsx`
  - `apps/mobile/src/features/onboarding/onboarding-allies-screen.tsx`
  - `apps/mobile/src/features/mock/mock-conversation-screen.tsx`
  - `apps/mobile/src/app/sign-in.tsx`
  - `apps/mobile/src/app/allies/[allyId]/index.tsx`
- Exit criteria: All current routes render with equivalent light-mode hierarchy,
  specified dark-mode values, accent-aware active actions, and readable status
  bar/icon colors.

## Acceptance Criteria

1. Device light and dark appearance changes update the current screen through
   the existing color-scheme hook; unspecified mode uses the light theme.
2. Dark mode uses `#000000` for the app background, `#161616` for onboarding
   inputs/back controls/modal surfaces, `#121212` for the chat input, and
   `#202020` for inactive or disabled buttons.
3. Every enabled button uses the selected Ally accent; the default accent remains
   Allies orange.
4. Welcome copy uses white text in dark mode and the Sign in link remains the
   current Ally accent.
5. Modal cancel controls use a white background and a `#121212` X in dark mode.
6. Google and ChatGPT option labels are white in dark mode, while the account
   modal privacy/terms text remains unchanged.
7. Back, search, settings, and modal-close icons have sufficient contrast in
   both modes without duplicate assets.
8. Only one root status bar controls icon appearance, with light icons in dark
   mode and dark icons in light mode.
9. Ally artwork, logos, provider logos, and selected Ally color behavior are
   unchanged.
10. Targeted tests, full mobile tests, mobile typecheck, lint, bundle/export,
    and `git diff --check` pass.

## Backend Considerations (if applicable)

Not applicable. No backend, API, query, migration, authorization, retry, or
idempotency behavior changes.

### Query Optimization Plan

Not applicable.

### N+1 Prevention

Not applicable.

### Detailed Unit Test Cases

Not applicable to backend behavior.

## Frontend Considerations (if applicable)

### Data Path

- User action entry: Device appearance setting or an existing screen action.
- Client route/component: Current Expo Router screens and shared UI.
- Client API route/proxy: Not applicable.
- Backend endpoint: Not applicable.
- Response -> UI model mapping: Device color scheme -> normalized `Theme` map.
- Error/loading/retry path: No new asynchronous path; existing screen state is
  preserved during theme updates.

### State Management Considerations

- State ownership by layer: React Native owns device scheme; `useTheme` owns
  normalization; screens consume derived tokens; onboarding flow still owns
  selected Ally color.
- Source of truth vs derived state: Device scheme and onboarding accent remain
  authoritative. Theme tokens and button colors are derived values.
- Caching/invalidation approach: No cache. The existing color-scheme hook
  triggers normal React updates.
- Concurrency and dedupe handling: No network or concurrent state change.

## Test Plan

- Unit tests: Exact light/dark theme tokens, unspecified fallback, active accent
  preservation, disabled/inactive button colors, and existing layout behavior.
- Integration/API tests: Not applicable.
- Regression checks: Existing onboarding, preview, mock, modal, and cloud-client
  tests must continue to pass.
- Manual verification checklist:
  - Review welcome, sign-in, name, look, job, and personality screens in both
    device modes.
  - Review coming-alive, preview conversation, account modal, post-setup,
    notifications, Allies list, missing-Ally, and Ally conversation screens.
  - Change device appearance while a screen is mounted and confirm immediate
    surface and status-bar changes.
  - Select a non-orange Ally color and confirm active buttons, progress, send
    controls, and Sign in retain that accent.
  - Confirm disabled or otherwise inactive buttons use `#202020` in dark mode.
  - Confirm the modal cancel button is white with a dark X and privacy/terms text
    is unchanged.
- Commands:
  - `bun run test:run -- apps/mobile/src/constants/theme.test.ts apps/mobile/src/features/onboarding/onboarding-motion.test.ts apps/mobile/src/features/onboarding/onboarding-layout.test.ts`
  - `bun --filter mobile typecheck`
  - `bun run lint:mobile`
  - `bun run test:run`
  - `bun run bundle:mobile`
  - `git diff --check`

## Risks and Mitigations

- Risk: Fixed screen-level status-bar components can override the root mode.
  Mitigation: Remove the fixed screen-level components and keep one root owner.
- Risk: Active Ally colors could be replaced by generic dark button colors.
  Mitigation: Keep `accentColor` as the source for every enabled action,
  including secondary actions, and test a non-orange accent.
- Risk: The dirty worktree contains parallel edits in the same screens.
  Mitigation: Patch the current files in place, avoid whole-file rewrites, and
  inspect the final diff by exact path.
- Risk: Runtime SVG tinting could vary by platform.
  Mitigation: Require a runtime check of every tinted icon on an Android
  emulator/device and an iOS simulator/device. If tinting fails, replace only
  that icon with a small inline `react-native-svg` component using a color prop;
  do not duplicate assets.

- Risk: The dirty worktree can hide unapproved path changes.
  Mitigation: Record the complete porcelain status including untracked files
  before coding, preserve hashes or diffs for pre-existing out-of-scope tracked
  files, compare both snapshots after coding, and stage only exact files or
  hunks.
- Risk: Supporting grey text may become too weak on black.
  Mitigation: Keep primary copy white and review supporting text against both
  themes during manual verification.
- Rollback/fallback: Revert only the focused dark-mode commit(s) or restore the
  previous token values; no persisted data or native schema changes are made.
