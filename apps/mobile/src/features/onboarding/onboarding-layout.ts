export const ONBOARDING_TOP_PADDING = 36;
export const ONBOARDING_IOS_TOP_PADDING = 24;
export const ONBOARDING_HEADER_BUTTON_SIZE = 44;
export const ONBOARDING_HEADER_LINE_HEIGHT = 28;
export const ONBOARDING_HEADER_ALLY_ARTWORK_SCALE = 0.72;
export const ONBOARDING_HEADER_ROW_TO_ACCESSORY_GAP = 24;
export const ONBOARDING_PAGE_HORIZONTAL_PADDING = 14;
export const ONBOARDING_PERSONALITY_ROW_INSET = ONBOARDING_PAGE_HORIZONTAL_PADDING;
export const ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE = 36;
export const ONBOARDING_PERSONALITY_HELP_ICON_SIZE = 24;
export const ONBOARDING_PERSONALITY_HELP_CARD_MIN_HEIGHT = 0;
export const ONBOARDING_PERSONALITY_HELP_TO_CHIP_GAP = 12;
export const ONBOARDING_PERSONALITY_CHIP_GAP = 8;
export const ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING = 16;
export const ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN = 36;
export const ONBOARDING_LOOK_HINT_ICON_GAP = 6;
export const ONBOARDING_LOOK_HINT_ICON_SIZE = 24;
export const ONBOARDING_LOOK_CHECKMARK_SIZE = { height: 16, width: 20 } as const;
export const ONBOARDING_LOOK_PREVIEW_SCALE = 0.7;
export const ONBOARDING_LOOK_NEUTRAL_SHELL_SCALE = 1.1;
export const ONBOARDING_LOOK_CAROUSEL_GROUP_STYLE = {
  flex: 1,
  justifyContent: 'center',
} as const;

export function getOnboardingEdgeToEdgeStyle(windowWidth: number) {
  return {
    marginHorizontal: -ONBOARDING_PAGE_HORIZONTAL_PADDING,
    width: windowWidth,
  };
}

export function getOnboardingLookPreviewScale(hasSelectedColor: boolean) {
  return hasSelectedColor ? ONBOARDING_LOOK_PREVIEW_SCALE : 1;
}

export function getOnboardingLookPreviewLayerScales(hasSelectedColor: boolean) {
  return {
    artwork: getOnboardingLookPreviewScale(hasSelectedColor),
    shell: 1,
  } as const;
}

export function getOnboardingLookShellSize(
  hasSelectedColor: boolean,
  artworkSize: number,
) {
  return hasSelectedColor
    ? artworkSize
    : artworkSize * ONBOARDING_LOOK_NEUTRAL_SHELL_SCALE;
}

export function getOnboardingLookDotProgress(
  pagePosition: number,
  dotIndex: number,
  dotCount: number,
) {
  'worklet';

  if (dotCount <= 0) return 0;

  const normalizedPosition = ((pagePosition % dotCount) + dotCount) % dotCount;
  const distance = Math.abs(normalizedPosition - dotIndex);
  const circularDistance = Math.min(distance, dotCount - distance);

  return Math.max(0, Math.min(1, 1 - circularDistance));
}
