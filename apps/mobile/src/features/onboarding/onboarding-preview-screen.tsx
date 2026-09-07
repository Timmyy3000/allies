import { Image } from 'expo-image';
import * as WebBrowser from 'expo-web-browser';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Keyboard,
  Pressable,
  StyleSheet,
  Text,
  View,
  type EmitterSubscription,
} from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { SafeAreaView } from 'react-native-safe-area-context';

import { BottomSheetModal } from '@/components/ui/bottom-sheet-modal';
import { BOTTOM_SHEET_ANIMATION_DURATION_MS } from '@/components/ui/bottom-sheet-motion';
import { LiquidGlassBackground } from '@/components/ui/liquid-glass-background';
import { PressScale } from '@/components/ui/press-scale-view';
import { ProviderButton } from '@/components/ui/provider-button';
import { useTheme } from '@/hooks/use-theme';

import {
  ConversationLayout,
  ConversationMessage,
  ConversationThinkingRow,
  type ConversationAlly,
} from '../conversation/conversation-layout';
import { OnboardingAllyPreview } from './onboarding-ally-preview';
import {
  ONBOARDING_COMING_ALIVE_SQUISH_DURATION_MS,
  getOnboardingComingAliveSquishTransform,
} from './onboarding-motion';
import {
  getNextOnboardingPreviewPhase,
  getAccountPromptOpenMode,
  getOnboardingReplyAction,
  ONBOARDING_PREVIEW_ENTRANCE_DELAY_MS,
  type OnboardingPreviewPhase,
} from './onboarding-preview';
import type { AllyColorValue, AllyShape } from './onboarding-state';

const HERO_SIZE = 64;
const COMING_ALIVE_TEXT = 'Coming alive....';
const PRIVACY_URL = 'https://yourallies.io/privacy';
const TERMS_URL = 'https://yourallies.io/terms';

function openLegalPage(url: string): void {
  void WebBrowser.openBrowserAsync(url).catch(() => undefined);
}

type OnboardingPreviewScreenProps = {
  allyName: string;
  allyShape: AllyShape;
  selectedColor: AllyColorValue | null;
  greeting: string;
  initialReply?: string;
  isSubmitting?: boolean;
  onBack: () => void;
  onAccountContinue?: (draft: string) => void | Promise<void>;
  onCancelPending?: () => void | Promise<void>;
  onReplySubmit: (reply: string) => boolean | Promise<boolean>;
  requiresAccount?: boolean;
  retryPending?: boolean;
  statusMessage?: string | null;
};

type ComingAliveAllyProps = {
  allyName: string;
  allyShape: AllyShape;
  reducedMotion: boolean;
  selectedColor: AllyColorValue | null;
};

function ComingAliveAlly({
  allyName,
  allyShape,
  reducedMotion,
  selectedColor,
}: ComingAliveAllyProps) {
  const squishProgress = useSharedValue(0);

  useEffect(() => {
    cancelAnimation(squishProgress);
    squishProgress.value = 0;

    if (reducedMotion) {
      squishProgress.value = 1;
      return;
    }

    squishProgress.value = withSequence(
      withTiming(0.18, { duration: 70, easing: Easing.out(Easing.cubic) }),
      withTiming(0.6, { duration: 160, easing: Easing.out(Easing.quad) }),
      withTiming(0.82, { duration: 270, easing: Easing.in(Easing.quad) }),
      withTiming(1, {
        duration: ONBOARDING_COMING_ALIVE_SQUISH_DURATION_MS - 70 - 160 - 270,
        easing: Easing.out(Easing.cubic),
      }),
    );

    return () => cancelAnimation(squishProgress);
  }, [reducedMotion, squishProgress]);

  const animatedStyle = useAnimatedStyle(() => {
    const transform = getOnboardingComingAliveSquishTransform(squishProgress.value);

    return {
      transform: [
        { translateY: transform.translateY },
        { scaleX: transform.scaleX },
        { scaleY: transform.scaleY },
      ],
    };
  });

  return (
    <Animated.View style={[styles.comingAliveHero, animatedStyle]}>
      <OnboardingAllyPreview
        accessibilityLabel={`${allyName || 'Your'} Ally coming alive`}
        artworkScale={0.86}
        color={selectedColor}
        identity={allyShape}
        size={HERO_SIZE}
      />
    </Animated.View>
  );
}

