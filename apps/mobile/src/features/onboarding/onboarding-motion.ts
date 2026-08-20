export const ALLY_NAME_PLACEHOLDER = 'give me a name';
export const WELCOME_CTA_LABEL = 'Meet your first ally';
export const ALLY_NAME_INPUT_LINE_HEIGHT = 36;
export const ALLY_NAME_CARET_BLINK_INTERVAL_MS = 500;
export const ONBOARDING_COLOR_TRANSITION_DURATION = 220;
export const ONBOARDING_COLOR_TRANSITION_EASING = [0.22, 1, 0.36, 1] as const;

export function getPrimaryButtonColor(accentColor: string, disabled: boolean) {
  return disabled ? '#D9D9D9' : accentColor;
}

export function getColorTransitionDuration(reducedMotion: boolean) {
  return reducedMotion ? 0 : ONBOARDING_COLOR_TRANSITION_DURATION;
}

export function getMutedOnboardingColor(accentColor: string): string {
  const match = /^#([\da-f]{6})$/i.exec(accentColor.trim());
  if (!match) return '#F3F3F3';

  const red = Number.parseInt(match[1].slice(0, 2), 16);
  const green = Number.parseInt(match[1].slice(2, 4), 16);
  const blue = Number.parseInt(match[1].slice(4, 6), 16);

  return `rgba(${red}, ${green}, ${blue}, 0.12)`;
}
