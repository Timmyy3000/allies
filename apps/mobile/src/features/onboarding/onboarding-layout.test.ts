import { describe, expect, it } from 'vitest';

import {
  ONBOARDING_HEADER_LINE_HEIGHT,
  ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN,
  ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING,
  ONBOARDING_LOOK_HINT_ICON_GAP,
  ONBOARDING_LOOK_HINT_ICON_SIZE,
  ONBOARDING_LOOK_PREVIEW_SCALE,
  ONBOARDING_TOP_PADDING,
  getOnboardingLookPreviewLayerScales,
  getOnboardingLookPreviewScale,
} from './onboarding-layout';

describe('onboarding layout contract', () => {
  it('keeps the header below the status bar with room for descenders', () => {
    expect(ONBOARDING_TOP_PADDING).toBe(36);
    expect(ONBOARDING_HEADER_LINE_HEIGHT).toBeGreaterThan(24);
  });

  it('keeps the look color picker full-bleed and close to the CTA', () => {
    expect(ONBOARDING_LOOK_COLOR_ROW_HORIZONTAL_PADDING).toBe(16);
    expect(ONBOARDING_LOOK_COLOR_ROW_BOTTOM_MARGIN).toBe(36);
    expect(ONBOARDING_LOOK_HINT_ICON_GAP).toBe(6);
    expect(ONBOARDING_LOOK_HINT_ICON_SIZE).toBe(24);
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
});
