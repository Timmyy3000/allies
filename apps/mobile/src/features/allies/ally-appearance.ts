import {
  ALLY_SHAPES,
  DEFAULT_ONBOARDING_ACCENT,
  isAllyColor,
  type AllyColorValue,
  type AllyShape,
} from '../onboarding/onboarding-state';

export function getAllyAppearance(key: string): { shape: AllyShape; color: AllyColorValue } {
  const [shape, color] = key.split(':');
  const normalizedColor = color ? `#${color.toUpperCase()}` : DEFAULT_ONBOARDING_ACCENT;

  return {
    shape: shape && (ALLY_SHAPES as readonly string[]).includes(shape) ? shape as AllyShape : 'ghosty',
    color: isAllyColor(normalizedColor) ? normalizedColor : DEFAULT_ONBOARDING_ACCENT,
  };
}
