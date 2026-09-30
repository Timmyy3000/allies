
import { describe, expect, it } from 'vitest';

import {
  ONBOARDING_EDITOR_HEIGHT,
  ONBOARDING_EDITOR_REGION_HEIGHT,
  ONBOARDING_EDITOR_KEYBOARD_HEIGHT,
  getOnboardingEditorHeight,
  getOnboardingKeyboardPadding,
} from './onboarding-motion';

describe('onboarding editor height', () => {
  it('keeps the normal and keyboard editor heights as a pure motion contract', () => {
    expect(ONBOARDING_EDITOR_HEIGHT).toBe(250);
    expect(ONBOARDING_EDITOR_REGION_HEIGHT).toBe(286);
    expect(ONBOARDING_EDITOR_KEYBOARD_HEIGHT).toBe(125);
    expect(getOnboardingEditorHeight(false)).toBe(250);
    expect(getOnboardingEditorHeight(true)).toBe(125);
    expect(getOnboardingKeyboardPadding(700, 600)).toBe(0);
    expect(getOnboardingKeyboardPadding(713, 600)).toBe(0);
    expect(getOnboardingKeyboardPadding(760, 600)).toBe(47);
  });
});
