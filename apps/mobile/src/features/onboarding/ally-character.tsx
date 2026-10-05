import { useEffect } from 'react';
import { Image } from 'expo-image';
import { StyleSheet, View, useWindowDimensions } from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useDerivedValue,
  useReducedMotion,
  useSharedValue,
  withDelay,
  withTiming,
} from 'react-native-reanimated';
import type { SharedValue } from 'react-native-reanimated';

import { AllyPointer } from './ally-pointer';
import {
  ENTRANCE_CURVES,
  ENTRANCE_DELAYS_MS,
  ENTRANCE_DURATION_MS,
  ENTRANCE_EASING,
  getCubicTangent,
  getCubicPoint,
  getIdleHoverOffset,
  getOrbitPoint,
} from './ally-entrance-motion';
import { FLOATING_ALLIES, type FloatingAlly } from './onboarding-characters';

const REFERENCE_WIDTH = 330;
const BASE_POINTER_SIZE = 27;

const IDLE_GIF_SOURCES = {
  boxy: require('@/assets/allies/gifs/ally-idle-boxy.gif'),
  ghosty: require('@/assets/allies/gifs/ally-idle-ghosty.gif'),
  rocky: require('@/assets/allies/gifs/ally-idle-rocky.gif'),
  rolly: require('@/assets/allies/gifs/ally-idle-rolly.gif'),
} as const;

const ARTWORK_LAYOUT = {
  boxy: { width: 0.72, height: 0.72 },
  ghosty: { width: 0.72, height: 0.76 },
  rocky: { width: 0.82, height: 0.74 },
  rolly: { width: 0.76, height: 0.76 },
} as const;

const ENTRANCE_MOTION = {
  blue: {
    delay: ENTRANCE_DELAYS_MS.blue,
    curve: ENTRANCE_CURVES.blue,
    rotation: -14,
    phase: 0.2,
    easing: 'standard',
  },
  yellow: {
    delay: ENTRANCE_DELAYS_MS.yellow,
    curve: ENTRANCE_CURVES.yellow,
    rotation: 14,
    phase: 1.8,
    easing: 'standard',
  },
  green: {
    delay: ENTRANCE_DELAYS_MS.green,
    curve: ENTRANCE_CURVES.green,
    rotation: 10,
    phase: 3.4,
    easing: 'soft',
  },
  pink: {
    delay: ENTRANCE_DELAYS_MS.pink,
    curve: ENTRANCE_CURVES.pink,
    rotation: -12,
    phase: 5.1,
    easing: 'standard',
  },
} as const;

type AllyCharacterProps = {
  ally: FloatingAlly;
  idleProgress: SharedValue<number>;
};

function clamp(value: number, minimum: number, maximum: number) {
  'worklet';
  return Math.min(maximum, Math.max(minimum, value));
}

