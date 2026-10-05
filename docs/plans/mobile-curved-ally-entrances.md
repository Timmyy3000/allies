# Mobile Curved Ally Entrances Implementation Plan

> **For agentic workers:** Implement this plan task-by-task with the existing mobile branch and validate after each meaningful change.

**Goal:** Make the four mobile onboarding Allies enter along visible, fluid X/S-shaped curves while preserving the current GIFs, sizes, landing positions, timing, idle motion, and cursor behavior.

**Architecture:** Add one small pure cubic Bézier point helper and four local, mobile-sized entrance curves. `AllyCharacter` will evaluate the selected curve inside its existing Reanimated derived value and apply the result only through `translateX` and `translateY`. No Remotion runtime, frame table, new dependency, or per-frame JavaScript will be introduced.

**Tech Stack:** Expo SDK 57, React Native 0.86, Reanimated 4.5, TypeScript, Vitest, Android emulator.

## Global Constraints

- Work only on the existing `mobile/dev/onboarding` branch.
- Do not change the supplied GIF files, GIF artwork proportions, final Ally anchors, or cursor/idle behavior.
- Do not import or copy Remotion motion code, path tables, frame samplers, or runtime helpers.
- Animate only transform and opacity values; do not animate layout properties.
- Keep reduced motion supported by the existing `useReducedMotion` path.
- Preserve the existing 850ms entrance duration and 0/120/240/360ms stagger.
- Use the locked workspace toolchain and the existing Vitest, lint, typecheck, and Android validation commands.

---

## Feature Overview

- Problem: The current mobile entrance interpolates directly from each start offset to its settled anchor, with only a small sine offset. It therefore reads as mostly straight instead of following the curved motion language observed in IntroVid2.
- Target users: People opening the Allies mobile onboarding welcome screen.
- Source docs/specs: `docs/superpowers/specs/2026-08-20-mobile-curved-ally-entrances-design.md`; the read-only visual reference is `C:/work/Allies/allies remotion vids` on branch `tolani/IntroVid2`.
- Success outcome: Every Ally visibly bends through an individual X/S-like entrance curve, lands at its current position, and settles into the unchanged GIF-backed idle screen without new runtime errors or a new animation architecture.

## User Stories

1. As a new user, I want each Ally to enter along a curved path, so that the welcome screen feels fluid rather than mechanically linear.
2. As a returning user, I want the Allies to land in the same positions and keep the same idle behavior, so that this refinement does not change the established layout.
3. As a user with reduced motion enabled, I want the Allies to skip the entrance movement, so that the screen remains comfortable and usable.

## Scope

### In Scope

- Add a pure, clamped cubic Bézier point evaluator.
- Define four small mobile-local entrance curves with distinct control points.
- Replace the existing direct-plus-sine entrance position calculation with the selected curve result.
- Keep the current entrance timing, GIF sizing, pointer lifecycle, idle float, and reduced-motion behavior.
- Add focused unit tests and validate on the Android emulator.

### Out of Scope

- Copying or importing Remotion animation code.
- Rebuilding the cursor, GIF assets, blob sizing, logo, CTA, or final actor placements.
- Adding collision, bump, task, domain-drag, or post-entrance behaviors.
- Changing the native build pipeline or adding dependencies.

### Dependencies and Assumptions

- `react-native-reanimated` is already configured and `useDerivedValue` runs the actor calculation on the UI thread.
- The current `AllyCharacter` start offsets are retained as the first point for each curve and `(0, 0)` remains the settled local offset.
- The local Windows Gradle/Ninja issue may require the existing JS-bundle APK fallback for emulator verification; that fallback does not change source behavior.

## Contract and Shape Definitions

### Function and Service Shapes

| Location | Symbol | Signature | Inputs and validation | Return value | Side effects / errors |
| --- | --- | --- | --- | --- | --- |
| `apps/mobile/src/features/onboarding/ally-entrance-motion.ts` | `getCubicPoint` | `function getCubicPoint(path: CubicPath, progress: number): MotionPoint` | Four finite points; progress is clamped to `[0, 1]` | A finite `{ x, y }` point on the cubic curve | Pure worklet-safe math; no I/O or mutation |
| `apps/mobile/src/features/onboarding/ally-entrance-motion.ts` | `ENTRANCE_CURVES` | `Record<AllyColor, CubicPath>` | Fixed blue, yellow, green, and pink local curves | Per-color start, controls, and settled endpoint | Immutable presentation constants |
| `apps/mobile/src/features/onboarding/ally-character.tsx` | `AllyCharacter` | Existing `({ ally, idleProgress }: AllyCharacterProps) => JSX.Element` | Existing Ally data and shared idle clock | Animated native actor | Reanimated lifecycle remains the same; no new external effects |

