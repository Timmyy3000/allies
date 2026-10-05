import { Image } from 'expo-image';
import { useEffect } from 'react';
import { StyleSheet } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';

import { useAnimatedColor } from '@/components/ui/use-animated-color';
import { useTheme } from '@/hooks/use-theme';

import {
  ONBOARDING_COLOR_TRANSITION_EASING,
  getColorTransitionDuration,
} from './onboarding-motion';
import type { AllyShape } from './onboarding-state';

const SOURCES = {
  idle: {
    boxy: {
      animated: require('@/assets/allies/characters/idle_boxy.svg'),
      reduced: require('@/assets/allies/characters/idle_boxy.reduced.svg'),
    },
    ghosty: {
      animated: require('@/assets/allies/characters/idle_ghosty.svg'),
      reduced: require('@/assets/allies/characters/idle_ghosty.reduced.svg'),
    },
    rocky: {
      animated: require('@/assets/allies/characters/idle_rocky.svg'),
      reduced: require('@/assets/allies/characters/idle_rocky.reduced.svg'),
    },
    rolly: {
      animated: require('@/assets/allies/characters/idle_rolly.svg'),
      reduced: require('@/assets/allies/characters/idle_rolly.reduced.svg'),
    },
  },
  thinking: {
    boxy: {
      animated: require('@/assets/allies/characters/thinking_boxy.svg'),
      reduced: require('@/assets/allies/characters/thinking_boxy.reduced.svg'),
    },
    ghosty: {
      animated: require('@/assets/allies/characters/thinking_ghosty.svg'),
      reduced: require('@/assets/allies/characters/thinking_ghosty.reduced.svg'),
    },
    rocky: {
      animated: require('@/assets/allies/characters/thinking_rocky.svg'),
      reduced: require('@/assets/allies/characters/thinking_rocky.reduced.svg'),
    },
    rolly: {
      animated: require('@/assets/allies/characters/thinking_rolly.svg'),
      reduced: require('@/assets/allies/characters/thinking_rolly.reduced.svg'),
    },
  },
} as const;

export type OnboardingAllyAnimationState = keyof typeof SOURCES;

type OnboardingAllyPreviewProps = {
  accessibilityLabel: string;
  color: string | null;
  identity: AllyShape;
  size: number;
  shellSize?: number;
  state?: OnboardingAllyAnimationState;
  artworkScale?: number;
  allowDownscaling?: boolean;
};

export function OnboardingAllyPreview({
  accessibilityLabel,
  color,
  identity,
  size,
  shellSize,
  state = 'idle',
  artworkScale,
  allowDownscaling,
}: OnboardingAllyPreviewProps) {
  const theme = useTheme();
  const effectiveArtworkScale = artworkScale ?? (color ? 0.86 : 1);
  const animatedShellColor = useAnimatedColor(color ?? theme.appBackground);
  const reducedMotion = useReducedMotion();
  const animatedArtworkScale = useSharedValue(effectiveArtworkScale);

  useEffect(() => {
    animatedArtworkScale.value = reducedMotion
      ? effectiveArtworkScale
      : withTiming(effectiveArtworkScale, {
          duration: getColorTransitionDuration(reducedMotion),
          easing: Easing.bezier(...ONBOARDING_COLOR_TRANSITION_EASING),
        });
  }, [animatedArtworkScale, effectiveArtworkScale, reducedMotion]);

  const shellStyle = useAnimatedStyle(() => ({
    backgroundColor: animatedShellColor.value,
  }));
  const artworkStyle = useAnimatedStyle(() => ({
    transform: [{ scale: animatedArtworkScale.value }],
  }));
  const source = SOURCES[state][identity][reducedMotion ? 'reduced' : 'animated'];

  return (
    <Animated.View
      accessible
      accessibilityLabel={accessibilityLabel}
      style={[styles.shell, { height: shellSize ?? size, width: shellSize ?? size }, shellStyle]}>
      <Animated.View style={[{ height: size, width: size }, artworkStyle]}>
        <Image
          allowDownscaling={allowDownscaling}
          contentFit="contain"
          source={source}
          style={styles.artwork}
        />
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  artwork: {
    height: '100%',
    width: '100%',
  },
  shell: {
    alignItems: 'center',
    borderRadius: 999,
    justifyContent: 'center',
    overflow: 'hidden',
  },
});
