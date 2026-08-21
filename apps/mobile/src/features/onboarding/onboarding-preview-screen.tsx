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
  type LayoutChangeEvent,
} from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  FadeIn,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withSpring,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { ShinyText } from '@/components/ui/shiny-text';
import { useAnimatedColor } from '@/components/ui/use-animated-color';

import { OnboardingAllyPreview } from './onboarding-ally-preview';
import { ONBOARDING_TOP_PADDING } from './onboarding-layout';
import { OnboardingTypewriterText } from './onboarding-typewriter-text';
import {
  ONBOARDING_COMING_ALIVE_WAVE_AMPLITUDE,
  ONBOARDING_COMING_ALIVE_WAVE_DURATION_MS,
  ONBOARDING_COMING_ALIVE_WAVE_STEP_MS,
} from './onboarding-motion';
import {
  ONBOARDING_PREVIEW_AVATAR_HANDOFF_SPRING,
  ONBOARDING_PREVIEW_BODY_TEXT_BOLD_STYLE,
  ONBOARDING_PREVIEW_BODY_TEXT_STYLE,
  ONBOARDING_PREVIEW_COMPOSER_INITIAL_BORDER_RADIUS,
  ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE,
  ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE,
  ONBOARDING_PREVIEW_HEADER_NAME_GAP,
  ONBOARDING_PREVIEW_HEADER_NAME_TEXT_STYLE,
  ONBOARDING_PREVIEW_NAME_CHAR_INTERVAL_MS,
  ONBOARDING_PREVIEW_GREETING_TOP_GAP,
  ONBOARDING_PREVIEW_THINKING_SHINE_DURATION_MS,
  ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE,
  getOnboardingAllyHandoffTransform,
  getNextOnboardingPreviewPhase,
  getOnboardingGreeting,
  getOnboardingGreetingRevealStep,
  getVisibleOnboardingGreeting,
  ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS,
  ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS,
  ONBOARDING_PREVIEW_THINKING_DELAY_MS,
  type OnboardingAvatarLayout,
  type OnboardingPreviewPhase,
} from './onboarding-preview';
import type { AllyColorValue, AllyShape } from './onboarding-state';

const HERO_SIZE = 164;
const COMPOSER_MIN_HEIGHT = 48;
const COMPOSER_MAX_HEIGHT = 96;
const PREVIEW_EASING = [0.32, 0.72, 0, 1] as const;
const COMING_ALIVE_TEXT = 'Coming alive....';
const CONVERSATION_HORIZONTAL_PADDING = 20;
const THINKING_LABEL_EXIT_DURATION_MS = 180;

type OnboardingPreviewScreenProps = {
  allyName: string;
  allyShape: AllyShape;
  selectedColor: AllyColorValue | null;
};

type WavyTextProps = {
  reducedMotion: boolean;
  text: string;
};

type WavyCharacterProps = {
  character: string;
  index: number;
  reducedMotion: boolean;
  waveProgress: SharedValue<number>;
};

function WavyText({ reducedMotion, text }: WavyTextProps) {
  const waveProgress = useSharedValue(0);

  useEffect(() => {
    cancelAnimation(waveProgress);

    if (reducedMotion) {
      waveProgress.value = 0;
      return;
    }

    waveProgress.value = withRepeat(
      withTiming(1, {
        duration: ONBOARDING_COMING_ALIVE_WAVE_DURATION_MS,
        easing: Easing.linear,
      }),
      -1,
      false,
    );

    return () => cancelAnimation(waveProgress);
  }, [reducedMotion, waveProgress]);

  return (
    <View
      accessible
      accessibilityLabel={text}
      style={styles.comingAliveLabel}>
      {Array.from(text).map((character, index) => (
        <WavyCharacter
          character={character === ' ' ? '\u00a0' : character}
          index={index}
          key={`${character}-${index}`}
          reducedMotion={reducedMotion}
          waveProgress={waveProgress}
        />
      ))}
    </View>
  );
}

