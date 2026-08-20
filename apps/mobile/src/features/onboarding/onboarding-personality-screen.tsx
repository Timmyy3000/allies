import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import Animated, { useAnimatedStyle } from 'react-native-reanimated';

import { useAnimatedColor } from '@/components/ui/use-animated-color';

import {
  PERSONALITIES,
  type Personality,
} from './onboarding-state';
import { getMutedOnboardingColor } from './onboarding-motion';

const AnimatedText = Animated.createAnimatedComponent(Text);

type OnboardingPersonalityScreenProps = {
  accentColor: string;
  personalityNote: string;
  personalities: readonly Personality[];
  onPersonalityNoteChange: (value: string) => void;
  onTogglePersonality: (personality: Personality) => void;
};

type PersonalityChipProps = {
  accentColor: string;
  mutedColor: string;
  onPress: () => void;
  personality: Personality;
  selected: boolean;
};

function PersonalityChip({
  accentColor,
  mutedColor,
  onPress,
  personality,
  selected,
}: PersonalityChipProps) {
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
      accessibilityLabel={`${selected ? 'Remove' : 'Choose'} ${personality} personality`}
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, pressed && styles.chipPressed]}>
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.chipBackground, backgroundStyle]} />
      <AnimatedText style={[styles.chipText, textStyle]}>{personality}</AnimatedText>
    </Pressable>
  );
}

export function OnboardingPersonalityScreen({
  accentColor,
  personalityNote,
  personalities,
  onPersonalityNoteChange,
  onTogglePersonality,
}: OnboardingPersonalityScreenProps) {
  const [showHelp, setShowHelp] = useState(false);
  const mutedColor = getMutedOnboardingColor(accentColor);
  const animatedEditorBackground = useAnimatedColor(mutedColor);
  const editorBackgroundStyle = useAnimatedStyle(() => ({
    backgroundColor: animatedEditorBackground.value,
  }));
  const remaining = 200 - personalityNote.length;
  const filled = personalityNote.trim().length > 0;

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={styles.root}>
      {showHelp ? (
        <View style={styles.helpStack}>
          <Pressable
            accessibilityLabel="Close personality help"
            accessibilityRole="button"
            onPress={() => setShowHelp(false)}
            style={[styles.helpClose, { backgroundColor: mutedColor }]}>
            <Text style={styles.helpCloseText}>×</Text>
          </Pressable>
          <View style={[styles.helpCard, { backgroundColor: accentColor }]}>
            <Text style={styles.helpText}>
              My personality describes what it feels like to work with me. It shapes how I speak, explain things, encourage you, challenge you, and respond when something is unclear.
            </Text>
            <Text style={[styles.helpText, styles.helpTextSecond]}>
              Describe the kind of Ally you want me to be. It changes my style, not my job or what I can access.
            </Text>
          </View>
        </View>
      ) : (
        <View style={styles.stack}>
          <ScrollView
            contentContainerStyle={styles.chipRow}
            horizontal
            showsHorizontalScrollIndicator={false}>
            <Pressable
              accessibilityLabel="Learn about personality"
              accessibilityRole="button"
              onPress={() => setShowHelp(true)}
              style={[
                styles.helpTrigger,
                { backgroundColor: mutedColor, borderColor: accentColor },
              ]}
            >
              <Text style={[styles.helpTriggerText, { color: accentColor }]}>?</Text>
            </Pressable>
            {PERSONALITIES.map((personality) => (
              <PersonalityChip
                accentColor={accentColor}
                mutedColor={mutedColor}
                key={personality}
                onPress={() => onTogglePersonality(personality)}
                personality={personality}
                selected={personalities.includes(personality)}
              />
            ))}
          </ScrollView>

          <Animated.View style={[styles.editorCard, editorBackgroundStyle]}>
            <TextInput
              accessibilityLabel="Personality note"
              maxLength={200}
              multiline
              onChangeText={onPersonalityNoteChange}
              placeholder="How should I speak and respond to you?"
              placeholderTextColor="#A8A8A8"
              style={styles.input}
              textAlignVertical="top"
              value={personalityNote}
            />
          </Animated.View>
          <Text style={styles.counter}>
            {filled ? `${remaining} characters left` : '200 character limit'}
          </Text>
        </View>
      )}
    </KeyboardAvoidingView>
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
  chipRow: {
    alignItems: 'center',
    gap: 12,
    paddingRight: 20,
  },
  chipText: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    letterSpacing: -0.43,
    lineHeight: 20,
  },
  counter: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    letterSpacing: -0.45,
    lineHeight: 18,
    marginTop: 18,
    textAlign: 'center',
  },
  editorCard: {
    backgroundColor: '#F3F3F3',
    borderRadius: 20,
    height: 250,
    marginTop: 12,
    overflow: 'hidden',
  },
  helpCard: {
    borderRadius: 20,
    minHeight: 233,
    paddingHorizontal: 16,
    paddingVertical: 18,
  },
  helpClose: {
    alignItems: 'center',
    backgroundColor: '#F3F3F3',
    borderRadius: 18,
    height: 36,
    justifyContent: 'center',
    width: 36,
  },
  helpCloseText: {
    color: '#121212',
    fontFamily: 'OpenRundeMedium',
    fontSize: 28,
    lineHeight: 28,
    marginTop: -3,
  },
  helpStack: {
    gap: 12,
    marginTop: 'auto',
    paddingBottom: 17,
  },
  helpText: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    letterSpacing: -0.48,
    lineHeight: 20,
  },
  helpTextSecond: {
    marginTop: 20,
  },
  input: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    includeFontPadding: false,
    letterSpacing: -0.48,
    lineHeight: 22,
    minHeight: 250,
    paddingHorizontal: 14,
    paddingTop: 18,
  },
  helpTrigger: {
    alignItems: 'center',
    borderRadius: 18,
    borderWidth: 2,
    height: 36,
    justifyContent: 'center',
    width: 36,
  },
  helpTriggerText: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 20,
    lineHeight: 20,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  stack: {
    marginTop: 'auto',
    paddingBottom: 17,
  },
});
