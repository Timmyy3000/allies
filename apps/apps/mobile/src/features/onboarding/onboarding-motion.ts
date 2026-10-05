export const ALLY_NAME_PLACEHOLDER = 'give me a name';
export const WELCOME_CTA_LABEL = 'Meet your first ally';
export const ALLY_NAME_INPUT_LINE_HEIGHT = 36;
export const ALLY_NAME_CARET_BLINK_INTERVAL_MS = 500;
export const ONBOARDING_EDITOR_HEIGHT = 250;
export const ONBOARDING_EDITOR_REGION_HEIGHT = ONBOARDING_EDITOR_HEIGHT + 36;
export const ONBOARDING_EDITOR_KEYBOARD_HEIGHT = 125;
export const ONBOARDING_EDITOR_KEYBOARD_HEIGHT_SCALE = 0.5;
export const ONBOARDING_EDITOR_KEYBOARD_GAP = 12;
export const ONBOARDING_EDITOR_RESIZE_DURATION_MS = 240;
export const ONBOARDING_EDITOR_RESIZE_EASING = [0.32, 0.72, 0, 1] as const;
export const ONBOARDING_COLOR_TRANSITION_DURATION = 220;
export const ONBOARDING_COLOR_TRANSITION_EASING = [0.22, 1, 0.36, 1] as const;
export const ONBOARDING_CHECKMARK_POP_INITIAL_SCALE = 0.84;
export const ONBOARDING_CHECKMARK_POP_SPRING = {
  damping: 18,
  stiffness: 300,
  mass: 0.7,
} as const;
export const ONBOARDING_COMING_ALIVE_SQUISH_DURATION_MS = 599;
export const ONBOARDING_LOOK_SWIPE_HINT_DISTANCE = 24;
export const ONBOARDING_LOOK_SWIPE_HINT_DELAY_MS = 300;
export const ONBOARDING_LOOK_SWIPE_HINT_DURATION_MS = 300;
export const ONBOARDING_LOOK_SWIPE_HINT_INTERVAL_MS = 5000;
export const ONBOARDING_POST_SETUP_DURATION_MS = 2000;
export const ONBOARDING_POST_SETUP_FADE_DURATION_MS = 280;
export const ONBOARDING_BASICS_BOUNCE_CYCLE_MS = 720;
export const ONBOARDING_BASICS_BOUNCE_LIFT = 18;

export function getPrimaryButtonColor(
  accentColor: string,
  disabled: boolean,
  inactiveColor = '#D9D9D9',
) {
  return disabled ? inactiveColor : accentColor;
}

export function getColorTransitionDuration(reducedMotion: boolean) {
  return reducedMotion ? 0 : ONBOARDING_COLOR_TRANSITION_DURATION;
}

export function getOnboardingEditorHeight(keyboardVisible: boolean) {
  return keyboardVisible ? ONBOARDING_EDITOR_KEYBOARD_HEIGHT : ONBOARDING_EDITOR_HEIGHT;
}

export function getOnboardingKeyboardPadding(expandedEditorBottom: number, keyboardTop: number) {
  return Math.max(
    0,
    expandedEditorBottom -
      (ONBOARDING_EDITOR_HEIGHT - ONBOARDING_EDITOR_KEYBOARD_HEIGHT) +
      ONBOARDING_EDITOR_KEYBOARD_GAP -
      keyboardTop,
  );
}

export function getOnboardingPersonalitySelectorOffset(keyboardProgress: number) {
  'worklet';

  return keyboardProgress * 295;
}

export function getOnboardingCheckmarkPopInitialScale(reducedMotion: boolean) {
  return reducedMotion ? 1 : ONBOARDING_CHECKMARK_POP_INITIAL_SCALE;
}

const COMING_ALIVE_SQUISH_PROGRESS = [0, 0.18, 0.6, 0.82, 1] as const;
const COMING_ALIVE_SQUISH_TRANSLATE_Y = [0, 0, -ONBOARDING_BASICS_BOUNCE_LIFT, 0, 0] as const;
const COMING_ALIVE_SQUISH_SCALE_X = [1, 1.08, 0.94, 1.1, 1] as const;
const COMING_ALIVE_SQUISH_SCALE_Y = [1, 0.9, 1.08, 0.9, 1] as const;

function interpolateComingAliveValue(progress: number, output: readonly number[]) {
  'worklet';

  for (let index = 1; index < COMING_ALIVE_SQUISH_PROGRESS.length; index += 1) {
    const end = COMING_ALIVE_SQUISH_PROGRESS[index];
    if (progress <= end) {
      const start = COMING_ALIVE_SQUISH_PROGRESS[index - 1];
      const range = end - start;
      const fraction = range === 0 ? 1 : (progress - start) / range;
      return output[index - 1] + (output[index] - output[index - 1]) * fraction;
    }
  }

  return output[output.length - 1];
}

export function getOnboardingComingAliveSquishTransform(progress: number) {
  'worklet';

  const clampedProgress = Math.min(1, Math.max(0, progress));
  return {
    scaleX: interpolateComingAliveValue(clampedProgress, COMING_ALIVE_SQUISH_SCALE_X),
    scaleY: interpolateComingAliveValue(clampedProgress, COMING_ALIVE_SQUISH_SCALE_Y),
    translateY: interpolateComingAliveValue(clampedProgress, COMING_ALIVE_SQUISH_TRANSLATE_Y),
  };
}

export function getMutedOnboardingColor(accentColor: string, opacity = 0.12): string {
  const match = /^#([\da-f]{6})$/i.exec(accentColor.trim());
  if (!match) return '#F3F3F3';

  const red = Number.parseInt(match[1].slice(0, 2), 16);
  const green = Number.parseInt(match[1].slice(2, 4), 16);
  const blue = Number.parseInt(match[1].slice(4, 6), 16);

  return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
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