### API and Transport Contracts

Not applicable. This is a local presentation-only change with no API, transport, webhook, queue, or streamed-event changes.

### Schema and Data Shapes

| Schema / model | Location | Fields and types | Required / nullable / defaults | Validation and invariants | Compatibility / migration notes |
| --- | --- | --- | --- | --- | --- |
| `MotionPoint` | `apps/mobile/src/features/onboarding/ally-entrance-motion.ts` | `x: number`, `y: number` | Both required and finite | Coordinates are local actor offsets in logical pixels | Not persisted |
| `CubicPath` | `apps/mobile/src/features/onboarding/ally-entrance-motion.ts` | `start`, `control1`, `control2`, `end`: `MotionPoint` | All required; `end` is `{ x: 0, y: 0 }` for each entrance | Progress 0/1 must return start/end exactly | Presentation-only |

### Frontend Interaction Shapes

| UI entry point | Hook / action signature | State shape and transitions | API input/output mapping | Loading, error, empty, and permission behavior |
| --- | --- | --- | --- | --- |
| `AllyCharacter` | Existing `useSharedValue` entrance clock and `useDerivedValue` actor style | `offscreen -> curved entrance -> settled idle`; reduced motion resolves immediately to settled | None | No network state; existing cursor fade and GIF autoplay behavior remain unchanged |

## Phases

### Phase 1 - Prove the curve math

- Goal: Establish a small testable contract before touching the actor.
- Work items: Add the failing helper tests for clamping, endpoints, and non-collinear midpoints; run the focused test and confirm the expected module-missing failure.
- Impacted files/systems: Create `apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts`.
- Exit criteria: The new test fails for the intended missing-helper reason, not because of a test syntax or environment error.

### Phase 2 - Add the minimal helper and curves

- Goal: Make the curve contract pass without involving React Native.
- Work items: Create `ally-entrance-motion.ts` with the `MotionPoint`, `CubicPath`, `ENTRANCE_CURVES`, a worklet-safe clamp, and `getCubicPoint`. Use four distinct local control-point pairs that visibly bend each path and end at `(0, 0)`.
- Impacted files/systems: `apps/mobile/src/features/onboarding/ally-entrance-motion.ts` and its focused test.
- Exit criteria: The focused helper tests pass and the helper contains no Remotion imports or runtime dependencies.

### Phase 3 - Integrate the curves into the actor

- Goal: Replace only the direct entrance position calculation.
- Work items: Import `ENTRANCE_CURVES` and `getCubicPoint`; attach the selected curve to the existing color motion config; evaluate it from the existing eased entrance progress; keep idle offsets, rotation, cursor transforms, opacity, GIF source, artwork sizing, and cleanup unchanged.
- Impacted files/systems: `apps/mobile/src/features/onboarding/ally-character.tsx`.
- Exit criteria: The actor’s final position, cursor lifecycle, and reduced-motion behavior are unchanged in code, while the entrance position is derived from the curve.

### Phase 4 - Validate the Android experience

- Goal: Confirm that the new path is visibly curved and does not add a performance regression.
- Work items: Run focused tests, lint, typecheck, and diff checks; export the JS bundle; inject it into the existing x86_64 APK using the established temporary signed diagnostic flow if Gradle is still blocked; install and launch on `emulator-5554`; capture an early entrance screenshot and a settled screenshot; inspect `gfxinfo` and fatal logcat output.
- Impacted files/systems: Android emulator and temporary files under `C:/Users/ASUS/AppData/Local/Temp/` only.
- Exit criteria: All checks pass, each Ally visibly bends during entrance, all four GIFs remain correctly sized, no fatal runtime errors appear, and no new continuous-JS or layout animation is introduced.

## Implementation Tasks

### Task 1: Add the failing curve contract test

**Files:**

- Create: `apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts`

**Interfaces:**

- Consumes: `ENTRANCE_CURVES` and `getCubicPoint` from the new motion helper. They do not exist yet, so this task must fail before production code is added.
- Produces: A repeatable test contract for the helper used by `AllyCharacter`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest';

import {
  ENTRANCE_CURVES,
  getCubicPoint,
} from './ally-entrance-motion';