function WavyCharacter({
  character,
  index,
  reducedMotion,
  waveProgress,
}: WavyCharacterProps) {
  const animatedStyle = useAnimatedStyle(() => {
    if (reducedMotion) {
      return { transform: [{ translateY: 0 }] };
    }

    const delayedProgress =
      (waveProgress.value -
        (index * ONBOARDING_COMING_ALIVE_WAVE_STEP_MS) /
          ONBOARDING_COMING_ALIVE_WAVE_DURATION_MS +
        1) %
      1;
    const wave =
      delayedProgress <= 0.5
        ? delayedProgress * 2
        : (1 - delayedProgress) * 2;

    return {
      transform: [{ translateY: -wave * ONBOARDING_COMING_ALIVE_WAVE_AMPLITUDE }],
    };
  }, [index, reducedMotion, waveProgress]);

  return (
    <Animated.Text
      accessibilityElementsHidden
      accessible={false}
      style={[styles.comingAliveCharacter, animatedStyle]}>
      {character}
    </Animated.Text>
  );
}

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
            <WavyText reducedMotion={Boolean(reducedMotion)} text={COMING_ALIVE_TEXT} />
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
  const [headerAvatarLayout, setHeaderAvatarLayout] = useState<OnboardingAvatarLayout | null>(null);
  const [thinkingAvatarLayout, setThinkingAvatarLayout] = useState<OnboardingAvatarLayout | null>(null);
  const [avatarSettledState, setAvatarSettledState] = useState(false);
  const greeting = useMemo(() => getOnboardingGreeting(allyName), [allyName]);
  const [visibleGreetingLength, setVisibleGreetingLength] = useState(0);
  const displayName = allyName || 'Your Ally';
  const [visibleNameLength, setVisibleNameLength] = useState(0);
  const accentColor = selectedColor ?? '#FF5800';
  const isThinking = phase === 'thinking';
  const avatarSettled = reducedMotion && phase === 'ready' ? true : avatarSettledState;
  const shouldRevealName = phase === 'ready' && avatarSettled;
  const nameRevealComplete = Boolean(reducedMotion) || visibleNameLength >= displayName.length;
  const shouldRevealGreeting = shouldRevealName && nameRevealComplete;
  const canSend = phase === 'ready' && Boolean(draft.trim()) && !replySubmitted;
  const displayedGreetingLength = reducedMotion ? greeting.length : visibleGreetingLength;
  const displayedName = reducedMotion
    ? displayName
    : getVisibleOnboardingGreeting(displayName, visibleNameLength);
  const avatarHandoffProgress = useSharedValue(0);
  const thinkingLabelOpacity = useSharedValue(isThinking ? 1 : 0);
  const avatarHandoffTarget = useMemo(() => {
    if (!headerAvatarLayout || !thinkingAvatarLayout) {
      return { scale: 1, translateX: 0, translateY: 0 };
    }

    return getOnboardingAllyHandoffTransform(
      thinkingAvatarLayout,
      phase === 'ready' ? headerAvatarLayout : thinkingAvatarLayout,
    );
  }, [headerAvatarLayout, phase, thinkingAvatarLayout]);
  const animatedSendColor = useAnimatedColor(canSend ? accentColor : '#A8A8A8');
  const sendBackgroundStyle = useAnimatedStyle(() => ({
    backgroundColor: animatedSendColor.value,
  }));
  const avatarHandoffStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(
          avatarHandoffProgress.value,
          [0, 1],
          [0, avatarHandoffTarget.translateX],
        ),
      },
      {
        translateY: interpolate(
          avatarHandoffProgress.value,
          [0, 1],
          [0, avatarHandoffTarget.translateY],
        ),
      },
      {
        scale: interpolate(
          avatarHandoffProgress.value,
          [0, 1],
          [1, avatarHandoffTarget.scale],
        ),
      },
    ],
  }), [avatarHandoffTarget]);
  const thinkingLabelOpacityStyle = useAnimatedStyle(() => ({
    opacity: thinkingLabelOpacity.value,
  }));

  const captureHeaderAvatarLayout = ({
    nativeEvent: { layout },
  }: LayoutChangeEvent) => {
    setHeaderAvatarLayout({
      height: ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE,
      width: ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE,
      x: layout.x + CONVERSATION_HORIZONTAL_PADDING,
      y: layout.y,
    });
  };
  const captureThinkingAvatarLayout = ({
    nativeEvent: { layout },
  }: LayoutChangeEvent) => {
    setThinkingAvatarLayout({
      height: ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE,
      width: ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE,
      x: layout.x + CONVERSATION_HORIZONTAL_PADDING,
      y: layout.y,
    });
  };

  useEffect(() => {
    cancelAnimation(thinkingLabelOpacity);

    if (reducedMotion) {
      thinkingLabelOpacity.set(isThinking ? 1 : 0);
      return;
    }

    thinkingLabelOpacity.set(
      withTiming(isThinking ? 1 : 0, {
        duration: THINKING_LABEL_EXIT_DURATION_MS,
        easing: Easing.out(Easing.cubic),
      }),
    );

    return () => cancelAnimation(thinkingLabelOpacity);
  }, [isThinking, reducedMotion, thinkingLabelOpacity]);

  useEffect(() => {
    if (!headerAvatarLayout || !thinkingAvatarLayout || avatarSettledState) return;

    cancelAnimation(avatarHandoffProgress);

    if (phase !== 'ready') {
      avatarHandoffProgress.set(0);
      return;
    }

    if (reducedMotion) {
      avatarHandoffProgress.set(1);
      return;
    }

    avatarHandoffProgress.set(
      withSpring(
        1,
        ONBOARDING_PREVIEW_AVATAR_HANDOFF_SPRING,
        (finished) => {
          'worklet';
          if (finished) runOnJS(setAvatarSettledState)(true);
        },
      ),
    );

    return () => {
      cancelAnimation(avatarHandoffProgress);
    };
  }, [
    avatarHandoffProgress,
    avatarSettledState,
    headerAvatarLayout,
    phase,
    reducedMotion,
    thinkingAvatarLayout,
  ]);

  useEffect(() => {
    if (phase !== 'ready' || !avatarSettled || reducedMotion) return;

    let nextLength = 0;
    const interval = setInterval(() => {
      nextLength = Math.min(displayName.length, nextLength + 1);
      setVisibleNameLength(nextLength);

      if (nextLength === displayName.length) clearInterval(interval);
    }, ONBOARDING_PREVIEW_NAME_CHAR_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [avatarSettled, displayName, phase, reducedMotion]);

  useEffect(() => {
    if (!shouldRevealGreeting || reducedMotion) return;

    let nextLength = 0;
    const revealStep = getOnboardingGreetingRevealStep(greeting.length);
    const interval = setInterval(() => {
      nextLength = Math.min(greeting.length, nextLength + revealStep);
      setVisibleGreetingLength(nextLength);

      if (nextLength === greeting.length) clearInterval(interval);
    }, ONBOARDING_PREVIEW_GREETING_CHAR_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [greeting, reducedMotion, shouldRevealGreeting]);

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
        <View style={styles.conversationContent}>
          <View onLayout={captureHeaderAvatarLayout} style={styles.conversationHeader}>
            <View style={styles.conversationAvatarSlot} />
            {shouldRevealName && displayedName ? (
              <Text
                accessibilityLabel={displayName}
                numberOfLines={1}
                style={styles.conversationName}>
                {displayedName}
              </Text>
            ) : null}
          </View>

          <ScrollView
            contentContainerStyle={styles.greetingContent}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
            style={styles.greetingScroll}>
            {shouldRevealGreeting ? (
              <OnboardingTypewriterText
                boldStyle={styles.greetingTextBold}
                characterCount={displayedGreetingLength}
                greeting={greeting}
                style={styles.greetingText}
              />
            ) : null}
          </ScrollView>

          <View onLayout={captureThinkingAvatarLayout} style={styles.thinkingStatus}>
            <View style={styles.thinkingAvatarSlot} />
            <Animated.View style={thinkingLabelOpacityStyle}>
              <ShinyText
                accessibilityLabel="Thinking"
                color={accentColor}
                paused={!isThinking}
                shineColor="#FFFFFF"
                speed={ONBOARDING_PREVIEW_THINKING_SHINE_DURATION_MS / 1000}
                style={styles.thinkingLabel}>
                Thinking
              </ShinyText>
            </Animated.View>
          </View>

          <View
            style={[
              styles.composerRow,
              { paddingBottom: Math.max(12, bottomInset > 0 ? 8 : 12) },
            ]}>
            <View
              style={[
                styles.composer,
                {
                  borderRadius:
                    composerHeight > COMPOSER_MIN_HEIGHT
                      ? 18
                      : ONBOARDING_PREVIEW_COMPOSER_INITIAL_BORDER_RADIUS,
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

          {thinkingAvatarLayout ? (
            <Animated.View
              pointerEvents="none"
              style={[
                styles.avatarHandoff,
                {
                  height: thinkingAvatarLayout.height,
                  left: thinkingAvatarLayout.x,
                  top: thinkingAvatarLayout.y,
                  width: thinkingAvatarLayout.width,
                },
                avatarHandoffStyle,
              ]}>
              <OnboardingAllyPreview
                accessibilityLabel={
                  phase === 'ready' && avatarSettled
                    ? `${allyName || 'Your'} Ally`
                    : 'Ally thinking'
                }
                color={selectedColor}
                identity={allyShape}
                size={ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE}
                state={phase === 'ready' && avatarSettled ? 'idle' : 'thinking'}
              />
            </Animated.View>
          ) : null}
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  avatarHandoff: {
    position: 'absolute',
    zIndex: 2,
  },
  comingAliveContent: {
    alignItems: 'center',
    flex: 1,
    gap: 28,
    justifyContent: 'center',
    paddingBottom: 22,
    paddingHorizontal: 20,
  },
  comingAliveCharacter: {
    color: '#121212',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    includeFontPadding: false,
    letterSpacing: -0.55,
    lineHeight: 24,
  },
  comingAliveLabel: {
    alignItems: 'baseline',
    flexDirection: 'row',
    justifyContent: 'center',
    minHeight: 32,
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
    ...ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE,
    flex: 1,
    includeFontPadding: false,
    maxHeight: COMPOSER_MAX_HEIGHT - 8,
    paddingHorizontal: 0,
    paddingVertical: 8,
  },
  composerRow: {
    paddingHorizontal: CONVERSATION_HORIZONTAL_PADDING,
  },
  conversationHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: ONBOARDING_PREVIEW_HEADER_NAME_GAP,
    minHeight: ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE,
    paddingHorizontal: CONVERSATION_HORIZONTAL_PADDING,
  },
  conversationAvatarSlot: {
    height: ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE,
    width: ONBOARDING_PREVIEW_HEADER_AVATAR_SIZE,
  },
  conversationName: {
    color: '#121212',
    flexShrink: 1,
    ...ONBOARDING_PREVIEW_HEADER_NAME_TEXT_STYLE,
  },
  conversationContent: {
    flex: 1,
    paddingTop: ONBOARDING_TOP_PADDING,
  },
  conversationSafeArea: {
    flex: 1,
  },
  greetingContent: {
    flexGrow: 1,
    paddingBottom: 20,
    paddingHorizontal: CONVERSATION_HORIZONTAL_PADDING,
    paddingTop: ONBOARDING_PREVIEW_GREETING_TOP_GAP,
  },
  greetingScroll: {
    flex: 1,
  },
  greetingText: {
    color: '#121212',
    ...ONBOARDING_PREVIEW_BODY_TEXT_STYLE,
    includeFontPadding: false,
  },
  greetingTextBold: {
    ...ONBOARDING_PREVIEW_BODY_TEXT_BOLD_STYLE,
    includeFontPadding: false,
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
    minHeight: ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE,
    paddingHorizontal: 20,
    paddingBottom: 16,
  },
  thinkingAvatarSlot: {
    height: ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE,
    width: ONBOARDING_PREVIEW_THINKING_AVATAR_SIZE,
  },
});
