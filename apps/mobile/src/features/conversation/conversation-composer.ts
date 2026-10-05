import { ONBOARDING_PREVIEW_COMPOSER_INITIAL_BORDER_RADIUS } from '../onboarding/onboarding-preview';

export const COMPOSER_MIN_HEIGHT = 48;
export const COMPOSER_MAX_HEIGHT = 96;
export const COMPOSER_MIN_RADIUS = 18;

export function getComposerHeight(contentSizeHeight: number, hasDraft: boolean): number {
  if (!hasDraft) return COMPOSER_MIN_HEIGHT;

  return Math.min(
    COMPOSER_MAX_HEIGHT,
    Math.max(COMPOSER_MIN_HEIGHT, contentSizeHeight + 16),
  );
}

export function getComposerBorderRadius(height: number): number {
  return height > COMPOSER_MIN_HEIGHT
    ? COMPOSER_MIN_RADIUS
    : ONBOARDING_PREVIEW_COMPOSER_INITIAL_BORDER_RADIUS;
}

export function shouldScrollComposer(draft: string, height: number): boolean {
  return draft.length > 0 && height >= COMPOSER_MAX_HEIGHT;
}
