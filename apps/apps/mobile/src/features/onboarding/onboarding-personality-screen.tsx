import { useState } from 'react';
import { Image } from 'expo-image';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';
import Animated, { useAnimatedStyle } from 'react-native-reanimated';

import { LiquidGlassBackground } from '@/components/ui/liquid-glass-background';
import { useTheme } from '@/hooks/use-theme';

import {
  ONBOARDING_PERSONALITY_CHIP_GAP,
  ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE,
  ONBOARDING_PERSONALITY_HELP_CARD_MIN_HEIGHT,
  ONBOARDING_PERSONALITY_HELP_ICON_SIZE,
  ONBOARDING_PERSONALITY_HELP_TO_CHIP_GAP,
  ONBOARDING_PERSONALITY_ROW_INSET,
  getOnboardingEdgeToEdgeStyle,
} from './onboarding-layout';
import { PERSONALITIES, type Personality } from './onboarding-state';
import {
  ONBOARDING_EDITOR_HEIGHT,
  ONBOARDING_EDITOR_REGION_HEIGHT,
  getMutedOnboardingColor,
  getOnboardingPersonalitySelectorOffset,
} from './onboarding-motion';
import { OnboardingSelectorChip } from './onboarding-selector-chip';
import { useOnboardingEditorHeight } from './use-onboarding-editor-height';

type OnboardingPersonalityScreenProps = {
  accentColor: string;
  personalityNote: string;
  personalities: readonly Personality[];
  onPersonalityNoteChange: (value: string) => void;
  onHelpVisibilityChange: (open: boolean) => void;
  onTogglePersonality: (personality: Personality) => void;
};

