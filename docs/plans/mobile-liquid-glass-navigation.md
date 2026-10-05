# Mobile Liquid Glass and Home Navigation Pill Implementation Plan

> **For agentic workers:** This plan is executed inline in the current task. Follow the repository and mobile AGENTS.md rules.

**Goal:** Implement iOS liquid glass materials for the back button and introduce a floating navigation pill on the Allies home screen containing three controls (Allies, Routines, and Make an Ally) with an Android fallback to muted button surfaces (`theme.controlSurface`).

**Architecture:** Create a reusable `GlassSurface` component leveraging the installed `expo-glass-effect` package (`GlassView`) on iOS, falling back on Android/web to a styled surface using the established `theme.controlSurface` token. Integrate `GlassSurface` into the mobile back button and build a floating bottom navigation pill in `OnboardingAlliesScreen` that consolidates top tabs and the create-Ally action.

**Tech Stack:** Expo SDK 57, React Native 0.86, TypeScript, `expo-glass-effect`, React Native Reanimated, React Native Safe Area Context, Vitest, Bun.

## Global Constraints

- Use the already-installed `expo-glass-effect` (~57.0.1) package; do not install new dependencies.
- On iOS, render native liquid glass via `GlassView`.
- On Android and Web, fall back to a container with `backgroundColor: theme.controlSurface` (`#F3F3F3` in light mode, `#161616` in dark mode).
- Keep the design responsive across device sizes and safe-area insets.
- Do not disturb existing authentication, session management, or routing contracts.

## Feature Overview

- **Problem:**
  1. Controls like the back button use flat solid background colors and lack the premium native iOS liquid glass material feel.
  2. The Allies Home screen currently has top tabs (`My allies`, `Routines`) and a separate bottom "Make an ally" button, creating visual clutter and fragmented navigation.
- **Target users:** Allies mobile users on iOS and Android.
- **Success outcome:**
  1. The back button uses iOS liquid glass on Apple devices and clean muted surface styling on Android.
  2. The Allies home screen features a unified, floating liquid glass navigation pill containing `Allies`, `Routines`, and `Make an Ally`.
  3. Seamless light and dark mode support across all affected surfaces.

## User Stories

1. As an iOS user, I want controls like the back button and the home navigation pill to feature native liquid glass materials, so that the app feels deeply integrated with modern iOS aesthetics.
2. As an Android user, I want the navigation pill and back button to have a consistent muted surface background, so that controls remain clear, tactile, and theme-adaptive.
3. As a mobile user on the Allies home screen, I want a single unified navigation pill to switch between Allies and Routines and easily trigger "Make an Ally", so that the screen is clean and accessible.

## Scope

### In Scope

- Create `GlassSurface` in `apps/mobile/src/components/ui/glass-surface.tsx`.
- Update `OnboardingHeader` and `MockConversationScreen` back buttons to use `GlassSurface`.
- Create `HomeNavigationPill` in `apps/mobile/src/features/onboarding/home-navigation-pill.tsx`.
- Update `OnboardingAlliesScreen` to replace the top tabs and bottom button with the floating navigation pill.
- Provide a clean placeholder state for the `Routines` tab.
- Add unit tests for `GlassSurface` and `HomeNavigationPill`.
- Validate via `bun run typecheck:mobile`, `bun run lint:mobile`, and `bun run test:run`.

### Out of Scope

- Remote push notification delivery or settings sync.
- Backend Cloud API changes or database migrations.
- New third-party styling or blur dependencies.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/components/ui/glass-surface.tsx` | `GlassSurface` | `function GlassSurface(props: GlassSurfaceProps): JSX.Element` | `children`, `style`, `glassEffectStyle`, `fallbackColor` | React Element | None |
| `apps/mobile/src/features/onboarding/home-navigation-pill.tsx` | `HomeNavigationPill` | `function HomeNavigationPill(props: HomeNavigationPillProps): JSX.Element` | `activeTab`, `onTabChange`, `onCreateAlly`, `accentColor` | React Element | User interaction callbacks |

### Schema and Data Shapes

```typescript
export type HomeNavigationTab = 'allies' | 'routines';

export type HomeNavigationPillProps = {
  accentColor?: string;
  activeTab: HomeNavigationTab;
  onCreateAlly: () => void;
  onTabChange: (tab: HomeNavigationTab) => void;
};

export type GlassSurfaceProps = {
  children?: React.ReactNode;
  colorScheme?: 'auto' | 'light' | 'dark';
  fallbackColor?: string;
  glassEffectStyle?: 'clear' | 'regular' | 'none';
  style?: StyleProp<ViewStyle>;
};
```

## Navigation Pill Layout Configurations

We evaluate two ergonomics layouts for the 3 items in the pill:

- **Configuration A (Center Attraction - Recommended):**
  `[ Allies | ✨ Make an Ally | Routines ]`
  - "Make an Ally" sits centrally as the prominent accent button (`#FF5800`).
  - "Allies" and "Routines" act as symmetrical view tabs.

- **Configuration B (Action on Right):**
  `[ Allies | Routines | + Make an Ally ]`
  - "Allies" and "Routines" form a segmented control on the left.
  - "Make an Ally" is an elevated action button on the far right.

## Implementation Phases

### Phase 1 - Shared GlassSurface Component
- Build `GlassSurface` wrapping `expo-glass-effect` on iOS and falling back to `theme.controlSurface` on Android/Web.
- Unit test platform switching and style propagation.

### Phase 2 - Back Button Refinement
- Update `OnboardingHeader` and `MockConversationScreen` back buttons with `GlassSurface`.
- Verify light and dark mode contrast for icons and press states.

### Phase 3 - Home Navigation Pill & Screen Integration
- Build `HomeNavigationPill` supporting liquid glass, active tab indicator, and the primary "Make an Ally" button.
- Update `OnboardingAlliesScreen`: remove the top tabs (`My allies`, `Routines`) and the fixed bottom button, mounting the floating `HomeNavigationPill` anchored above the bottom safe-area.
- Implement view switching between `allies` list and a minimal `routines` placeholder.

### Phase 4 - Validation & Verification
- Verify test suite passes (`bun run test:run`).
- Verify types and linting (`bun run typecheck:mobile`, `bun run lint:mobile`).
- Confirm live packager reload on port 8082.

## Acceptance Criteria

1. On iOS, `GlassSurface` renders the native `GlassView` from `expo-glass-effect`.
2. On Android/Web, `GlassSurface` renders a view with `theme.controlSurface`.
3. Back buttons across onboarding and conversation screens use liquid glass styling.
4. On the Allies home screen, the previous top tabs and bottom button are replaced by the floating navigation pill.
5. The navigation pill provides clear access to "Allies", "Routines", and "Make an Ally".
6. All automated checks (`typecheck`, `lint:mobile`, `test:run`) pass cleanly.
