import { describe, expect, it } from 'vitest';

import {
  ALLY_NAME_CARET_BLINK_INTERVAL_MS,
  ALLY_NAME_INPUT_LINE_HEIGHT,
  ALLY_NAME_PLACEHOLDER,
  ONBOARDING_COLOR_TRANSITION_DURATION,
  ONBOARDING_COLOR_TRANSITION_EASING,
  WELCOME_CTA_LABEL,
  getColorTransitionDuration,
  getMutedOnboardingColor,
  getPrimaryButtonColor,
} from './onboarding-motion';

describe('onboarding polish contract', () => {
  it('uses relationship-first welcome copy', () => {
    expect(WELCOME_CTA_LABEL).toBe('Meet your first ally');
  });

  it('uses the approved Ally name prompt and a descender-safe line box', () => {
    expect(ALLY_NAME_PLACEHOLDER).toBe('give me a name');
    expect(ALLY_NAME_INPUT_LINE_HEIGHT).toBeGreaterThan(28);
  });

  it('keeps the empty name caret on a standard blink interval', () => {
    expect(ALLY_NAME_CARET_BLINK_INTERVAL_MS).toBe(500);
  });

  it('uses the accent only when the primary button is enabled', () => {
    expect(getPrimaryButtonColor('#FF5800', false)).toBe('#FF5800');
    expect(getPrimaryButtonColor('#FF5800', true)).toBe('#D9D9D9');
  });

  it('uses a fast eased transition and disables it for reduced motion', () => {
    expect(ONBOARDING_COLOR_TRANSITION_DURATION).toBe(220);
    expect(ONBOARDING_COLOR_TRANSITION_EASING).toEqual([0.22, 1, 0.36, 1]);
    expect(getColorTransitionDuration(false)).toBe(220);
    expect(getColorTransitionDuration(true)).toBe(0);
  });

  it('derives a washed-out surface from the active Ally color', () => {
    expect(getMutedOnboardingColor('#A3F06F')).toBe('rgba(163, 240, 111, 0.12)');
  });
});
