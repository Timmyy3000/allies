# Mobile Ally Naming Flow Plan

**Goal:** Add the Ally naming step after the existing welcome screen, carry the future selectable accent color through onboarding, and expose a temporary color-selection step without adding backend or global state.

**Architecture:** A local `OnboardingFlow` owns the current step, Ally name, and dynamic accent color. Presentational screens receive those values through props; progress is derived from the step so back navigation cannot leave stale fill behind. The fixed central Allies logo remains orange and is not part of the dynamic accent system.

**Tech Stack:** Expo SDK 57, React Native, TypeScript, Expo Router entry, `expo-image`, `react-native-svg`, `react-native-reanimated`, Vitest, Bun.

## Global Constraints

- Keep the implementation local to `apps/mobile`; do not add API calls, persistence, or a global theme/store.
- Use the existing Open Runde font assets and `PrimaryButton` component.
- Preserve the central Allies logo as `#FF5800`.
- Use `#FF5800` as the initial onboarding accent and replace only dynamic accents after a future color selection.
- Treat whitespace-only Ally names as empty; the active button requires at least one trimmed character.
- Respect safe-area insets and the existing portrait mobile layout.
- Keep the provided `back-chevron-icon.svg` as the source asset.
- Do not overwrite or stage unrelated dirty changes from the other agents.
- Branch and commit subjects for mobile work use the `mobile:` prefix.
- Because the execution checkout contains uncommitted user/agent files, do not
  make task-level commits that include overlapping existing files; use a
  feature handoff diff and commit after the shared baseline is checkpointed.

## Feature Overview

- **Problem:** The current onboarding CTA has no name-entry step, and future color selection needs a single accent boundary instead of hard-coded orange values scattered across screens.
- **Target users:** New mobile users creating their first Ally.
- **Source docs/specs:** `docs/superpowers/specs/2026-08-19-mobile-ally-naming-flow-design.md`, `apps/mobile/AGENTS.md`, `ENGINEERING_STYLE.md`, and the supplied screen references.
- **Success outcome:** A user can enter a non-empty Ally name, continue to a visible future color-step placeholder, return with progress reset correctly, and later selected accent colors have one clear flow-level home.

## User Stories

1. As a new user, I want to name my Ally after tapping “Make your first ally”, so that the next onboarding step can use that name.
2. As a new user, I want the disabled Next button and empty progress ring to communicate that I have not completed the name step.
3. As a new user, I want to go back without stale progress, so that the screen accurately reflects the current onboarding step.
4. As a new user, I want my later Ally color choice to recolor dynamic onboarding accents while the central Allies logo remains the brand orange.

## Scope

### In Scope

- Local `welcome -> name -> colorPreview` flow state.
- Controlled Ally-name input with the requested typography and colors.
- Reusable back header, progress ring, and temporary color-step screen.
- Dynamic accent support in `PrimaryButton` and the existing welcome screen.
- Supplied back-chevron asset copied into the mobile Allies assets.
- Focused pure-state tests, mobile lint/typecheck, and manual device checks.

### Out of Scope

- The actual Ally color picker UI.
- Cloud/API integration or durable Ally creation.
- Recoloring the central Allies logo.
- New account, sign-in, or authenticated navigation behavior.
- Changes to the existing Ally motion implementation or assets.

### Dependencies and Assumptions