export function OnboardingPreviewScreen({
  allyName,
  allyShape,
  greeting,
  initialReply,
  isSubmitting = false,
  onBack,
  onAccountContinue,
  onCancelPending,
  onReplySubmit,
  requiresAccount = false,
  retryPending = false,
  selectedColor,
  statusMessage,
}: OnboardingPreviewScreenProps) {
  const theme = useTheme();
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
    if (!((phase === 'thinking' && greeting) || (phase === 'ready' && !greeting))) return undefined;

    const timer = setTimeout(() => {
      setPhase(
        phase === 'thinking'
          ? getNextOnboardingPreviewPhase(phase, true)
          : 'thinking',
      );
    }, 0);

    return () => clearTimeout(timer);
  }, [greeting, phase]);

  if (phase === 'coming-alive') {
    return (
      <View
        style={[styles.root, { backgroundColor: theme.appBackground }]}
      >
        <SafeAreaView edges={['top', 'bottom']} style={styles.comingAliveSafeArea}>
          <View style={styles.comingAliveContent}>
            <ComingAliveAlly
              allyName={allyName}
              allyShape={allyShape}
              reducedMotion={Boolean(reducedMotion)}
              selectedColor={selectedColor}
            />
            <Text style={[styles.comingAliveText, { color: theme.primaryText }]}>{COMING_ALIVE_TEXT}</Text>
          </View>
        </SafeAreaView>
      </View>
    );
  }

  return (
    <ConversationPreview
      allyName={allyName}
      allyShape={allyShape}
      onBack={onBack}
      phase={phase}
      selectedColor={selectedColor}
      greeting={greeting}
      initialReply={initialReply}
      isSubmitting={isSubmitting}
      onAccountContinue={onAccountContinue}
      onCancelPending={onCancelPending}
      onReplySubmit={onReplySubmit}
      requiresAccount={requiresAccount}
      retryPending={retryPending}
      statusMessage={statusMessage}
    />
  );
}

type ConversationPreviewProps = OnboardingPreviewScreenProps & {
  phase: Exclude<OnboardingPreviewPhase, 'coming-alive'>;
};

