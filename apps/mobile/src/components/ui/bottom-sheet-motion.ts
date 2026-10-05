export const BOTTOM_SHEET_ANIMATION_DURATION_MS = 260;
const BOTTOM_SHEET_MIN_DISMISS_DISTANCE = 120;
const BOTTOM_SHEET_DISMISS_RATIO = 0.2;
const BOTTOM_SHEET_DISMISS_VELOCITY = 900;

export function getBottomSheetAnimationTarget(
  visible: boolean,
  reducedMotion: boolean,
  exitDistance: number,
) {
  return {
    duration: reducedMotion ? 0 : BOTTOM_SHEET_ANIMATION_DURATION_MS,
    overlayOpacity: visible ? 1 : 0,
    translateY: visible ? 0 : exitDistance,
  };
}

export function shouldDismissBottomSheet(
  translationY: number,
  velocityY: number,
  viewportHeight: number,
) {
  'worklet';

  return translationY >= Math.max(
    BOTTOM_SHEET_MIN_DISMISS_DISTANCE,
    viewportHeight * BOTTOM_SHEET_DISMISS_RATIO,
  ) || velocityY >= BOTTOM_SHEET_DISMISS_VELOCITY;
}