- `react-native-svg` and `react-native-reanimated` are already installed and configured in the mobile app.
- `expo-image` can render the supplied local SVG asset; if the native build rejects the SVG import, use the same path data in a small `react-native-svg` component while retaining the supplied SVG as the source asset.
- The current dirty onboarding work is user-owned and must remain intact.
- The future color picker will call the flow’s accent-color setter; this plan only establishes that seam.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/features/onboarding/onboarding-state.ts` | `isAllyNameReady` | `isAllyNameReady(value: string): boolean` | Accept any string; trim before checking length | `true` only when the trimmed value is non-empty | Pure; no I/O |
| `apps/mobile/src/features/onboarding/onboarding-state.ts` | `getOnboardingProgress` | `getOnboardingProgress(step: OnboardingStep): number` | `step` is `welcome`, `name`, or `colorPreview` | `0`, `0`, or `1 / 3` respectively | Pure; progress is derived, never mutated independently |
| `apps/mobile/src/features/onboarding/onboarding-state.ts` | `getPreviousOnboardingStep` | `getPreviousOnboardingStep(step: OnboardingStep): OnboardingStep` | `welcome` stays at `welcome`; later steps move one step backward | Previous flow step | Pure; prevents stale progress |
| `apps/mobile/src/features/onboarding/onboarding-header.tsx` | `OnboardingHeader` | `OnboardingHeader(props: OnboardingHeaderProps): JSX.Element` | Title, back callback, progress, and accent color | Header with accessible back control and progress ring | Calls `onBack` only on user press |
| `apps/mobile/src/features/onboarding/ally-name-screen.tsx` | `AllyNameScreen` | `AllyNameScreen(props: AllyNameScreenProps): JSX.Element` | Controlled name value, change callback, next/back callbacks, accent color | Name-entry screen | No persistence; next callback only receives valid flow state |

### API and Transport Contracts

Not applicable. This feature has no API, transport, webhook, queue, or streaming changes.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `OnboardingStep` | `apps/mobile/src/features/onboarding/onboarding-state.ts` | `'welcome' \| 'name' \| 'colorPreview'` | Required; flow starts at `'welcome'` | Progress is derived from the current value | In-memory presentation state only |
| `OnboardingFlowState` | `apps/mobile/src/features/onboarding/onboarding-state.ts` | `step: OnboardingStep`; `allyName: string`; `accentColor: string` | `allyName` starts empty; `accentColor` defaults to `#FF5800` | `allyName` is trimmed on Next; logo never consumes `accentColor` | No persistence or backend migration |
| `OnboardingProgressProps` | `apps/mobile/src/features/onboarding/onboarding-progress.tsx` | `progress: number`; `accentColor: string`; optional `size?: number` | Progress clamped to `0..1`; size defaults to `40` | Track remains visible at empty state; filled stroke uses accent | Presentation-only |
| `PrimaryButtonProps` | `apps/mobile/src/components/ui/primary-button.tsx` | Existing props plus `accentColor?: string`; `bottomMargin?: number` | Accent defaults to `#FF5800`; bottom margin defaults to existing `24` | `disabled` renders `#D9D9D9` and blocks press | Existing callers retain current behavior |

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| Welcome CTA | `onStart(): void` | `welcome -> name` | None | Always available; existing welcome visuals stay intact |
| Name input | `onNameChange(value: string): void` | `name` remains active while input changes | None | Empty/whitespace value keeps Next disabled |
| Name Next | `onNext(): void` | `name -> colorPreview` only when `isAllyNameReady` is true | None | No network loading or error state |
| Name back | `onBack(): void` | `name -> welcome` | None | Progress ring disappears with the name screen |
| Color preview back | `onBack(): void` | `colorPreview -> name` | None | Progress becomes empty; typed name and selected accent remain in memory |
| Future color selection seam | `setAccentColor(color: string): void` | Any later step updates `accentColor`; current preview does not call it | None | Dynamic UI receives selected color; fixed logo remains orange |

## Phases

### Phase 1 - State and shared primitives

- **Goal:** Establish tested flow semantics and reusable accent-aware visual primitives without changing the existing screen composition.
- **Work items:** Add pure state helpers/tests; copy the chevron asset; create the header and progress ring; extend `PrimaryButton` with accent and disabled styling.
- **Impacted files/systems:** `apps/mobile/src/features/onboarding/`, `apps/mobile/src/components/ui/primary-button.tsx`, `apps/mobile/assets/allies/icons/back-chevron-icon.svg`.
- **Exit criteria:** Focused state tests pass; progress is derived from step; the button remains orange for existing callers and supports gray disabled plus custom accent states.

### Phase 2 - Flow screens and integration

