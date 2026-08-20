import { StatusBar } from 'expo-status-bar';
import { Image } from 'expo-image';
import { useEffect, useMemo, useState } from 'react';
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
import Animated, {
  Easing,
  FadeIn,
  useAnimatedStyle,
  useReducedMotion,
} from 'react-native-reanimated';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { useAnimatedColor } from '@/components/ui/use-animated-color';

import { OnboardingAllyPreview } from './onboarding-ally-preview';
import {
  getNextOnboardingPreviewPhase,
  getOnboardingGreeting,
  getVisibleOnboardingGreeting,
  ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS,
  ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS,
  ONBOARDING_PREVIEW_THINKING_DELAY_MS,
  type OnboardingPreviewPhase,
} from './onboarding-preview';
import type { AllyColorValue, AllyShape } from './onboarding-state';

const HERO_SIZE = 164;
const CONVERSATION_HEADER_AVATAR_SIZE = 24;
const THINKING_AVATAR_SIZE = 28;
const COMPOSER_MIN_HEIGHT = 48;
const COMPOSER_MAX_HEIGHT = 96;
const PREVIEW_EASING = [0.32, 0.72, 0, 1] as const;

type OnboardingPreviewScreenProps = {
  allyName: string;
  allyShape: AllyShape;
  selectedColor: AllyColorValue | null;
};

export function OnboardingPreviewScreen({
  allyName,
  allyShape,
  selectedColor,
}: OnboardingPreviewScreenProps) {
  const [phase, setPhase] = useState<OnboardingPreviewPhase>('coming-alive');
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    const timer = setTimeout(
      () => setPhase(getNextOnboardingPreviewPhase('coming-alive')),
      reducedMotion ? 0 : ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS,
    );

    return () => clearTimeout(timer);
  }, [reducedMotion]);

  useEffect(() => {
    if (phase !== 'thinking') return;

    const timer = setTimeout(
      () => setPhase(getNextOnboardingPreviewPhase('thinking')),
      reducedMotion ? 0 : ONBOARDING_PREVIEW_THINKING_DELAY_MS,
    );

    return () => clearTimeout(timer);
  }, [phase, reducedMotion]);

  if (phase === 'coming-alive') {
    return (
      <View style={styles.root}>
        <StatusBar style="dark" />
        <SafeAreaView edges={['top', 'bottom']} style={styles.comingAliveSafeArea}>
          <View style={styles.comingAliveContent}>
            <Animated.View
              entering={
                reducedMotion
                  ? undefined
                  : FadeIn.duration(260).easing(Easing.bezier(...PREVIEW_EASING))
              }>
              <OnboardingAllyPreview
                accessibilityLabel={`${allyName || 'Your'} Ally coming alive`}
                artworkScale={0.86}
                color={selectedColor}
                identity={allyShape}
                size={HERO_SIZE}
              />
            </Animated.View>
            <Text style={styles.comingAliveLabel}>Coming alive....</Text>
          </View>
        </SafeAreaView>
      </View>
    );
  }

  return (
    <ConversationPreview
      allyName={allyName}
      allyShape={allyShape}
      phase={phase}
      selectedColor={selectedColor}
    />
  );
}

type ConversationPreviewProps = OnboardingPreviewScreenProps & {
  phase: Exclude<OnboardingPreviewPhase, 'coming-alive'>;
};

