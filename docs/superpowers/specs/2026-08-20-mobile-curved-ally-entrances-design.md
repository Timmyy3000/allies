# Mobile Curved Ally Entrances Design

## Goal

Make the four floating Allies enter the mobile welcome screen along visible,
fluid X/S-shaped curves instead of reading as straight-line movement, without
reintroducing the performance problems from the earlier Remotion runtime port.

## Scope

- Change only the entrance trajectory calculation in the mobile Ally actor.
- Keep the current final anchors, stagger, entrance duration, GIF assets and
  artwork sizing unchanged.
- Keep the existing idle float, cursor fade-out, and reduced-motion behavior.
- Do not copy Remotion code, path tables, or frame-sampling logic into mobile.
- Do not add a new animation dependency or per-frame JavaScript work.

## Design decisions

- Use one small cubic Bézier evaluator in a Reanimated worklet. Each Ally gets
  four local points: its current off-screen start, two direction-specific
  control points, and the existing settled anchor at `(0, 0)`.
- Choose control points that create a visible two-bend X/S-like sweep for each
  color, with different directions so the group feels organic rather than
  cloned.
- Apply the existing eased entrance progress to the curve parameter. Position
  remains a transform-only `translateX`/`translateY` update, so no layout is
  recalculated during motion.
- Preserve the existing entrance rotation behavior for this pass. Movement
  shape is the isolated variable; banking can be tuned separately after the
  path is visually approved.
- Keep the same timing values: 850ms entrance duration and the existing
  0/120/240/360ms color delays.

## Test strategy

- Add pure unit coverage for the curve helper before implementation:
  - progress 0 returns the configured start point;
  - progress 1 returns the settled point;
  - a mid-progress point deviates from the straight start/end segment;
  - out-of-range progress is clamped.
- Run the focused onboarding tests, mobile lint, and mobile typecheck.
- Export and install a JS-only Android diagnostic build using the existing
  fallback when native Gradle compilation is blocked by the local Windows
  toolchain.
- Inspect a fresh emulator screenshot and frame timing after the entrance has
  settled. A path change is accepted only if the visual curve is clear and no
  new fatal runtime errors appear.

## Acceptance criteria

- Every Ally visibly bends during entrance; none travels as a direct line from
  its start offset to its anchor.
- All Allies still land at their current positions and settle into the same
  idle behavior.
- GIFs remain the current assets and remain correctly sized inside their blobs.
- Reduced motion still skips the entrance motion.
- The implementation uses only existing Reanimated primitives and transform
  styles.
