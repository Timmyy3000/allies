import { describe, expect, it } from 'vitest';

import {
  ALLY_NAME_CARET_BLINK_INTERVAL_MS,
  ALLY_NAME_INPUT_LINE_HEIGHT,
  ALLY_NAME_PLACEHOLDER,
  ONBOARDING_COLOR_TRANSITION_DURATION,
  ONBOARDING_COLOR_TRANSITION_EASING,
  ONBOARDING_CHECKMARK_POP_INITIAL_SCALE,
  ONBOARDING_CHECKMARK_POP_SPRING,
  ONBOARDING_COMING_ALIVE_WAVE_AMPLITUDE,
  ONBOARDING_COMING_ALIVE_WAVE_DURATION_MS,
  ONBOARDING_COMING_ALIVE_WAVE_STEP_MS,
  ONBOARDING_LOOK_SWIPE_HINT_INTERVAL_MS,
  WELCOME_CTA_LABEL,
  getColorTransitionDuration,
  getMutedOnboardingColor,
  getOnboardingCheckmarkPopInitialScale,
  getPrimaryButtonColor,
  getOnboardingLookSwipeHintOffsets,
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

  it('uses a restrained checkmark pop with a reduced-motion fallback', () => {
    expect(ONBOARDING_CHECKMARK_POP_INITIAL_SCALE).toBe(0.84);
    expect(ONBOARDING_CHECKMARK_POP_SPRING).toEqual({
      damping: 18,
      stiffness: 300,
      mass: 0.7,
    });
    expect(getOnboardingCheckmarkPopInitialScale(false)).toBe(0.84);
    expect(getOnboardingCheckmarkPopInitialScale(true)).toBe(1);
  });

  it('keeps the coming-alive wave aligned with the web motion contract', () => {
    expect(ONBOARDING_COMING_ALIVE_WAVE_DURATION_MS).toBe(1350);
    expect(ONBOARDING_COMING_ALIVE_WAVE_STEP_MS).toBe(70);
    expect(ONBOARDING_COMING_ALIVE_WAVE_AMPLITUDE).toBe(4);
  });

  it('derives a washed-out surface from the active Ally color', () => {
    expect(getMutedOnboardingColor('#A3F06F')).toBe('rgba(163, 240, 111, 0.12)');
  });

  it('nudges the look carousel left and returns to its original offset', () => {
    expect(ONBOARDING_LOOK_SWIPE_HINT_INTERVAL_MS).toBe(5000);
    expect(getOnboardingLookSwipeHintOffsets(1200, 24)).toEqual({
      hintOffset: 1224,
      returnOffset: 1200,
    });
    expect(getOnboardingLookSwipeHintOffsets(10, 24)).toEqual({
      hintOffset: 34,
      returnOffset: 10,
    });
  });
});