export function AllyCharacter({ ally, idleProgress }: AllyCharacterProps) {
  const { width } = useWindowDimensions();
  const reducedMotion = useReducedMotion();
  const entranceProgress = useSharedValue(reducedMotion ? 1 : 0);
  const motion = ENTRANCE_MOTION[ally.color];

  const scale = width / REFERENCE_WIDTH;
  const allySize = ally.size * scale;
  const pointerSize = BASE_POINTER_SIZE * scale;
  const pointerRadius = allySize / 2 + pointerSize * 1.15;
  const artworkLayout = ARTWORK_LAYOUT[ally.identity];
  const artworkWidth = allySize * artworkLayout.width;
  const artworkHeight = allySize * artworkLayout.height;

  useEffect(() => {
    if (reducedMotion) {
      entranceProgress.value = 1;
      return;
    }

    entranceProgress.value = 0;
    entranceProgress.value = withDelay(
      motion.delay,
      withTiming(1, {
        duration: ENTRANCE_DURATION_MS,
        easing:
          motion.easing === 'soft'
            ? Easing.bezier(
                ENTRANCE_EASING.soft.x1,
                ENTRANCE_EASING.soft.y1,
                ENTRANCE_EASING.soft.x2,
                ENTRANCE_EASING.soft.y2,
              )
            : Easing.bezier(
                ENTRANCE_EASING.standard.x1,
                ENTRANCE_EASING.standard.y1,
                ENTRANCE_EASING.standard.x2,
                ENTRANCE_EASING.standard.y2,
              ),
      }),
    );

    return () => cancelAnimation(entranceProgress);
  }, [entranceProgress, motion.delay, motion.easing, reducedMotion]);

  const motionValues = useDerivedValue(() => {
    const entrance = clamp(entranceProgress.value, 0, 1);
    const easedEntrance = 1 - Math.pow(1 - entrance, 3);
    const entrancePoint = getCubicPoint(motion.curve, easedEntrance);
    const tangent = getCubicTangent(motion.curve, easedEntrance);
    const travelAngle = Math.atan2(tangent.y, tangent.x);
    const idle = getIdleHoverOffset(idleProgress.value, motion.phase);
    const cursorIntro = clamp(easedEntrance / 0.14, 0, 1);
    const cursorOutro = clamp((1 - easedEntrance) / 0.18, 0, 1);
    const cursorProgress = Math.min(cursorIntro, cursorOutro);
    const cursorRadius =
      allySize / 2 + (pointerRadius - allySize / 2) * cursorProgress;
    const cursorPosition = getOrbitPoint(travelAngle, cursorRadius);
    const anticipation = Math.sin(Math.PI * clamp(easedEntrance / 0.14, 0, 1));
    const settling = Math.sin(
      Math.PI * clamp((easedEntrance - 0.84) / 0.16, 0, 1),
    );
    const squash = anticipation * 0.06 - settling * 0.05;

    return {
      positionX: entrancePoint.x + idle.x * entrance,
      positionY: entrancePoint.y + idle.y * entrance,
      rotation: motion.rotation * (1 - easedEntrance) + idle.rotation * entrance,
      cursorAngle: (travelAngle * 180) / Math.PI,
      cursorOpacity: reducedMotion ? 0 : cursorProgress,
      cursorX: cursorPosition.x,
      cursorY: cursorPosition.y,
      cursorScale: 0.2 + cursorProgress * 0.8,
      scaleX: 1 + squash,
      scaleY: 1 - squash,
    };
  });

  const actorStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: motionValues.value.positionX },
      { translateY: motionValues.value.positionY },
      { rotate: `${motionValues.value.rotation}deg` },
      { scaleX: motionValues.value.scaleX },
      { scaleY: motionValues.value.scaleY },
    ],
  }));

  const pointerStyle = useAnimatedStyle(() => ({
    opacity: motionValues.value.cursorOpacity,
    transform: [
      { translateX: motionValues.value.cursorX },
      { translateY: motionValues.value.cursorY },
      { scale: motionValues.value.cursorScale },
      { rotate: `${motionValues.value.cursorAngle}deg` },
    ],
  }));

  return (
    <Animated.View
      style={[
        styles.actor,
        {
          height: allySize,
          left: ally.left,
          right: ally.right,
          top: ally.top,
          width: allySize,
        },
        actorStyle,
      ]}>
      <Animated.View
        pointerEvents="none"
        style={[
          styles.pointer,
          {
            height: pointerSize,
            left: allySize / 2 - pointerSize / 2,
            top: allySize / 2 - pointerSize / 2,
            width: pointerSize,
          },
          pointerStyle,
        ]}>
        <AllyPointer color={ally.tint} rotation={0} size={pointerSize} />
      </Animated.View>

      <View style={[styles.orb, { backgroundColor: ally.tint }]}>
        <Image
          accessibilityLabel={`${ally.color} Ally`}
          autoplay={!reducedMotion}
          cachePolicy="memory-disk"
          contentFit="contain"
          source={IDLE_GIF_SOURCES[ally.identity]}
          style={{ height: artworkHeight, width: artworkWidth }}
        />
      </View>
    </Animated.View>
  );
}

export { FLOATING_ALLIES };

const styles = StyleSheet.create({
  actor: {
    overflow: 'visible',
    position: 'absolute',
    zIndex: 2,
  },
  orb: {
    alignItems: 'center',
    borderRadius: 999,
    height: '100%',
    justifyContent: 'center',
    overflow: 'hidden',
    width: '100%',
  },
  pointer: {
    position: 'absolute',
    zIndex: 2,
  },
});