function ConversationPreview({
  allyName,
  allyShape,
  greeting,
  initialReply,
  isSubmitting,
  onBack,
  onAccountContinue,
  onCancelPending,
  onReplySubmit,
  phase,
  requiresAccount,
  retryPending,
  selectedColor,
  statusMessage,
}: ConversationPreviewProps) {
  const theme = useTheme();
  const reducedMotion = useReducedMotion();
  const [draft, setDraft] = useState(initialReply ?? '');
  const [composerHeight, setComposerHeight] = useState(48);
  const [greetingFinished, setGreetingFinished] = useState(false);
  const [replySubmitted, setReplySubmitted] = useState(false);
  const displayName = allyName || 'Your Ally';
  const accentColor = selectedColor ?? '#FF5800';
  const isThinking = phase === 'thinking';
  const shouldRevealGreeting = phase === 'ready' && Boolean(greeting);
  const canSend = phase === 'ready'
    && Boolean(draft.trim())
    && !replySubmitted
    && !isSubmitting;
  const [accountPromptVisible, setAccountPromptVisible] = useState(false);
  const accountPromptKeyboardSubscription = useRef<EmitterSubscription | null>(null);
  const accountTransitionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const replyAction = getOnboardingReplyAction(canSend, Boolean(requiresAccount));
  const handleGreetingComplete = useCallback(() => setGreetingFinished(true), []);

  useEffect(() => () => {
    accountPromptKeyboardSubscription.current?.remove();
    if (accountTransitionTimer.current) {
      clearTimeout(accountTransitionTimer.current);
      accountTransitionTimer.current = null;
    }
  }, []);

  const handleDraftChange = (value: string) => {
    setDraft(value);
    if (replySubmitted) setReplySubmitted(false);
  };

  const openAccountPrompt = () => {
    accountPromptKeyboardSubscription.current?.remove();
    accountPromptKeyboardSubscription.current = null;

    const open = () => {
      accountPromptKeyboardSubscription.current?.remove();
      accountPromptKeyboardSubscription.current = null;
      setAccountPromptVisible(true);
    };

    if (getAccountPromptOpenMode(Keyboard.isVisible()) === 'immediate') {
      open();
      return;
    }

    accountPromptKeyboardSubscription.current = Keyboard.addListener('keyboardDidHide', open);
    Keyboard.dismiss();
  };

  const handleSend = async () => {
    if (replyAction === 'ignore') return;
    if (replyAction === 'prompt-account') {
      openAccountPrompt();
      return;
    }
    Keyboard.dismiss();
    setReplySubmitted(true);
    const accepted = await onReplySubmit(draft);
    if (!accepted) setReplySubmitted(false);
  };

  const continueAfterAccount = () => {
    setAccountPromptVisible(false);
    if (!onAccountContinue) return;

    if (accountTransitionTimer.current) {
      clearTimeout(accountTransitionTimer.current);
      accountTransitionTimer.current = null;
    }
    if (reducedMotion) {
      void onAccountContinue(draft);
      return;
    }

    accountTransitionTimer.current = setTimeout(() => {
      accountTransitionTimer.current = null;
      void onAccountContinue(draft);
    }, BOTTOM_SHEET_ANIMATION_DURATION_MS);
  };

  const conversationAlly: ConversationAlly = {
    color: accentColor,
    name: displayName,
    shape: allyShape,
  };

  return (
    <>
      <ConversationLayout
        active={isThinking && !statusMessage}
        ally={conversationAlly}
        canSend={canSend}
        composerHeight={composerHeight}
        draft={draft}
        editable={!replySubmitted && !isSubmitting && !retryPending}
        focusComposer={greetingFinished}
        headerMode="onboarding"
        onBack={onBack}
        onChangeDraft={handleDraftChange}
        onComposerHeightChange={setComposerHeight}
        onSend={() => void handleSend()}
        placeholder={`Ask ${displayName}`}
      >
        {shouldRevealGreeting ? (
          <ConversationMessage
            ally={conversationAlly}
            key="onboarding-greeting"
            message={{ content: greeting, id: 'onboarding-greeting', sender: 'assistant' }}
            onRevealComplete={handleGreetingComplete}
            reducedMotion={Boolean(reducedMotion)}
          />
        ) : null}
        {!statusMessage ? (
          <ConversationThinkingRow ally={conversationAlly} key="onboarding-ally-status" reducedMotion={Boolean(reducedMotion)} thinking={isThinking} />
        ) : null}
        {statusMessage ? <Text style={styles.statusMessage}>{statusMessage}</Text> : null}
        {retryPending && onCancelPending ? (
          <Pressable accessibilityRole="button" onPress={() => void onCancelPending()} style={styles.cancelPending}>
            <Text style={styles.cancelPendingText}>Cancel saved creation</Text>
          </Pressable>
        ) : null}
      </ConversationLayout>

      <BottomSheetModal
        accessibilityLabel="Close account creation"
        onClose={() => setAccountPromptVisible(false)}
        visible={accountPromptVisible}>
        <View style={styles.accountPromptContent}>
          <View style={styles.accountPromptHeader}>
            <View style={styles.accountPromptAllyContainer}>
              <OnboardingAllyPreview
                accessibilityLabel={`${allyName || 'Your'} Ally`}
                color={selectedColor}
                identity={allyShape}
                size={48}
              />
            </View>
            <PressScale
              accessibilityLabel="Close account creation"
              accessibilityRole="button"
              onPress={() => setAccountPromptVisible(false)}
              pressableStyle={styles.accountPromptClosePressable}
              style={styles.accountPromptClose}>
              <LiquidGlassBackground
                borderRadius={999}
                fallbackColor={theme.modalCancelSurface}
                invertColorScheme
              />
              <Image
                accessibilityLabel=""
                contentFit="contain"
                source={require('@/assets/allies/icons/x-icon.svg')}
                style={[styles.accountPromptCloseIcon, { tintColor: theme.modalCancelIcon }]}
              />
            </PressScale>
          </View>

          <Text style={[styles.accountPromptTitle, { color: theme.primaryText }]}>Create your{ '\n' }account</Text>
          <Text style={[styles.accountPromptDescription, { color: theme.primaryText }]}>
            {displayName} has been saved but you need to set up an account to use it.
          </Text>

          <View style={styles.accountPromptOptions}>
            <ProviderButton
              accessibilityLabel="Continue with Google"
              icon={require('@/assets/allies/icons/google-logo.svg')}
              label="Continue with Google"
              onPress={continueAfterAccount}
            />
          </View>

          <Text style={styles.accountPromptFinePrint}>
            By continuing, you agree to our{' '}
            <Text accessibilityRole="link" onPress={() => openLegalPage(TERMS_URL)} style={styles.accountPromptLink}>Terms of Service</Text>{' '}
            and have read our{' '}
            <Text accessibilityRole="link" onPress={() => openLegalPage(PRIVACY_URL)} style={styles.accountPromptLink}>Privacy Policy</Text>
          </Text>
        </View>
      </BottomSheetModal>
    </>
  );
}

