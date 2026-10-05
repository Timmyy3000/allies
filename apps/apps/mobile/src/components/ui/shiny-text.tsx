import MaskedView from '@react-native-masked-view/masked-view';
import { useEffect, useId, useState } from 'react';
import {
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
  type StyleProp,
  type TextStyle,
} from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';
import Animated, {
  cancelAnimation,
  Easing,
  interpolate,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

type ShinyTextProps = {
  accessibilityLabel?: string;
  children: string;
  color: string;
  paused?: boolean;
  shineColor?: string;
  speed?: number;
  style: StyleProp<TextStyle>;
};

type TextSize = {
  height: number;
  width: number;
};

const DEFAULT_CYCLE_DURATION_SECONDS = 1.7;

export function ShinyText({
  accessibilityLabel,
  children,
  color,
  paused = false,
  shineColor = '#FFFFFF',
  speed = DEFAULT_CYCLE_DURATION_SECONDS,
  style,
}: ShinyTextProps) {
  const reducedMotion = Boolean(useReducedMotion());
  const [textSize, setTextSize] = useState<TextSize>({ height: 1, width: 1 });
  const shineProgress = useSharedValue(0);
  const gradientId = useId().replace(/:/g, '');
  const safeSpeed = Number.isFinite(speed) && speed > 0 ? speed : DEFAULT_CYCLE_DURATION_SECONDS;
  const gradientWidth = Math.max(2, textSize.width * 2);

  useEffect(() => {
    cancelAnimation(shineProgress);

    if (reducedMotion || paused) {
      shineProgress.value = 0;
      return;
    }

    shineProgress.value = withRepeat(
      withTiming(1, {
        duration: safeSpeed * 1000,
        easing: Easing.linear,
      }),
      -1,
      false,
    );

    return () => cancelAnimation(shineProgress);
  }, [paused, reducedMotion, safeSpeed, shineProgress]);

  const shineStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(
          shineProgress.value,
          [0, 1],
          [textSize.width * -1.5, textSize.width * 0.5],
        ),
      },
    ],
  }), [textSize.width]);

  const handleTextLayout = ({ nativeEvent: { layout } }: LayoutChangeEvent) => {
    if (layout.width === textSize.width && layout.height === textSize.height) return;
    setTextSize({ height: Math.max(1, layout.height), width: Math.max(1, layout.width) });
  };

  return (
    <View
      accessible
      accessibilityLabel={accessibilityLabel ?? children}
      accessibilityRole="text"
      onLayout={handleTextLayout}
      style={styles.root}>
      <Text
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        numberOfLines={1}
        style={[style, styles.measurement]}>
        {children}
      </Text>
      <MaskedView
        pointerEvents="none"
        style={StyleSheet.absoluteFill}
        maskElement={
          <Text
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
            numberOfLines={1}
            style={[style, styles.mask]}>
            {children}
          </Text>
        }>
        <View style={[StyleSheet.absoluteFill, { backgroundColor: color }]}>
          {!reducedMotion && !paused ? (
            <Animated.View
              style={[styles.gradientTrack, { height: textSize.height, width: gradientWidth }, shineStyle]}>
              <Svg height={textSize.height} width={gradientWidth}>
                <Defs>
                  <LinearGradient id={gradientId} x1="0%" x2="100%" y1="0%" y2="0%">
                    <Stop offset="0%" stopColor={color} />
                    <Stop offset="35%" stopColor={color} />
                    <Stop offset="50%" stopColor={shineColor} />
                    <Stop offset="65%" stopColor={color} />
                    <Stop offset="100%" stopColor={color} />
                  </LinearGradient>
                </Defs>
                <Rect fill={`url(#${gradientId})`} height="100%" width="100%" />
              </Svg>
            </Animated.View>
          ) : null}
        </View>
      </MaskedView>
    </View>
  );
}

const styles = StyleSheet.create({
  gradientTrack: {
    left: 0,
    position: 'absolute',
    top: 0,
  },
  mask: {
    color: '#FFFFFF',
  },
  measurement: {
    opacity: 0,
  },
  root: {
    alignSelf: 'flex-start',
    position: 'relative',
  },
});
