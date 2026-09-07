import { describe, expect, it } from 'vitest';

import {
  ONBOARDING_HEADER_LINE_HEIGHT,
  ONBOARDING_HEADER_BUTTON_SIZE,
  ONBOARDING_IOS_TOP_PADDING,
  ONBOARDING_PAGE_HORIZONTAL_PADDING,
  ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN,
  ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING,
  ONBOARDING_LOOK_CHECKMARK_SIZE,
  ONBOARDING_LOOK_HINT_ICON_GAP,
  ONBOARDING_LOOK_HINT_ICON_SIZE,
  ONBOARDING_LOOK_NEUTRAL_SHELL_SCALE,
  ONBOARDING_LOOK_PREVIEW_SCALE,
  ONBOARDING_LOOK_CAROUSEL_GROUP_STYLE,
  ONBOARDING_HEADER_ALLY_ARTWORK_SCALE,
  ONBOARDING_HEADER_ROW_TO_ACCESSORY_GAP,
  ONBOARDING_PERSONALITY_CHIP_GAP,
  ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE,
  ONBOARDING_PERSONALITY_HELP_CARD_MIN_HEIGHT,
  ONBOARDING_PERSONALITY_HELP_ICON_SIZE,
  ONBOARDING_PERSONALITY_HELP_TO_CHIP_GAP,
  ONBOARDING_PERSONALITY_ROW_INSET,
  ONBOARDING_TOP_PADDING,
  getOnboardingLookPreviewLayerScales,
  getOnboardingLookPreviewScale,
  getOnboardingLookDotProgress,
  getOnboardingLookShellSize,
  getOnboardingEdgeToEdgeStyle,
} from './onboarding-layout';

describe('onboarding layout contract', () => {
  it('keeps chat and onboarding back controls on the same geometry', () => {
    expect(ONBOARDING_HEADER_BUTTON_SIZE).toBe(44);
    expect(ONBOARDING_IOS_TOP_PADDING).toBe(24);
    expect(ONBOARDING_TOP_PADDING).toBe(36);
  });

  it('keeps the header below the status bar with room for descenders', () => {
    expect(ONBOARDING_TOP_PADDING).toBe(36);
    expect(ONBOARDING_HEADER_LINE_HEIGHT).toBeGreaterThan(24);
  });

  it('lets horizontal selectors bleed through the page inset', () => {
    expect(ONBOARDING_PAGE_HORIZONTAL_PADDING).toBe(14);
    expect(getOnboardingEdgeToEdgeStyle(390)).toEqual({
      marginHorizontal: -14,
      width: 390,
    });
  });

  it('centers the Ally carousel group in the available vertical space', () => {
    expect(ONBOARDING_LOOK_CAROUSEL_GROUP_STYLE).toEqual({
      flex: 1,
      justifyContent: 'center',
    });
  });

  it('interpolates neighboring look dots while the carousel is swiped', () => {
    expect(getOnboardingLookDotProgress(0, 0, 4)).toBe(1);
    expect(getOnboardingLookDotProgress(0.25, 0, 4)).toBe(0.75);
    expect(getOnboardingLookDotProgress(0.25, 1, 4)).toBe(0.25);
    expect(getOnboardingLookDotProgress(0.5, 0, 4)).toBe(0.5);
    expect(getOnboardingLookDotProgress(3.75, 3, 4)).toBe(0.25);
    expect(getOnboardingLookDotProgress(3.75, 0, 4)).toBe(0.75);
  });

  it('keeps the header Ally artwork inset inside its fixed shell', () => {
    expect(ONBOARDING_HEADER_ALLY_ARTWORK_SCALE).toBe(0.72);
  });

  it('keeps 24px between the header row and its Ally accessory', () => {
    expect(ONBOARDING_HEADER_ROW_TO_ACCESSORY_GAP).toBe(24);
  });

  it('keeps the look color picker full-bleed and close to the CTA', () => {
    expect(ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING).toBe(16);
    expect(ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN).toBe(36);
    expect(ONBOARDING_LOOK_HINT_ICON_GAP).toBe(6);
    expect(ONBOARDING_LOOK_HINT_ICON_SIZE).toBe(24);
    expect(ONBOARDING_LOOK_CHECKMARK_SIZE).toEqual({ width: 20, height: 16 });
  });

  it('keeps the colored shell full size while scaling its Ally artwork', () => {
    expect(ONBOARDING_LOOK_PREVIEW_SCALE).toBe(0.7);
    expect(getOnboardingLookPreviewScale(false)).toBe(1);
    expect(getOnboardingLookPreviewScale(true)).toBe(0.7);
    expect(getOnboardingLookPreviewLayerScales(true)).toEqual({
      artwork: 0.7,
      shell: 1,
    });
  });

  it('gives every neutral look option the same shell room without enlarging its artwork', () => {
    expect(ONBOARDING_LOOK_NEUTRAL_SHELL_SCALE).toBe(1.1);
    expect(getOnboardingLookShellSize(false, 160)).toBe(176);
    expect(getOnboardingLookShellSize(true, 160)).toBe(160);
  });

  it('keeps the personality row aligned and spaced inside its edge-to-edge viewport', () => {
    expect(ONBOARDING_PERSONALITY_ROW_INSET).toBe(14);
    expect(ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE).toBe(36);
    expect(ONBOARDING_PERSONALITY_HELP_CARD_MIN_HEIGHT).toBe(0);
    expect(ONBOARDING_PERSONALITY_HELP_ICON_SIZE).toBe(24);
    expect(ONBOARDING_PERSONALITY_HELP_TO_CHIP_GAP).toBe(12);
    expect(ONBOARDING_PERSONALITY_CHIP_GAP).toBe(8);
  });
});
