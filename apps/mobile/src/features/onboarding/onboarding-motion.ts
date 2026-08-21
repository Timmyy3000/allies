export const ALLY_NAME_PLACEHOLDER = 'give me a name';
export const WELCOME_CTA_LABEL = 'Meet your first ally';
export const ALLY_NAME_INPUT_LINE_HEIGHT = 36;
export const ALLY_NAME_CARET_BLINK_INTERVAL_MS = 500;
export const ONBOARDING_COLOR_TRANSITION_DURATION = 220;
export const ONBOARDING_COLOR_TRANSITION_EASING = [0.22, 1, 0.36, 1] as const;
export const ONBOARDING_CHECKMARK_POP_INITIAL_SCALE = 0.84;
export const ONBOARDING_CHECKMARK_POP_SPRING = {
  damping: 18,
  stiffness: 300,
  mass: 0.7,
} as const;
export const ONBOARDING_COMING_ALIVE_WAVE_DURATION_MS = 1350;
export const ONBOARDING_COMING_ALIVE_WAVE_STEP_MS = 70;
export const ONBOARDING_COMING_ALIVE_WAVE_AMPLITUDE = 4;
export const ONBOARDING_LOOK_SWIPE_HINT_DISTANCE = 24;
export const ONBOARDING_LOOK_SWIPE_HINT_DELAY_MS = 300;
export const ONBOARDING_LOOK_SWIPE_HINT_DURATION_MS = 300;
export const ONBOARDING_LOOK_SWIPE_HINT_INTERVAL_MS = 5000;

export function getPrimaryButtonColor(accentColor: string, disabled: boolean) {
  return disabled ? '#D9D9D9' : accentColor;
}

export function getColorTransitionDuration(reducedMotion: boolean) {
  return reducedMotion ? 0 : ONBOARDING_COLOR_TRANSITION_DURATION;
}

export function getOnboardingCheckmarkPopInitialScale(reducedMotion: boolean) {
  return reducedMotion ? 1 : ONBOARDING_CHECKMARK_POP_INITIAL_SCALE;
}

export function getMutedOnboardingColor(accentColor: string): string {
  const match = /^#([\da-f]{6})$/i.exec(accentColor.trim());
  if (!match) return '#F3F3F3';

  const red = Number.parseInt(match[1].slice(0, 2), 16);
  const green = Number.parseInt(match[1].slice(2, 4), 16);
  const blue = Number.parseInt(match[1].slice(4, 6), 16);

  return `rgba(${red}, ${green}, ${blue}, 0.12)`;
}

export function getOnboardingLookSwipeHintOffsets(
  baseOffset: number,
  distance = ONBOARDING_LOOK_SWIPE_HINT_DISTANCE,
) {
  return {
    hintOffset: baseOffset + Math.max(0, distance),
    returnOffset: baseOffset,
  };
}