- **Goal:** Make the name screen reachable and connect it to the future color step while preserving the orange logo.
- **Work items:** Add the name screen and color-step preview; update the welcome screen to accept dynamic accent text/button color; add `OnboardingFlow`; change `apps/mobile/src/app/index.tsx` to render it.
- **Impacted files/systems:** `apps/mobile/src/features/onboarding/`, `apps/mobile/src/app/index.tsx`, and the existing welcome screen.
- **Exit criteria:** CTA, input, Next, back, ring, safe-area spacing, and accessible labels work on mobile; all dynamic accents flow from `accentColor`; the logo stays orange.

### Phase 3 - Verification and handoff

- **Goal:** Verify visual behavior and prevent regressions without absorbing unrelated agent changes.
- **Work items:** Run focused tests, mobile lint/typecheck, diff checks, and manual Android verification at empty, typed, preview, and back states.
- **Impacted files/systems:** Mobile app runtime and the exact feature diff.
- **Exit criteria:** Required commands pass or pre-existing failures are clearly separated; screenshots/evidence cover the acceptance checklist.

## Acceptance Criteria

1. Tapping “Make your first ally” opens the naming screen.
2. The back control is `40px × 40px`, circular, uses `#F3F3F3`, and renders the supplied chevron.
3. The heading is below the back control with a `24px` gap and matches the requested Open Runde sizing and letter spacing.
4. The progress ring is empty on the naming screen and partially filled on the color-preview screen.
5. A whitespace-only name leaves Next disabled with `#D9D9D9`; a valid name makes it use the current accent color and allows navigation.
6. The name input is centered, uses the requested `28px` styling, and changes typed text to the current accent color.
7. The Next button is positioned `50px` above the physical bottom edge while respecting safe-area insets.
8. Going back from the color-preview screen restores the naming screen with an empty ring, preserving the in-memory name and accent color.
9. The current central Allies logo remains `#FF5800` regardless of accent color.
10. The current welcome screen’s dynamic accent text/button surfaces consume `accentColor` without changing the logo.
11. Relevant unit tests, `bun run lint:mobile`, `bun --filter mobile typecheck`, and `git diff --check` are recorded.

## Backend Considerations

Not applicable. The name and accent remain local presentation state until a separate product/API contract is approved.

## Frontend Considerations

### Data Path

- **User action entry:** Existing welcome CTA.
- **Client route/component:** `apps/mobile/src/app/index.tsx` -> `OnboardingFlow` -> `AllyNameScreen` / `OnboardingColorPreview`.
- **Client API route/proxy:** None.
- **Backend endpoint:** None.
- **Response -> UI model mapping:** None; local state only.
- **Error/loading/retry path:** Font loading remains a screen-level loading surface; name validation is synchronous and visible through button state.

### State Management Considerations

- **State ownership:** `OnboardingFlow` owns `step`, `allyName`, and `accentColor`.
- **Source of truth vs derived state:** `step` is authoritative; progress and button readiness are derived by pure helpers.
- **Caching/invalidation:** None.
- **Concurrency/dedupe:** None; no network actions exist in this slice.
- **Accessibility:** The icon-only back control has an accessible label; the input has an accessible label; disabled state is conveyed by both behavior and color.

## Test Plan

- **Unit tests:** Add `onboarding-state.test.ts` covering whitespace validation, progress mapping, previous-step mapping, and accent preservation as pure behavior.
- **Integration/API tests:** Not applicable.
- **Regression checks:** Existing onboarding character/motion tests plus mobile lint and typecheck.
- **Manual verification checklist:**
  - Launch welcome screen and tap the CTA.
  - Confirm chevron, circle, title, ring, input, and button align with the supplied reference.
  - Confirm empty input keeps Next gray and non-interactive.
  - Type one character; confirm text and button use `#FF5800`.
  - Tap Next; confirm the temporary color step and partial ring.
  - Tap back; confirm empty ring and preserved name.
  - Confirm the central logo remains orange throughout.
  - Test a device with a bottom safe-area inset.
- **Commands:**
  - `bun test apps/mobile/src/features/onboarding/onboarding-state.test.ts`
  - `bun run lint:mobile`
  - `bun --filter mobile typecheck`
  - `git diff --check`

