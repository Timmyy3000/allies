import {
  ALLY_SHAPES,
  isAllyColor,
  type AllyColorValue,
  type AllyShape,
} from '../onboarding/onboarding-state';

export function getAllyAppearance(key: string): { shape: AllyShape; color: AllyColorValue } {
  const [shape, color] = key.split(':');
  const normalizedColor = color ? `#${color.toUpperCase()}` : '#FF5800';
  return {
    shape: shape && (ALLY_SHAPES as readonly string[]).includes(shape) ? shape as AllyShape : 'ghosty',
    color: isAllyColor(normalizedColor) ? normalizedColor : '#FF5800',
  };
}
