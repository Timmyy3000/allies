import { useCallback, useEffect, type ReactNode } from 'react';
import {
  Pressable,
  type GestureResponderEvent,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';

import {
  getPressScaleTarget,
  PRESS_SCALE,
  PRESS_SCALE_DURATION_MS,
} from './press-scale';

type PressScaleProps = Omit<PressableProps, 'children' | 'style'> & {
  children: ReactNode;
  pressableStyle?: StyleProp<ViewStyle>;
  pressedScale?: number;
  style?: StyleProp<ViewStyle>;
};

export function PressScale({
  children,
  disabled = false,
  onPressIn,
  onPressOut,
  pressableStyle,
  pressedScale = PRESS_SCALE,
  style,
  ...props
}: PressScaleProps) {
  const isDisabled = Boolean(disabled);
  const reducedMotion = Boolean(useReducedMotion());
  const scale = useSharedValue(1);
  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));
  const setPressed = useCallback((pressed: boolean) => {
    scale.set(withTiming(
      getPressScaleTarget(pressed, isDisabled, reducedMotion, pressedScale),
      {
        duration: reducedMotion ? 0 : PRESS_SCALE_DURATION_MS,
        easing: Easing.out(Easing.cubic),
      },
    ));
  }, [isDisabled, pressedScale, reducedMotion, scale]);

  useEffect(() => {
    if (isDisabled || reducedMotion) scale.set(1);
  }, [isDisabled, reducedMotion, scale]);

  const handlePressIn = (event: GestureResponderEvent) => {
    setPressed(true);
    onPressIn?.(event);
  };
  const handlePressOut = (event: GestureResponderEvent) => {
    setPressed(false);
    onPressOut?.(event);
  };

  return (
    <Pressable
      disabled={disabled}
      onPressIn={handlePressIn}
      onPressOut={handlePressOut}
      style={style}
      {...props}>
      <Animated.View pointerEvents="box-none" style={[pressableStyle, animatedStyle]}>
        {children}
      </Animated.View>
    </Pressable>
  );
}