## Risks and Mitigations

- **Risk:** The current branch contains other agents’ uncommitted onboarding work. **Mitigation:** Use an isolated execution workspace and stage only this feature’s files; never reset or clean the shared checkout.
- **Risk:** A local SVG import could differ across native platforms. **Mitigation:** Use Expo Image’s local SVG support first; verify Android and web, with an inline `react-native-svg` fallback only if the build requires it.
- **Risk:** Hard-coded accent values remain in the welcome screen. **Mitigation:** Route all dynamic button/text accents through `accentColor`; keep only the central logo’s orange constant.
- **Risk:** Keyboard or safe-area changes shift the centered input/button. **Mitigation:** Use flex layout, `SafeAreaView`, explicit input hit area, and manual device checks rather than measuring layout in JavaScript.

## Implementation Tasks

### Task 1: Add tested onboarding state helpers

**Files:**

- Create: `apps/mobile/src/features/onboarding/onboarding-state.ts`
- Test: `apps/mobile/src/features/onboarding/onboarding-state.test.ts`

**Interfaces:**

- Produces `OnboardingStep`, `DEFAULT_ONBOARDING_ACCENT`, `isAllyNameReady`, `getOnboardingProgress`, and `getPreviousOnboardingStep` for the flow and screens.

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from 'vitest';

import {
  getOnboardingProgress,
  getPreviousOnboardingStep,
  isAllyNameReady,
} from './onboarding-state';