export function OnboardingPersonalityScreen({
  accentColor,
  personalityNote,
  personalities,
  onHelpVisibilityChange,
  onPersonalityNoteChange,
  onTogglePersonality,
}: OnboardingPersonalityScreenProps) {
  const theme = useTheme();
  const {
    editorRef,
    editorStyle,
    keyboardProgress,
    keyboardVisible,
    onEditorLayout,
  } = useOnboardingEditorHeight();
  const { width: windowWidth } = useWindowDimensions();
  const [showHelp, setShowHelp] = useState(false);
  const edgeToEdgeStyle = getOnboardingEdgeToEdgeStyle(windowWidth);
  const mutedColor = getMutedOnboardingColor(accentColor);
  const remaining = 200 - personalityNote.length;
  const filled = personalityNote.trim().length > 0;
  const personalitySelectorStyle = useAnimatedStyle(() => ({
    transform: [{
      translateY: getOnboardingPersonalitySelectorOffset(keyboardProgress.value),
    }],
  }));

  const content = (
    <ScrollView
      contentContainerStyle={styles.rootContent}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
      style={[styles.root, { backgroundColor: theme.appBackground }, edgeToEdgeStyle]}>
      {showHelp ? (
        <View style={styles.helpStack}>
          <Pressable
            accessibilityLabel="Close personality help"
            accessibilityRole="button"
            onPress={() => {
              setShowHelp(false);
              onHelpVisibilityChange(false);
            }}
            style={styles.helpClose}>
            <LiquidGlassBackground
              borderRadius={18}
              fallbackColor={mutedColor}
            />
            <Image
              accessibilityLabel=""
              contentFit="contain"
              source={require('@/assets/allies/icons/x-icon.svg')}
              style={[styles.helpCloseIcon, { tintColor: theme.primaryText }]}
            />
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
          <Animated.ScrollView
            contentContainerStyle={styles.chipRow}
            horizontal
            showsHorizontalScrollIndicator={false}
            style={[edgeToEdgeStyle, personalitySelectorStyle]}>
            <Pressable
              accessibilityLabel="Learn about personality"
              accessibilityRole="button"
              onPress={() => {
                setShowHelp(true);
                onHelpVisibilityChange(true);
              }}
            style={[styles.helpTrigger, { backgroundColor: theme.controlSurface }]}
            >
              <View style={[styles.helpTriggerIcon, { borderColor: accentColor }]}>
                <Text style={[styles.helpTriggerText, { color: accentColor }]}>?</Text>
              </View>
            </Pressable>
            {PERSONALITIES.map((personality) => (
              <OnboardingSelectorChip
                accessibilityLabel={`${personalities.includes(personality) ? 'Remove' : 'Choose'} ${personality} personality`}
                accentColor={accentColor}
                label={personality}
                mutedColor={mutedColor}
                key={personality}
                onPress={() => onTogglePersonality(personality)}
                selected={personalities.includes(personality)}
              />
            ))}
          </Animated.ScrollView>

          <View
            onLayout={onEditorLayout}
            pointerEvents="box-none"
            ref={editorRef}
            style={styles.editorRegion}>
            <Animated.View style={[styles.editorCard, editorStyle]}>
              <LiquidGlassBackground
                borderRadius={20}
                fallbackColor={theme.onboardingInput}
                tintColor={getMutedOnboardingColor(accentColor, 0.02)}
              />
              <TextInput
                accessibilityLabel="Personality note"
                maxLength={200}
                multiline
                onChangeText={onPersonalityNoteChange}
                placeholder="How should I speak and respond to you?"
                placeholderTextColor="#A8A8A8"
                scrollEnabled
                style={[styles.input, { color: theme.primaryText }]}
                textAlignVertical="top"
                value={personalityNote}
              />
            </Animated.View>
            {!keyboardVisible ? (
              <Text style={[styles.counter, { color: theme.primaryText }]}>
                {filled ? `${remaining} characters left` : '200 character limit'}
              </Text>
            ) : null}
          </View>
        </View>
      )}
    </ScrollView>
  );

  return Platform.OS === 'ios' ? (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      {content}
    </View>
  ) : (
    <KeyboardAvoidingView behavior="height" style={styles.root}>
      {content}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  chipRow: {
    alignItems: 'center',
    gap: ONBOARDING_PERSONALITY_CHIP_GAP,
    paddingLeft: ONBOARDING_PERSONALITY_ROW_INSET,
    paddingRight: 20,
  },
  counter: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    letterSpacing: -0.45,
    lineHeight: 18,
    marginTop: 18,
    textAlign: 'center',
  },
  editorCard: {
    borderRadius: 20,
    height: ONBOARDING_EDITOR_HEIGHT,
    overflow: 'hidden',
  },
  editorRegion: {
    height: ONBOARDING_EDITOR_REGION_HEIGHT,
    marginTop: 12,
  },
  helpCard: {
    borderRadius: 20,
    minHeight: ONBOARDING_PERSONALITY_HELP_CARD_MIN_HEIGHT,
    paddingHorizontal: 16,
    paddingVertical: 18,
  },
  helpClose: {
    alignItems: 'center',
    borderRadius: 18,
    height: 36,
    justifyContent: 'center',
    overflow: 'hidden',
    width: 36,
  },
  helpCloseIcon: {
    height: 10.5,
    width: 10.5,
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
    flex: 1,
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    includeFontPadding: false,
    letterSpacing: -0.48,
    lineHeight: 22,
    paddingHorizontal: 14,
    paddingTop: 18,
  },
  helpTrigger: {
    alignItems: 'center',
    borderRadius: ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE / 2,
    height: ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE,
    justifyContent: 'center',
    marginRight:
      ONBOARDING_PERSONALITY_HELP_TO_CHIP_GAP - ONBOARDING_PERSONALITY_CHIP_GAP,
    width: ONBOARDING_PERSONALITY_HELP_CONTROL_SIZE,
  },
  helpTriggerIcon: {
    alignItems: 'center',
    borderRadius: ONBOARDING_PERSONALITY_HELP_ICON_SIZE / 2,
    borderWidth: 2,
    height: ONBOARDING_PERSONALITY_HELP_ICON_SIZE,
    justifyContent: 'center',
    width: ONBOARDING_PERSONALITY_HELP_ICON_SIZE,
  },
  helpTriggerText: {
    includeFontPadding: false,
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    lineHeight: 18,
    textAlign: 'center',
  },
  root: {
    flex: 1,
  },
  rootContent: {
    flexGrow: 1,
    paddingHorizontal: ONBOARDING_PERSONALITY_ROW_INSET,
  },
  stack: {
    marginTop: 'auto',
    paddingBottom: 17,
  },
});
