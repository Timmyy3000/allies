import { useEffect, useMemo, useState } from 'react';
import { Text, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withTiming,
} from 'react-native-reanimated';

import {
  ONBOARDING_PREVIEW_FOCUS_DURATION_MS,
  getOnboardingFocusDelayMs,
  getOnboardingGreetingBlocks,
} from './onboarding-preview';

type FocusGreetingTextProps = {
  characterCount: number;
  greeting: string;
  reducedMotion: boolean;
  style: StyleProp<TextStyle>;
  boldStyle: StyleProp<TextStyle>;
};

type FocusCharacterProps = {
  character: string;
  delayMs: number;
  reducedMotion: boolean;
  style: StyleProp<TextStyle>;
};

const FOCUS_INITIAL_BLUR = 2;
const FOCUS_INITIAL_OPACITY = 0.18;
const FOCUS_EASING = Easing.bezier(0.22, 0.65, 0.3, 1);

type FocusCharactersProps = {
  characterCount: number;
  characterStart: number;
  keyPrefix: string;
  reducedMotion: boolean;
  style?: StyleProp<TextStyle>;
  text: string;
};

function FocusCharacter({ character, delayMs, reducedMotion, style }: FocusCharacterProps) {
  const [initialDelayMs] = useState(delayMs);
  const [settled, setSettled] = useState(reducedMotion);
  const progress = useSharedValue(reducedMotion ? 1 : 0);

  useEffect(() => {
    cancelAnimation(progress);

    if (reducedMotion) {
      progress.value = 1;
      return;
    }

    progress.value = withDelay(
      initialDelayMs,
      withTiming(1, {
        duration: ONBOARDING_PREVIEW_FOCUS_DURATION_MS,
        easing: FOCUS_EASING,
      }, (finished) => {
        'worklet';
        if (finished) runOnJS(setSettled)(true);
      }),
    );

    return () => cancelAnimation(progress);
  }, [initialDelayMs, progress, reducedMotion]);

  const animatedStyle = useAnimatedStyle<TextStyle>(() => {
    if (reducedMotion || settled) {
      return { opacity: 1, filter: [{ blur: 0 }] } as unknown as TextStyle;
    }

    return {
      opacity: interpolate(progress.value, [0, 1], [FOCUS_INITIAL_OPACITY, 1]),
      filter: [{ blur: interpolate(progress.value, [0, 1], [FOCUS_INITIAL_BLUR, 0]) }],
    } as unknown as TextStyle;
  }, [reducedMotion, settled, progress]);

  if (settled) return <Text style={style}>{character}</Text>;

  return <Animated.Text style={[style, animatedStyle]}>{character}</Animated.Text>;
}

function renderFocusCharacters({
  characterCount,
  characterStart,
  keyPrefix,
  reducedMotion,
  style,
  text,
}: FocusCharactersProps) {
  let characterOffset = characterStart;

  return Array.from(text).map((character, index) => {
    const glyphStart = characterOffset;
    characterOffset += character.length;
    const glyph = character === ' ' ? '\u00a0' : character;

    if (glyphStart < characterCount) {
      return (
        <FocusCharacter
          character={glyph}
          delayMs={getOnboardingFocusDelayMs(glyphStart, Math.max(0, characterCount - 1))}
          key={`${keyPrefix}-focus-${index}`}
          reducedMotion={reducedMotion}
          style={style}
        />
      );
    }

    return (
      <Text
        accessibilityElementsHidden
        key={`${keyPrefix}-hidden-${index}`}
        style={[style, styles.hiddenCharacter]}>
        {glyph}
      </Text>
    );
  });
}

export function OnboardingFocusText({
  characterCount,
  greeting,
  reducedMotion,
  style,
  boldStyle,
}: FocusGreetingTextProps) {
  const blocks = useMemo(
    () => getOnboardingGreetingBlocks(greeting),
    [greeting],
  );

  return (
    <View style={styles.greetingBlocks}>
      {blocks.map((block, blockIndex) => {
        if (block.type === 'heading') {
          return (
            <Text key={`heading-${blockIndex}`} style={boldStyle}>
              {renderFocusCharacters({
                characterCount,
                characterStart: block.textStart,
                keyPrefix: `heading-${blockIndex}`,
                reducedMotion,
                style: boldStyle,
                text: `✨ ${block.heading}`,
              })}
            </Text>
          );
        }

        if (block.type === 'bullet') {
          return (
            <View key={`bullet-${blockIndex}`} style={styles.bulletRow}>
              <Text style={[style, styles.bulletMarker]}>
                {renderFocusCharacters({
                  characterCount,
                  characterStart: block.markerStart,
                  keyPrefix: `bullet-${blockIndex}-marker`,
                  reducedMotion,
                  style,
                  text: '•',
                })}
              </Text>
              <Text style={[style, styles.bulletContent]}>
                {renderFocusCharacters({
                  characterCount,
                  characterStart: block.labelStart,
                  keyPrefix: `bullet-${blockIndex}-label`,
                  reducedMotion,
                  style: boldStyle,
                  text: block.label,
                })}
                {renderFocusCharacters({
                  characterCount,
                  characterStart: block.bodyStart - 1,
                  keyPrefix: `bullet-${blockIndex}-space`,
                  reducedMotion,
                  style,
                  text: ' ',
                })}
                {renderFocusCharacters({
                  characterCount,
                  characterStart: block.bodyStart,
                  keyPrefix: `bullet-${blockIndex}-body`,
                  reducedMotion,
                  style,
                  text: block.body,
                })}
              </Text>
            </View>
          );
        }

        return (
          <Text key={`paragraph-${blockIndex}`} style={style}>
            {renderFocusCharacters({
              characterCount,
              characterStart: block.start,
              keyPrefix: `paragraph-${blockIndex}`,
              reducedMotion,
              style,
              text: block.text,
            })}
          </Text>
        );
      })}
    </View>
  );
}

const styles = {
  bulletContent: {
    flex: 1,
  } satisfies TextStyle,
  bulletMarker: {
    flexShrink: 0,
    textAlign: 'left',
    width: 18,
  } satisfies TextStyle,
  bulletRow: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: 8,
  } satisfies ViewStyle,
  greetingBlocks: {
    gap: 18,
  } satisfies ViewStyle,
  hiddenCharacter: {
    opacity: 0,
  } satisfies TextStyle,
};