function ConversationPreview({
  allyName,
  allyShape,
  phase,
  selectedColor,
}: ConversationPreviewProps) {
  const { bottom: bottomInset } = useSafeAreaInsets();
  const reducedMotion = useReducedMotion();
  const [draft, setDraft] = useState('');
  const [composerHeight, setComposerHeight] = useState(COMPOSER_MIN_HEIGHT);
  const [replySubmitted, setReplySubmitted] = useState(false);
  const greeting = useMemo(() => getOnboardingGreeting(allyName), [allyName]);
  const [visibleGreetingLength, setVisibleGreetingLength] = useState(0);
  const accentColor = selectedColor ?? '#FF5800';
  const isThinking = phase === 'thinking';
  const canSend = phase === 'ready' && Boolean(draft.trim()) && !replySubmitted;
  const displayedGreetingLength = reducedMotion ? greeting.length : visibleGreetingLength;
  const animatedSendColor = useAnimatedColor(canSend ? accentColor : '#A8A8A8');
  const sendBackgroundStyle = useAnimatedStyle(() => ({
    backgroundColor: animatedSendColor.value,
  }));

  useEffect(() => {
    if (phase !== 'ready') return;

    if (reducedMotion) return;

    let nextLength = 0;
    const interval = setInterval(() => {
      nextLength = Math.min(greeting.length, nextLength + 1);
      setVisibleGreetingLength(nextLength);

      if (nextLength === greeting.length) clearInterval(interval);
    }, ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [greeting, phase, reducedMotion]);

  const handleDraftChange = (value: string) => {
    setDraft(value);
    if (replySubmitted) setReplySubmitted(false);
  };

  const handleSend = () => {
    if (!canSend) return;
    setReplySubmitted(true);
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.conversationSafeArea}>
        {phase === 'ready' ? (
          <View style={styles.conversationHeader}>
            <OnboardingAllyPreview
              accessibilityLabel={`${allyName || 'Your'} Ally`}
              color={selectedColor}
              identity={allyShape}
              size={CONVERSATION_HEADER_AVATAR_SIZE}
            />
            <Text numberOfLines={1} style={styles.conversationName}>
              {allyName || 'Your Ally'}
            </Text>
          </View>
        ) : null}

        <ScrollView
          contentContainerStyle={styles.greetingContent}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
          style={styles.greetingScroll}>
          {phase === 'ready' ? (
            <Text style={styles.greetingText}>
              {getVisibleOnboardingGreeting(greeting, displayedGreetingLength)}
            </Text>
          ) : null}
        </ScrollView>

        {isThinking ? (
          <View style={styles.thinkingStatus}>
            <OnboardingAllyPreview
              accessibilityLabel="Ally thinking"
              color={selectedColor}
              identity={allyShape}
              size={THINKING_AVATAR_SIZE}
              state="thinking"
            />
            <Text style={[styles.thinkingLabel, { color: accentColor }]}>Thinking</Text>
          </View>
        ) : null}

        <View
          style={[
            styles.composerRow,
            { paddingBottom: Math.max(12, bottomInset > 0 ? 8 : 12) },
          ]}>
          <View
            style={[
              styles.composer,
              {
                borderRadius: composerHeight > COMPOSER_MIN_HEIGHT ? 18 : 999,
                height: composerHeight,
              },
            ]}>
            <TextInput
              accessibilityLabel="Reply to your Ally"
              autoCapitalize="sentences"
              autoCorrect
              editable={!replySubmitted}
              maxLength={4000}
              multiline
              onChangeText={handleDraftChange}
              onContentSizeChange={({ nativeEvent }) =>
                setComposerHeight(
                  Math.min(
                    COMPOSER_MAX_HEIGHT,
                    Math.max(COMPOSER_MIN_HEIGHT, nativeEvent.contentSize.height + 16),
                  ),
                )
              }
              placeholder={`Reply ${allyName || 'your Ally'}`}
              placeholderTextColor="#A8A8A8"
              selectionColor={accentColor}
              style={styles.composerInput}
              textAlignVertical="center"
              value={draft}
            />
            <Pressable
              accessibilityLabel="Send reply"
              accessibilityRole="button"
              accessibilityState={{ disabled: !canSend }}
              disabled={!canSend}
              onPress={handleSend}
              style={({ pressed }) => [styles.sendButton, pressed && styles.sendButtonPressed]}>
              <Animated.View
                pointerEvents="none"
                style={[StyleSheet.absoluteFill, styles.sendBackground, sendBackgroundStyle]}
              />
              <Image
                accessibilityLabel=""
                contentFit="contain"
                source={require('@/assets/allies/icons/send.svg')}
                style={styles.sendIcon}
              />
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  comingAliveContent: {
    alignItems: 'center',
    flex: 1,
    gap: 28,
    justifyContent: 'center',
    paddingBottom: 22,
    paddingHorizontal: 20,
  },
  comingAliveLabel: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    includeFontPadding: false,
    letterSpacing: -0.55,
    lineHeight: 24,
    textAlign: 'center',
  },
  comingAliveSafeArea: {
    flex: 1,
  },
  composer: {
    alignItems: 'center',
    backgroundColor: '#F3F3F3',
    flexDirection: 'row',
    overflow: 'hidden',
    paddingLeft: 14,
    paddingRight: 6,
    width: '100%',
  },
  composerInput: {
    color: '#121212',
    flex: 1,
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    includeFontPadding: false,
    letterSpacing: -0.35,
    lineHeight: 18,
    maxHeight: COMPOSER_MAX_HEIGHT - 8,
    paddingHorizontal: 0,
    paddingVertical: 8,
  },
  composerRow: {
    paddingHorizontal: 20,
  },
  conversationHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  conversationName: {
    color: '#121212',
    flexShrink: 1,
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    includeFontPadding: false,
    letterSpacing: -0.35,
    lineHeight: 18,
  },
  conversationSafeArea: {
    flex: 1,
  },
  greetingContent: {
    flexGrow: 1,
    paddingBottom: 20,
    paddingHorizontal: 20,
    paddingTop: 20,
  },
  greetingScroll: {
    flex: 1,
  },
  greetingText: {
    color: '#121212',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    includeFontPadding: false,
    letterSpacing: -0.3,
    lineHeight: 17,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  sendBackground: {
    borderRadius: 999,
  },
  sendButton: {
    alignItems: 'center',
    borderRadius: 999,
    height: 36,
    justifyContent: 'center',
    overflow: 'hidden',
    position: 'relative',
    width: 36,
  },
  sendButtonPressed: {
    opacity: 0.84,
    transform: [{ scale: 0.96 }],
  },
  sendIcon: {
    height: 18,
    width: 18,
  },
  thinkingLabel: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    includeFontPadding: false,
    letterSpacing: -0.35,
    lineHeight: 18,
  },
  thinkingStatus: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    minHeight: THINKING_AVATAR_SIZE,
    paddingHorizontal: 20,
    paddingBottom: 16,
  },
});