describe('mobile Ally entrance curves', () => {
  it('clamps progress and preserves each path endpoint', () => {
    for (const path of Object.values(ENTRANCE_CURVES)) {
      expect(getCubicPoint(path, -1)).toEqual(path.start);
      expect(getCubicPoint(path, 0)).toEqual(path.start);
      expect(getCubicPoint(path, 1)).toEqual(path.end);
      expect(getCubicPoint(path, 2)).toEqual(path.end);
    }
  });

  it('bends every path away from its straight start-to-end midpoint', () => {
    for (const path of Object.values(ENTRANCE_CURVES)) {
      const midpoint = getCubicPoint(path, 0.5);
      const straightMidpoint = {
        x: (path.start.x + path.end.x) / 2,
        y: (path.start.y + path.end.y) / 2,
      };

      expect(
        Math.hypot(
          midpoint.x - straightMidpoint.x,
          midpoint.y - straightMidpoint.y,
        ),
      ).toBeGreaterThan(8);
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails for the intended reason**

Run:

```bash
bun test apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts
```

Expected: FAIL because `./ally-entrance-motion` does not exist yet. Do not add production code until this failure is observed.

### Task 2: Implement the minimal curve helper

**Files:**

- Create: `apps/mobile/src/features/onboarding/ally-entrance-motion.ts`

**Interfaces:**

- Consumes: `AllyColor` as a type from `onboarding-characters.ts`.
- Produces: `MotionPoint`, `CubicPath`, `ENTRANCE_CURVES`, and `getCubicPoint` for the actor integration.

- [ ] **Step 1: Add the smallest implementation that satisfies the test**

```ts
import type { AllyColor } from './onboarding-characters';

export type MotionPoint = {
  x: number;
  y: number;
};

export type CubicPath = {
  start: MotionPoint;
  control1: MotionPoint;
  control2: MotionPoint;
  end: MotionPoint;
};

export const ENTRANCE_CURVES = {
  blue: {
    start: { x: 70, y: -130 },
    control1: { x: -70, y: -175 },
    control2: { x: 120, y: -45 },
    end: { x: 0, y: 0 },
  },
  yellow: {
    start: { x: 85, y: -110 },
    control1: { x: -80, y: -150 },
    control2: { x: 130, y: 45 },
    end: { x: 0, y: 0 },
  },
  green: {
    start: { x: -65, y: 120 },
    control1: { x: -100, y: -30 },
    control2: { x: 100, y: 170 },
    end: { x: 0, y: 0 },
  },
  pink: {
    start: { x: 100, y: 105 },
    control1: { x: 155, y: -20 },
    control2: { x: -100, y: 170 },
    end: { x: 0, y: 0 },
  },
} as const satisfies Record<AllyColor, CubicPath>;

function clamp(value: number, minimum: number, maximum: number) {
  'worklet';
  return Math.min(maximum, Math.max(minimum, value));
}

export function getCubicPoint(path: CubicPath, progress: number): MotionPoint {
  'worklet';
  const t = clamp(progress, 0, 1);
  const inverse = 1 - t;
  const inverseSquared = inverse * inverse;
  const tSquared = t * t;

  return {
    x:
      inverseSquared * inverse * path.start.x +
      3 * inverseSquared * t * path.control1.x +
      3 * inverse * tSquared * path.control2.x +
      tSquared * t * path.end.x,
    y:
      inverseSquared * inverse * path.start.y +
      3 * inverseSquared * t * path.control1.y +
      3 * inverse * tSquared * path.control2.y +
      tSquared * t * path.end.y,
  };
}
```

- [ ] **Step 2: Run the focused test and verify it passes**

Run:

```bash
bun test apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts
```

Expected: PASS with both curve tests green.

### Task 3: Integrate the curves without changing other actor behavior

**Files:**

- Modify: `apps/mobile/src/features/onboarding/ally-character.tsx`

**Interfaces:**

- Consumes: `ENTRANCE_CURVES` and `getCubicPoint` from Task 2.
- Produces: The same `AllyCharacter` component contract, with only its entrance translation changed.

- [ ] **Step 1: Replace only the entrance motion configuration**

Add the import:

```ts
import {
  ENTRANCE_CURVES,
  getCubicPoint,
} from './ally-entrance-motion';
```

Replace the existing `startX`, `startY`, `arcX`, and `arcY` fields with the selected curve while preserving the existing delays, rotations, and phases:

```ts
const ENTRANCE_MOTION = {
  blue: {
    delay: 0,
    curve: ENTRANCE_CURVES.blue,
    rotation: -14,
    phase: 0.2,
  },
  yellow: {
    delay: 120,
    curve: ENTRANCE_CURVES.yellow,
    rotation: 14,
    phase: 1.8,
  },
  green: {
    delay: 240,
    curve: ENTRANCE_CURVES.green,
    rotation: 10,
    phase: 3.4,
  },
  pink: {
    delay: 360,
    curve: ENTRANCE_CURVES.pink,
    rotation: -12,
    phase: 5.1,
  },
} as const;
```

- [ ] **Step 2: Replace the direct-plus-sine position expression**

Inside the existing `useDerivedValue` callback, replace the `arc` calculation and the two direct position expressions with:

```ts
const entrancePoint = getCubicPoint(motion.curve, easedEntrance);

return {
  positionX: entrancePoint.x + idleX * entrance,
  positionY: entrancePoint.y + idleY * entrance,
  rotation: motion.rotation * (1 - easedEntrance) + idleRotation * entrance,
  cursorOpacity,
  cursorX: Math.cos(cursorAngle) * pointerRadius,
  cursorY: Math.sin(cursorAngle) * pointerRadius,
  cursorScale: 0.75 + easedEntrance * 0.25,
};
```

Do not change the GIF `<Image>`, artwork sizing, blob style, pointer style, entrance timing, `useEffect` cleanup, or reduced-motion branch.

- [ ] **Step 3: Run the focused tests and typecheck**

Run:

```bash
bun test apps/mobile/src/features/onboarding
bun --filter mobile typecheck
```

Expected: All onboarding tests pass and TypeScript reports no errors.

### Task 4: Run static checks and inspect the Android result

**Files:**

- Modify: None beyond the implementation files above.
- Temporary outputs: `C:/Users/ASUS/AppData/Local/Temp/allies-curved-entrance-export-20260820/` and diagnostic APK files only.

**Interfaces:**

- Consumes: The source changes from Tasks 2 and 3.
- Produces: Evidence that the motion remains smooth, visually curved, and runtime-safe.

- [ ] **Step 1: Run the repository checks**

```bash
bun run lint:mobile
bun --filter mobile typecheck
git diff --check
```

Expected: Each command exits with code 0.

- [ ] **Step 2: Export the Android JavaScript bundle**

From `apps/mobile`:

```powershell
$exportDir = 'C:\Users\ASUS\AppData\Local\Temp\allies-curved-entrance-export-20260820'
New-Item -ItemType Directory -Path $exportDir -Force | Out-Null
$env:NODE_ENV = 'production'
$env:EXPO_NO_DOCTOR = '1'
bunx expo export --platform android --output-dir $exportDir --no-bytecode --max-workers 1
```

Expected: An Android bundle is emitted and the existing four GIF assets are present in the export.

- [ ] **Step 3: Install the exported bundle using the existing diagnostic APK fallback if native Gradle is blocked**

Use the current x86_64 release APK as the base, replace only `assets/index.android.bundle`, sign the temporary copy with the existing temporary debug keystore, and install with:

```powershell
$adb = 'C:\Users\ASUS\AppData\Local\Android\Sdk\platform-tools\adb.exe'
& $adb -s emulator-5554 install --no-streaming -r 'C:\Users\ASUS\AppData\Local\Temp\allies-curved-entrance-signed.apk'
& $adb -s emulator-5554 shell am force-stop com.daviddll.mobile
& $adb -s emulator-5554 shell am start -n com.daviddll.mobile/.MainActivity
```

Expected: Installation succeeds and `com.daviddll.mobile/.MainActivity` launches.

- [ ] **Step 4: Capture early and settled screenshots**

```powershell
Start-Sleep -Milliseconds 350
& $adb -s emulator-5554 exec-out screencap -p > 'C:\Users\ASUS\AppData\Local\Temp\allies-curved-entrance-early.png'
Start-Sleep -Seconds 2
& $adb -s emulator-5554 exec-out screencap -p > 'C:\Users\ASUS\AppData\Local\Temp\allies-curved-entrance-settled.png'
```

Expected: The early frame shows bent trajectories in progress; the settled frame shows the same final placement and correctly sized animated GIFs with no visible cursors.

- [ ] **Step 5: Inspect frame stats and fatal logs**

```powershell
& $adb -s emulator-5554 shell dumpsys gfxinfo com.daviddll.mobile reset
Start-Sleep -Seconds 12
& $adb -s emulator-5554 shell dumpsys gfxinfo com.daviddll.mobile | Select-String -Pattern 'Total frames rendered|Janky frames:|50th percentile|90th percentile|95th percentile|99th percentile|Number Slow UI thread|Number Slow bitmap uploads|Number Slow issue draw commands'
& $adb -s emulator-5554 logcat -d -t 500 | Select-String -Pattern 'FATAL EXCEPTION|AndroidRuntime|ReactNativeJS|Unable to resolve|SoLoader'
```

Expected: No fatal runtime lines; compare the frame sample with the previous GIF-enabled baseline and investigate any obvious regression before handoff.

### Task 5: Review the focused diff

**Files:**

- Review: `apps/mobile/src/features/onboarding/ally-entrance-motion.ts`
- Review: `apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts`
- Review: `apps/mobile/src/features/onboarding/ally-character.tsx`

- [ ] **Step 1: Confirm the diff is scoped**

```bash
git diff -- apps/mobile/src/features/onboarding/ally-entrance-motion.ts apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts apps/mobile/src/features/onboarding/ally-character.tsx
```

Expected: Only the new curve helper/test and the entrance position integration appear; GIF sources, sizes, cursor styles, idle values, timing, and final layout remain unchanged.

- [ ] **Step 2: Stop for visual feedback before the next motion behavior**

Do not add bumps, task states, new cursor behavior, or further idle changes in this task. Hand off the early and settled screenshots for visual approval first.

## Acceptance Criteria

1. The four Ally curves start at their existing local offsets and end exactly at `{ x: 0, y: 0 }`.
2. Each curve’s midpoint differs from its straight start/end interpolation by a visible amount.
3. The current stagger and 850ms duration remain unchanged.
4. The existing GIF assets, Remotion-derived artwork proportions, blob sizes, final placements, cursor fade behavior, and idle float remain unchanged.
5. Reduced motion skips entrance animation and keeps cursors hidden as before.
6. The actor motion uses only Reanimated derived values and transform/opacity styles.
7. `bun test apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts`, `bun run lint:mobile`, `bun --filter mobile typecheck`, and `git diff --check` pass.

## Backend Considerations

Not applicable.

## Frontend Considerations

### Data Path

- User action entry: Mounting the onboarding welcome screen.
- Client route/component: `apps/mobile/src/features/onboarding/onboarding-screen.tsx` -> `AllyCharacter`.
- Client API route/proxy: None.
- Backend endpoint: None.
- Response -> UI model mapping: None.
- Error/loading/retry path: None; motion is local and existing screen loading behavior is unchanged.

### State Management Considerations

- State ownership by layer: `AllyCharacter` owns the entrance shared value; the screen continues to own only the shared idle clock.
- Source of truth vs derived state: `ENTRANCE_CURVES` is the source of truth; position and visual styles are derived on the UI thread.
- Caching/invalidation approach: None.
- Concurrency and dedupe handling: Existing `cancelAnimation(entranceProgress)` cleanup remains in place.

## Test Plan

- Unit tests: `ally-entrance-motion.test.ts` covers endpoints, clamping, and visible curvature for all four curves.
- Integration/API tests: Not applicable.
- Regression checks: Existing onboarding tests, mobile lint, mobile typecheck, diff check, and Android launch.
- Manual verification checklist:
  - Restart the app and observe the entrance from the first frame.
  - Confirm blue, yellow, green, and pink each bend rather than travel directly.
  - Confirm each Ally lands at its previous anchor.
  - Confirm GIFs remain animated and correctly contained.
  - Wait for settlement and confirm cursors disappear.
  - Inspect reduced-motion behavior if available.
  - Check emulator frame stats after settlement and scan logcat for fatal errors.
- Commands:
  - `bun test apps/mobile/src/features/onboarding/ally-entrance-motion.test.ts`
  - `bun run lint:mobile`
  - `bun --filter mobile typecheck`
  - `git diff --check`

## Risks and Mitigations

- Risk: A control point creates a curve that is too subtle or overshoots the visible composition.
  - Mitigation: Keep the controls local and inspect early/mid-entrance screenshots before moving to the next onboarding behavior.
  - Rollback/fallback: Revert only the curve helper import and position calculation to the existing direct-plus-sine expression.
- Risk: Capturing curve data or evaluating it from JS on every frame could reintroduce jank.
  - Mitigation: Keep the point evaluator worklet-safe, use only four fixed points per actor, and derive the result inside Reanimated.
  - Rollback/fallback: Disable the new path calculation while leaving GIFs and existing actor-level idle motion intact.
- Risk: The local Android Gradle toolchain remains unable to rebuild native code.
  - Mitigation: Use the already-established JS-bundle APK replacement only for diagnostic installation; do not change repository build configuration.
  - Rollback/fallback: Continue with source tests and emulator screenshots from the existing diagnostic APK path.
