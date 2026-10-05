
import { describe, expect, it } from 'vitest';

import {
  ALLY_NAME_CARET_BLINK_INTERVAL_MS,
  ALLY_NAME_INPUT_LINE_HEIGHT,
  ALLY_NAME_PLACEHOLDER,
  ONBOARDING_COLOR_TRANSITION_DURATION,
  ONBOARDING_COLOR_TRANSITION_EASING,
  ONBOARDING_CHECKMARK_POP_INITIAL_SCALE,
  ONBOARDING_CHECKMARK_POP_SPRING,
  ONBOARDING_COMING_ALIVE_SQUISH_DURATION_MS,
  ONBOARDING_BASICS_BOUNCE_CYCLE_MS,
  ONBOARDING_BASICS_BOUNCE_LIFT,
  ONBOARDING_EDITOR_HEIGHT,
  ONBOARDING_EDITOR_KEYBOARD_HEIGHT_SCALE,
  ONBOARDING_LOOK_SWIPE_HINT_INTERVAL_MS,
  WELCOME_CTA_LABEL,
  getColorTransitionDuration,
  getMutedOnboardingColor,
  getOnboardingCheckmarkPopInitialScale,
  getPrimaryButtonColor,
  getOnboardingLookSwipeHintOffsets,
  getOnboardingComingAliveSquishTransform,
  getOnboardingPersonalitySelectorOffset,
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

  it('shrinks the keyboard editor to half its resting height', () => {
    expect(ONBOARDING_EDITOR_HEIGHT).toBe(250);
    expect(ONBOARDING_EDITOR_HEIGHT * ONBOARDING_EDITOR_KEYBOARD_HEIGHT_SCALE).toBe(125);
  });

  it('moves the personality selector from closed to 295px open with keyboard progress', () => {
    expect(getOnboardingPersonalitySelectorOffset(0)).toBe(0);
    expect(getOnboardingPersonalitySelectorOffset(1)).toBe(295);
  });

  it('uses the selected accent while active and the theme color while disabled', () => {
    expect(getPrimaryButtonColor('#3446E9', false, '#202020')).toBe('#3446E9');
    expect(getPrimaryButtonColor('#3446E9', true, '#202020')).toBe('#202020');
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

  it('keeps the basics Ally bounce short and grounded', () => {
    expect(ONBOARDING_BASICS_BOUNCE_CYCLE_MS).toBe(720);
    expect(ONBOARDING_BASICS_BOUNCE_LIFT).toBe(18);
  });

  it('uses one finite coming-alive squish that settles at identity', () => {
    expect(ONBOARDING_COMING_ALIVE_SQUISH_DURATION_MS).toBe(599);
    expect(getOnboardingComingAliveSquishTransform(0)).toEqual({
      scaleX: 1,
      scaleY: 1,
      translateY: 0,
    });
    expect(getOnboardingComingAliveSquishTransform(0.6)).toEqual({
      scaleX: 0.94,
      scaleY: 1.08,
      translateY: -18,
    });
    expect(getOnboardingComingAliveSquishTransform(1)).toEqual({
      scaleX: 1,
      scaleY: 1,
      translateY: 0,
    });
  });

  it('derives a washed-out surface from the active Ally color', () => {
    expect(getMutedOnboardingColor('#A3F06F')).toBe('rgba(163, 240, 111, 0.12)');
  });

  it('accepts an explicit opacity for a washed-out Ally color', () => {
    expect(getMutedOnboardingColor('#A3F06F', 0.04)).toBe('rgba(163, 240, 111, 0.04)');
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
