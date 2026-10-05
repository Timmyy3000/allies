import { Image, StyleSheet, View } from 'react-native';
import Animated, {
  useAnimatedStyle,
  useDerivedValue,
} from 'react-native-reanimated';
import type { SharedValue } from 'react-native-reanimated';

import {
  ALLY_IDLE_SPRITES,
  getAllyIdleSpriteFrame,
  type AllyIdleIdentity,
} from './ally-idle-sprite-motion';

type AllyIdleSpriteProps = {
  accessibilityLabel: string;
  identity: AllyIdleIdentity;
  progress: SharedValue<number>;
  size: number;
};

const SPRITE_SOURCES = {
  boxy: require('@/assets/allies/sprites/ally-idle-boxy.png'),
  ghosty: require('@/assets/allies/sprites/ally-idle-ghosty.png'),
  rocky: require('@/assets/allies/sprites/ally-idle-rocky.png'),
  rolly: require('@/assets/allies/sprites/ally-idle-rolly.png'),
} as const;

const AnimatedImage = Animated.createAnimatedComponent(Image);

export function AllyIdleSprite({
  accessibilityLabel,
  identity,
  progress,
  size,
}: AllyIdleSpriteProps) {
  const sprite = ALLY_IDLE_SPRITES[identity];
  const frame = useDerivedValue(() =>
    getAllyIdleSpriteFrame(progress.value, sprite.frameCount),
  );
  const imageStyle = useAnimatedStyle(() => {
    const frameIndex = frame.value;
    const column = frameIndex % sprite.columns;
    const row = Math.floor(frameIndex / sprite.columns);

    return {
      transform: [
        { translateX: -column * size },
        { translateY: -row * size },
      ],
    };
  });

  return (
    <View
      accessibilityLabel={accessibilityLabel}
      accessible
      style={[styles.viewport, { height: size, width: size }]}>
      <AnimatedImage
        resizeMode="stretch"
        source={SPRITE_SOURCES[identity]}
        style={[styles.sheet, { height: size * Math.ceil(sprite.frameCount / sprite.columns), width: size * sprite.columns }, imageStyle]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    left: 0,
    position: 'absolute',
    top: 0,
  },
  viewport: {
    overflow: 'hidden',
  },
});
