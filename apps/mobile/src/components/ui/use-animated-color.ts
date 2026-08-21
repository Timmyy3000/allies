import { useEffect } from 'react';
import {
  Easing,
  useReducedMotion,
  useSharedValue,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';

import {
  ONBOARDING_COLOR_TRANSITION_EASING,
  getColorTransitionDuration,
} from '@/features/onboarding/onboarding-motion';

export function useAnimatedColor(targetColor: string): SharedValue<string> {
  const reducedMotion = useReducedMotion();
  const color = useSharedValue(targetColor);

  useEffect(() => {
    color.value = reducedMotion
      ? targetColor
      : withTiming(targetColor, {
          duration: getColorTransitionDuration(reducedMotion),
          easing: Easing.bezier(...ONBOARDING_COLOR_TRANSITION_EASING),
        });
  }, [color, reducedMotion, targetColor]);

  return color;
}
