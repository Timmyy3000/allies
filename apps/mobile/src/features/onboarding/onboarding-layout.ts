import type { AllyShape } from './onboarding-state';

export const ONBOARDING_TOP_PADDING = 36;
export const ONBOARDING_HEADER_LINE_HEIGHT = 28;
export const ONBOARDING_HEADER_ALLY_ARTWORK_SCALE = 0.72;
export const ONBOARDING_HEADER_ROW_TO_ACCESSORY_GAP = 24;
export const ONBOARDING_PAGE_HORIZONTAL_PADDING = 14;
export const ONBOARDING_PERSONALITY_ROW_INSET = ONBOARDING_PAGE_HORIZONTAL_PADDING;
export const ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE = 36;
export const ONBOARDING_PERSONALITY_HELP_ICON_SIZE = 24;
export const ONBOARDING_PERSONALITY_HELP_CARD_MIN_HEIGHT = 0;
export const ONBOARDING_PERSONALITY_HELP_OUTER_BACKGROUND = '#F3F3F3';
export const ONBOARDING_PERSONALITY_HELP_TO_CHIP_GAP = 12;
export const ONBOARDING_PERSONALITY_CHIP_GAP = 8;
export const ONBOARDING_PERSONALITY_EDITOR_BACKGROUND = '#F3F3F3';
export const ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING = 16;
export const ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN = 36;
export const ONBOARDING_LOOK_HINT_ICON_GAP = 6;
export const ONBOARDING_LOOK_HINT_ICON_SIZE = 24;
export const ONBOARDING_LOOK_CHECKMARK_SIZE = { height: 16, width: 20 } as const;
export const ONBOARDING_LOOK_PREVIEW_SCALE = 0.7;
export const ONBOARDING_LOOK_ROCKY_NEUTRAL_ARTWORK_SCALE = 0.96;
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

export function getOnboardingLookArtworkScale(
  identity: AllyShape,
  hasSelectedColor: boolean,
) {
  return identity === 'rocky' && !hasSelectedColor
    ? ONBOARDING_LOOK_ROCKY_NEUTRAL_ARTWORK_SCALE
    : 1;
}
