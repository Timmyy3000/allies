import { Pressable, StyleSheet, Text, type PressableProps } from 'react-native';
import Animated, { useAnimatedStyle } from 'react-native-reanimated';

import { useAnimatedColor } from './use-animated-color';
import { getPrimaryButtonColor } from '@/features/onboarding/onboarding-motion';

type PrimaryButtonProps = Omit<PressableProps, 'children' | 'style'> & {
  accentColor?: string;
  bottomMargin?: number;
  label: string;
};

export function PrimaryButton({
  accentColor = '#FF5800',
  bottomMargin = 24,
  disabled,
  label,
  ...props
}: PrimaryButtonProps) {
  const animatedColor = useAnimatedColor(getPrimaryButtonColor(accentColor, Boolean(disabled)));
  const animatedBackgroundStyle = useAnimatedStyle(() => ({
    backgroundColor: animatedColor.value,
  }));

  return (
    <Pressable
      disabled={disabled}
      {...props}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.button,
        { marginBottom: bottomMargin },
        pressed && !disabled && styles.buttonPressed,
      ]}>
      <Animated.View
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, styles.background, animatedBackgroundStyle]}
      />
      <Text style={styles.label}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    borderRadius: 60,
    height: 48,
    justifyContent: 'center',
    position: 'relative',
    width: '100%',
  },
  background: {
    borderRadius: 60,
  },
  buttonPressed: {
    opacity: 0.88,
    transform: [{ scale: 0.985 }],
  },
  label: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    letterSpacing: -0.7,
    lineHeight: 24,
  },
});
