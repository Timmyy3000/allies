import { useMemo } from 'react';
import { Text, View, type StyleProp, type TextStyle, type ViewStyle } from 'react-native';

import {
  getOnboardingGreetingBlocks,
  getVisibleOnboardingGreeting,
} from './onboarding-preview';

type OnboardingTypewriterTextProps = {
  boldStyle: StyleProp<TextStyle>;
  characterCount: number;
  greeting: string;
  style: StyleProp<TextStyle>;
};

function getVisibleBlockText(text: string, start: number, characterCount: number) {
  return getVisibleOnboardingGreeting(text, characterCount - start);
}

export function OnboardingTypewriterText({
  boldStyle,
  characterCount,
  greeting,
  style,
}: OnboardingTypewriterTextProps) {
  const blocks = useMemo(() => getOnboardingGreetingBlocks(greeting), [greeting]);

  return (
    <View style={styles.greetingBlocks}>
      {blocks.map((block, blockIndex) => {
        const blockStart = block.type === 'bullet' ? block.markerStart : block.start;
        if (characterCount <= blockStart) return null;

        if (block.type === 'heading') {
          const heading = getVisibleBlockText(
            `🌟 ${block.heading}`,
            block.textStart,
            characterCount,
          );

          return (
            <Text key={`heading-${blockIndex}`} style={boldStyle}>
              {heading}
            </Text>
          );
        }

        if (block.type === 'bullet') {
          const label = getVisibleBlockText(block.label, block.labelStart, characterCount);
          const body = getVisibleBlockText(block.body, block.bodyStart, characterCount);
          const bodySpace = characterCount > block.bodyStart - 1 ? ' ' : '';

          return (
            <View key={`bullet-${blockIndex}`} style={styles.bulletRow}>
              <Text style={[style, styles.bulletMarker]}>•</Text>
              <Text style={[style, styles.bulletContent]}>
                <Text style={boldStyle}>{label}</Text>
                {bodySpace}
                {body}
              </Text>
            </View>
          );
        }

        return (
          <Text key={`paragraph-${blockIndex}`} style={style}>
            {getVisibleBlockText(block.text, block.start, characterCount)}
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
};