describe('onboarding state', () => {
  it('rejects blank and whitespace-only Ally names', () => {
    expect(isAllyNameReady('')).toBe(false);
    expect(isAllyNameReady('   ')).toBe(false);
  });

  it('accepts a name containing at least one non-whitespace character', () => {
    expect(isAllyNameReady(' Sally ')).toBe(true);
  });

  it('derives progress from the current step', () => {
    expect(getOnboardingProgress('welcome')).toBe(0);
    expect(getOnboardingProgress('name')).toBe(0);
    expect(getOnboardingProgress('colorPreview')).toBe(1 / 3);
  });

  it('moves one step backward without storing progress separately', () => {
    expect(getPreviousOnboardingStep('colorPreview')).toBe('name');
    expect(getPreviousOnboardingStep('name')).toBe('welcome');
    expect(getPreviousOnboardingStep('welcome')).toBe('welcome');
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails for the missing module**

Run: `bun test apps/mobile/src/features/onboarding/onboarding-state.test.ts`

Expected: FAIL because `./onboarding-state` does not exist yet.

- [ ] **Step 3: Add the minimal pure implementation**

```ts
export type OnboardingStep = 'welcome' | 'name' | 'colorPreview';

export const DEFAULT_ONBOARDING_ACCENT = '#FF5800';

export function isAllyNameReady(value: string): boolean {
  return value.trim().length > 0;
}

export function getOnboardingProgress(step: OnboardingStep): number {
  return step === 'colorPreview' ? 1 / 3 : 0;
}

export function getPreviousOnboardingStep(step: OnboardingStep): OnboardingStep {
  if (step === 'colorPreview') return 'name';
  if (step === 'name') return 'welcome';
  return 'welcome';
}
```

- [ ] **Step 4: Re-run the focused test**

Run: `bun test apps/mobile/src/features/onboarding/onboarding-state.test.ts`

Expected: 4 tests pass with 0 failures.

- [ ] **Step 5: Record the isolated state slice without staging shared files**

Keep the new state files in the working tree for the coordinator’s final
feature commit. Do not stage or commit the shared checkout while the other
agent’s onboarding files remain uncommitted.

### Task 2: Add the shared header, progress ring, and supplied asset

**Files:**

- Create: `apps/mobile/assets/allies/icons/back-chevron-icon.svg`
- Create: `apps/mobile/src/features/onboarding/onboarding-progress.tsx`
- Create: `apps/mobile/src/features/onboarding/onboarding-header.tsx`

**Interfaces:**

- `OnboardingProgress({ progress, accentColor, size = 40 })` renders a gray track plus a clamped accent stroke.
- `OnboardingHeader({ title, progress, accentColor, onBack })` renders the accessible `40px` back control, title, and progress ring.

- [ ] **Step 1: Copy the exact provided SVG without changing its path or stroke**

Copy `C:/Users/ASUS/Downloads/back-chevron-icon.svg` to `apps/mobile/assets/allies/icons/back-chevron-icon.svg` and verify it retains the `8 × 14` viewBox and `#212121` stroke.

- [ ] **Step 2: Implement the progress ring with explicit SVG primitives**

Use two `Circle` elements from `react-native-svg` with a `40px` default box, `4px` stroke width, a light-gray background track, and a rotated accent arc. Clamp `progress` to `0..1`; use `strokeDasharray` and `strokeDashoffset` so an empty ring remains visibly present. Animate only the arc’s stroke offset with a short `withTiming` transition and use the reduced-motion value immediately.

- [ ] **Step 3: Implement the shared header**

Use `expo-image` with `require('@/assets/allies/icons/back-chevron-icon.svg')` inside a `40px` circular `Pressable`. Give it `accessibilityRole="button"` and `accessibilityLabel="Go back"`. Place the title `24px` below the button and keep the progress ring in the top-right.

- [ ] **Step 4: Run typecheck after the primitive changes**

Run: `bun --filter mobile typecheck`

Expected: no new errors attributable to the header, ring, or asset.

- [ ] **Step 5: Record the shared primitives without staging unrelated files**

Keep the new asset and primitive files in the working tree. Do not stage or
commit the shared checkout until the other agent’s baseline is checkpointed.

### Task 3: Make the reusable button and welcome screen accent-aware

**Files:**

- Modify: `apps/mobile/src/components/ui/primary-button.tsx`
- Modify: `apps/mobile/src/features/onboarding/onboarding-screen.tsx`

**Interfaces:**

- Add optional `accentColor?: string` and `bottomMargin?: number` to `PrimaryButtonProps`; preserve the current orange/24px defaults.
- Add optional `accentColor?: string` to `OnboardingScreenProps`; preserve `#FF5800` when omitted.

- [ ] **Step 1: Add the disabled/accent behavior**

Destructure `accentColor`, `bottomMargin`, and `disabled` before spreading the remaining Pressable props. Use `#D9D9D9` when disabled, otherwise the supplied accent or `#FF5800`; keep the label white and suppress the pressed transform when disabled.

- [ ] **Step 2: Thread the accent through the welcome screen**

Pass `accentColor` into the welcome `PrimaryButton` and use it for the sign-in accent text. Do not pass it to `AlliesLogo`; the logo must remain orange.

- [ ] **Step 3: Run the existing onboarding test and typecheck**

Run: `bun test apps/mobile/src/features/onboarding/onboarding-characters.test.ts`

Expected: existing motion/identity assertions pass.

Run: `bun --filter mobile typecheck`

Expected: no new errors from the button or welcome screen changes.

- [ ] **Step 4: Record the accent-aware shared UI without staging the shared base**

The button and welcome screen are currently uncommitted shared files. Leave
them unstaged and include their exact feature diff in the final handoff.

### Task 4: Build the name screen, color preview, and local flow

**Files:**

- Create: `apps/mobile/src/features/onboarding/ally-name-screen.tsx`
- Create: `apps/mobile/src/features/onboarding/onboarding-color-preview.tsx`
- Create: `apps/mobile/src/features/onboarding/onboarding-flow.tsx`
- Modify: `apps/mobile/src/app/index.tsx`

**Interfaces:**

- `AllyNameScreen({ allyName, accentColor, onNameChange, onNext, onBack })`.
- `OnboardingColorPreview({ accentColor, allyName, onBack })`.
- `OnboardingFlow()` owns `step`, `allyName`, and `accentColor`, and renders the correct screen.

- [ ] **Step 1: Implement the controlled name screen**

Use `SafeAreaView` and flex layout. Render the shared header with the name title and empty progress. Render a centered `TextInput` with `placeholder="give it a name"`, `accessibilityLabel="Ally name"`, `textAlign="center"`, `fontSize: 28`, `lineHeight: 28`, `letterSpacing: -1`, and `color: accentColor`. Render `PrimaryButton` with `disabled={!isAllyNameReady(allyName)}`, `accentColor`, `bottomMargin={0}`, and footer padding that leaves the button `50px` above the physical bottom after safe-area compensation.

- [ ] **Step 2: Implement the color-preview screen**

Render the shared header with `getOnboardingProgress('colorPreview')` and a short centered message that makes the future color-selection step explicit. Keep the `allyName` available to the component boundary even though the preview does not display it yet. Back calls the flow callback.

- [ ] **Step 3: Implement the local flow controller**

Initialize:

```ts
const [step, setStep] = useState<OnboardingStep>('welcome');
const [allyName, setAllyName] = useState('');
const [accentColor, setAccentColor] = useState(DEFAULT_ONBOARDING_ACCENT);
```

Render `OnboardingScreen` for `welcome`; on start set `step` to `name`. Render `AllyNameScreen` for `name`; on Next trim the name and set `step` to `colorPreview`. Render `OnboardingColorPreview` for `colorPreview`; on back use `getPreviousOnboardingStep(step)`. Keep `accentColor` unchanged on back.

- [ ] **Step 4: Move font loading to the flow boundary**

Load the two existing Open Runde font assets once in `OnboardingFlow` and show the existing white loading surface until they are ready. Remove the duplicate font-loading hook and loading guard from `OnboardingScreen` after the flow owns font readiness; do not change the font asset files.

- [ ] **Step 5: Change the app entry to render the flow**

Replace the `OnboardingScreen` import/render in `apps/mobile/src/app/index.tsx` with `OnboardingFlow`. Keep the existing root Stack/provider setup unchanged.

- [ ] **Step 6: Run the focused state and existing onboarding tests**

Run:

```bash
bun test apps/mobile/src/features/onboarding/onboarding-state.test.ts apps/mobile/src/features/onboarding/onboarding-characters.test.ts
```

Expected: all focused state and motion tests pass.

- [ ] **Step 7: Record the flow implementation without staging the shared entry file**

The app entry is already modified by the shared onboarding work. Leave it
unstaged and include the exact feature diff in the final handoff.

### Task 5: Verify the complete feature and hand off evidence

**Files:**

- Inspect only: all feature files listed above and the exact feature diff.

- [ ] **Step 1: Run the complete relevant checks**

```bash
bun run lint:mobile
bun --filter mobile typecheck
git diff --check
```

Expected: each command exits `0`. If a pre-existing unresolved import or unrelated agent change fails, record the exact file and output instead of claiming a clean baseline.

- [ ] **Step 2: Perform manual Android verification**

Verify the welcome CTA, name screen layout, disabled/active button states, typed accent text, empty/partial ring states, back behavior, safe-area bottom spacing, accessible labels, and the fixed orange central logo.

- [ ] **Step 3: Review the exact diff and status**

Run:

```bash
git status --short
git diff --stat HEAD~4..HEAD
git diff --check HEAD~4..HEAD
```

Confirm the feature paths and the pre-existing user/agent changes are present;
do not reset, clean, or amend another agent’s work. Do not claim a commit until
the shared baseline has been checkpointed by the coordinator.

- [ ] **Step 4: Prepare the handoff**

Return the required evidence:

```markdown
## Handoff
- Ticket: mobile ally naming flow
- Result: completed, blocked, or review needed
- Changed areas: exact files
- Validation: exact commands and outcomes
- Evidence: screenshots/manual states
- Decisions discovered: accent-color and logo boundary
- Follow-ups: actual color picker remains
- Blockers: exact unresolved failures, if any
```

## Review Notes

The design emphasizes clear hierarchy, deliberate alignment, safe-area respect, accessible icon labels, explicit form states, and limited animation. These choices follow the repository’s requirement to use the Vercel interface/design guidance as a quality reference while preserving Allies’ own orange, Open Runde typography, and supplied visual assets.
