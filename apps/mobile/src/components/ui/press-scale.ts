export const PRESS_SCALE = 1.075;
export const PRESS_SCALE_DURATION_MS = 140;

export function getPressScaleTarget(
  pressed: boolean,
  disabled: boolean,
  reducedMotion: boolean,
  pressedScale = PRESS_SCALE,
): number {
  return pressed && !disabled && !reducedMotion ? pressedScale : 1;
}
