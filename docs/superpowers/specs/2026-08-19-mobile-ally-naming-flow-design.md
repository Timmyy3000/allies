# Mobile Ally Naming Flow Design

**Date:** 2026-08-19  
**Status:** Awaiting user review  
**Scope:** Mobile onboarding naming screen and temporary next-step placeholder

## Goal

Add the onboarding screen where a user names their first Ally, connect it to the
existing “Make your first ally” screen, and provide a temporary screen for the
future Ally-color selection step.

The flow must stay small and local for now. It must not add API calls,
persistence, a global theme system, or unrelated navigation work.

## Flow and state

The existing onboarding entry screen will render a local `OnboardingFlow` that
owns three pieces of state:

- `step`: `welcome | name | colorPlaceholder`
- `allyName`: the current name input
- `accentColor`: the onboarding accent, initially `#FF5800`

The visible progress is derived from `step`, rather than incremented and
decremented independently:

- `welcome`: no progress ring is shown
- `name`: empty ring
- `colorPlaceholder`: one partial fill segment

Returning with the back button changes `step` to the previous value, so the
ring automatically loses the fill associated with the later step. The selected
`accentColor` remains in memory when moving backward.

The future color picker will update `accentColor` when a color is selected. The
current placeholder does not select a color yet; it simply reserves the flow
boundary and state shape for that screen.

## Screen design

### Name screen

- White full-screen background.
- Top-left back control: a `40px × 40px` circle with `#F3F3F3` fill and the
  supplied `8px × 14px` chevron asset centered inside it.
- Heading below the back control with a `24px` vertical gap:
  “What do you want to name your ally?”
- Heading uses the available Open Runde semibold face as the closest local
  match to the requested 700 weight, at `24px`, `24px` line height, and `-1px`
  letter spacing.
- Progress ring at the top-right. Its track is light gray; its filled stroke
  uses the current `accentColor`.
- Centered controlled text input with placeholder “give it a name”. Both
  placeholder and typed text use `28px` Open Runde semibold, `28px` line height,
  `-1px` letter spacing, and centered alignment.
- Placeholder text uses `#D9D9D9`. Typed text uses `accentColor`.
- Bottom button is the existing reusable wide button. It sits `50px` above the
  physical bottom edge, has white text, starts with `#D9D9D9`, and becomes
  `accentColor` when the trimmed name contains at least one character.
- Pressing `Next` stores the trimmed name and moves to `colorPlaceholder`.

### Color placeholder screen

- Uses the same header/back/progress treatment.
- Displays a minimal centered “Color selection coming next” placeholder.
- Keeps the name in memory and uses the current `accentColor` for dynamic
  accents.
- Its back control returns to the name screen and therefore restores the empty
  progress ring.

### Brand-color boundary

The central Allies logo remains fixed orange (`#FF5800`) throughout onboarding.
It is brand artwork, not part of the dynamic Ally accent system.

Dynamic onboarding accents are driven by `accentColor`, including buttons,
progress-ring fills, typed Ally-name text, sign-in/accent text, and future color
selection indicators.

## Implementation boundary

Use one flow component and small presentational screen components. Pass
`accentColor`, callbacks, and the current name through props. Do not introduce a
store, backend model, or router route for the placeholder.

The reusable button needs only the smallest extension required to render a
disabled gray state and the active accent color. Existing callers that do not
provide an accent continue using the current orange behavior.

The supplied chevron will be copied into the mobile Allies asset directory. The
progress ring will use the already-installed `react-native-svg`; its fill can
animate briefly on step changes, while reduced-motion users receive the final
state immediately.

## Validation

Add focused tests for:

1. A blank or whitespace-only name keeps `Next` unavailable.
2. A non-empty trimmed name enables `Next` and advances to the placeholder.
3. Progress is empty on the name step and partially filled on the placeholder.
4. Going back returns to the name step with empty progress.
5. A selected accent color is used by dynamic UI while the logo remains orange.

Run the relevant mobile tests, `bun run lint:mobile`,
`bun --filter mobile typecheck`, and `git diff --check`.

## Non-goals

- Implementing the actual Ally color picker.
- Saving the Ally name or color to Cloud.
- Recoloring the Allies logo.
- Adding the later onboarding screens beyond the placeholder.
- Refactoring unrelated onboarding motion or assets.
