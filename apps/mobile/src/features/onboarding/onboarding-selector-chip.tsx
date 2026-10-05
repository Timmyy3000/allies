import { Pressable, StyleSheet, Text } from 'react-native';
import Animated, { useAnimatedStyle } from 'react-native-reanimated';

import { useAnimatedColor } from '@/components/ui/use-animated-color';

const AnimatedText = Animated.createAnimatedComponent(Text);

type OnboardingSelectorChipProps = {
  accessibilityLabel: string;
  accentColor: string;
  label: string;
  mutedColor: string;
  onPress: () => void;
  selected: boolean;
};

export function OnboardingSelectorChip({
  accessibilityLabel,
  accentColor,
  label,
  mutedColor,
  onPress,
  selected,
}: OnboardingSelectorChipProps) {
  const animatedBackground = useAnimatedColor(selected ? accentColor : mutedColor);
  const animatedText = useAnimatedColor(selected ? '#FFFFFF' : accentColor);
  const backgroundStyle = useAnimatedStyle(() => ({
    backgroundColor: animatedBackground.value,
  }));
  const textStyle = useAnimatedStyle(() => ({
    color: animatedText.value,
  }));

  return (
    <Pressable
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, pressed && styles.chipPressed]}>
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.chipBackground, backgroundStyle]} />
      <AnimatedText style={[styles.chipText, textStyle]}>{label}</AnimatedText>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    alignItems: 'center',
    borderRadius: 100,
    height: 36,
    justifyContent: 'center',
    minWidth: 84,
    overflow: 'hidden',
    paddingHorizontal: 24,
  },
  chipBackground: {
    borderRadius: 100,
  },
  chipPressed: {
    opacity: 0.8,
  },
  chipText: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    letterSpacing: -0.43,
    lineHeight: 20,
  },
});
