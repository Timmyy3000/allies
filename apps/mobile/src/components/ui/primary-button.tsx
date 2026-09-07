import { StyleSheet, Text, View, type PressableProps } from 'react-native';
import Animated, { useAnimatedStyle } from 'react-native-reanimated';

import { LiquidGlassBackground } from './liquid-glass-background';
import { PressScale } from './press-scale-view';
import { useAnimatedColor } from './use-animated-color';
import { getPrimaryButtonColor } from '@/features/onboarding/onboarding-motion';
import { useTheme } from '@/hooks/use-theme';

type PrimaryButtonProps = Omit<PressableProps, 'children' | 'style'> & {
  accentColor?: string;
  bottomMargin?: number;
  labelColor?: string;
  label: string;
};

export function PrimaryButton({
  accentColor = '#FF5800',
  bottomMargin = 24,
  disabled,
  labelColor,
  label,
  ...props
}: PrimaryButtonProps) {
  const theme = useTheme();
  const animatedColor = useAnimatedColor(getPrimaryButtonColor(accentColor, Boolean(disabled), theme.inactiveButton));
  const animatedBackgroundStyle = useAnimatedStyle(() => ({
    backgroundColor: animatedColor.value,
  }));

  return (
    <PressScale
      disabled={disabled}
      {...props}
      accessibilityRole="button"
      pressableStyle={styles.button}
      pressedScale={1.03}
      style={[styles.container, { marginBottom: bottomMargin }]}>
      <Animated.View
        pointerEvents="none"
        style={[StyleSheet.absoluteFill, styles.background, animatedBackgroundStyle]}
      />
      <LiquidGlassBackground
        borderRadius={60}
        fallbackColor="transparent"
        glassEffectStyle="regular"
        isInteractive={!disabled}
        tintColor={disabled ? theme.inactiveButton : accentColor}
      />
      {disabled ? (
        <View
          pointerEvents="none"
          style={[
            StyleSheet.absoluteFill,
            styles.disabledGlassFill,
            { backgroundColor: theme.inactiveButton },
          ]}
        />
      ) : null}
      <Text
        style={[
          styles.label,
          { color: labelColor ?? (disabled ? theme.disabledButtonText : theme.buttonText) },
        ]}
      >
        {label}
      </Text>
    </PressScale>
  );
}

const styles = StyleSheet.create({
  button: {
    alignItems: 'center',
    borderRadius: 60,
    flex: 1,
    justifyContent: 'center',
    overflow: 'hidden',
    position: 'relative',
    width: '100%',
  },
  background: {
    borderRadius: 60,
  },
  container: {
    height: 48,
    width: '100%',
  },
  disabledGlassFill: {
    borderRadius: 60,
    opacity: 0.72,
  },
  label: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    letterSpacing: -0.7,
    lineHeight: 18,
  },
});