const styles = StyleSheet.create({
  accountPromptAllyContainer: {
    alignItems: 'flex-start',
    height: 64,
    justifyContent: 'center',
    marginTop: 12,
    width: 64,
  },
  accountPromptClose: {
    height: 36,
    position: 'absolute',
    right: 0,
    top: 0,
    width: 36,
  },
  accountPromptClosePressable: {
    alignItems: 'center',
    borderRadius: 999,
    flex: 1,
    justifyContent: 'center',
    overflow: 'hidden',
  },
  accountPromptCloseIcon: {
    height: 10.5,
    width: 10.5,
  },
  accountPromptDescription: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    letterSpacing: -0.5,
    lineHeight: 20,
    marginTop: 12,
  },
  accountPromptFinePrint: {
    color: '#A0A0A0',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    letterSpacing: -0.5,
    lineHeight: 14,
    marginTop: 24,
    textAlign: 'center',
  },
  accountPromptHeader: {
    height: 76,
    position: 'relative',
  },
  accountPromptLink: {
    textDecorationLine: 'underline',
  },
  accountPromptOptions: {
    gap: 12,
    marginTop: 24,
  },
  accountPromptContent: {
    paddingHorizontal: 20,
    paddingTop: 24,
  },
  accountPromptTitle: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 24,
    includeFontPadding: true,
    letterSpacing: -1,
    lineHeight: 24,
    marginTop: 12,
  },
  cancelPending: {
    alignSelf: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  cancelPendingText: {
    color: '#7A7A7A',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
  },
  comingAliveContent: {
    alignItems: 'center',
    flex: 1,
    gap: 18,
    justifyContent: 'center',
    paddingHorizontal: 14,
  },
  comingAliveHero: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  comingAliveText: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 24,
    letterSpacing: -1,
    lineHeight: 24,
    textAlign: 'center',
  },
  comingAliveSafeArea: {
    flex: 1,
  },
  root: {
    flex: 1,
  },
  statusMessage: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    paddingBottom: 8,
    textAlign: 'center',
  },
});
