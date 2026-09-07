import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import Animated, {
  useAnimatedProps,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import Svg, { Circle } from 'react-native-svg';

import { useAnimatedColor } from '@/components/ui/use-animated-color';
import { useTheme } from '@/hooks/use-theme';

const AnimatedCircle = Animated.createAnimatedComponent(Circle);

const DEFAULT_SIZE = 40;
const STROKE_WIDTH = 4;
type OnboardingProgressProps = {
  accentColor: string;
  progress: number;
  size?: number;
};

function clampProgress(progress: number) {
  return Math.min(1, Math.max(0, progress));
}

export function OnboardingProgress({
  accentColor,
  progress,
  size = DEFAULT_SIZE,
}: OnboardingProgressProps) {
  const theme = useTheme();
  const reducedMotion = useReducedMotion();
  const progressValue = useSharedValue(clampProgress(progress));
  const radius = (size - STROKE_WIDTH) / 2;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;
  const animatedAccentColor = useAnimatedColor(accentColor);

  useEffect(() => {
    const nextProgress = clampProgress(progress);

    if (reducedMotion) {
      progressValue.value = nextProgress;
      return;
    }

    progressValue.value = withTiming(nextProgress, { duration: 220 });
  }, [progress, progressValue, reducedMotion]);

  const animatedProps = useAnimatedProps(() => ({
    stroke: animatedAccentColor.value,
    strokeDashoffset: circumference * (1 - progressValue.value),
  }));

  return (
    <View
      accessibilityLabel={`Onboarding progress: ${Math.round(clampProgress(progress) * 100)} percent`}
      accessibilityRole="progressbar"
      accessibilityValue={{
        max: 100,
        min: 0,
        now: Math.round(clampProgress(progress) * 100),
      }}
      style={[styles.container, { height: size, width: size }]}>
      <Svg height={size} viewBox={`0 0 ${size} ${size}`} width={size}>
        <Circle
          cx={center}
          cy={center}
          fill="none"
          r={radius}
          stroke={theme.progressTrack}
          strokeWidth={STROKE_WIDTH}
        />
        <AnimatedCircle
          animatedProps={animatedProps}
          cx={center}
          cy={center}
          fill="none"
          r={radius}
          strokeDasharray={`${circumference} ${circumference}`}
          strokeLinecap="round"
          strokeWidth={STROKE_WIDTH}
          transform={`rotate(-90 ${center} ${center})`}
        />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
