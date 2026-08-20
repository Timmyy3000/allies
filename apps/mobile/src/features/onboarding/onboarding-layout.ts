export const ONBOARDING_TOP_PADDING = 36;
export const ONBOARDING_HEADER_LINE_HEIGHT = 28;
export const ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING = 16;
export const ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN = 36;
export const ONBOARDING_LOOK_HINT_ICON_GAP = 6;
export const ONBOARDING_LOOK_HINT_ICON_SIZE = 24;
export const ONBOARDING_LOOK_PREVIEW_SCALE = 0.7;

export function getOnboardingLookPreviewScale(hasSelectedColor: boolean) {
  return hasSelectedColor ? ONBOARDING_LOOK_PREVIEW_SCALE : 1;
}

export function getOnboardingLookPreviewLayerScales(hasSelectedColor: boolean) {
  return {
    artwork: getOnboardingLookPreviewScale(hasSelectedColor),
    shell: 1,
  } as const;
}
