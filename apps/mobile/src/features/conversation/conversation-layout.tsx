import { Image } from 'expo-image';
import { Keyboard, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type NativeScrollEvent, type NativeSyntheticEvent, type StyleProp, type ViewStyle } from 'react-native';
import { useEffect, useRef, useState, type ComponentRef, type ReactNode, type RefObject } from 'react';
import { KeyboardChatScrollView, KeyboardStickyView } from 'react-native-keyboard-controller';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, { Easing, FadeIn, FadeOut, LinearTransition, useAnimatedStyle, useSharedValue } from 'react-native-reanimated';
import Svg, { Circle, Path } from 'react-native-svg';

import { ShinyText } from '@/components/ui/shiny-text';
import { LiquidGlassBackground } from '@/components/ui/liquid-glass-background';
import { useAnimatedColor } from '@/components/ui/use-animated-color';
import { OnboardingBackButton } from '@/features/onboarding/onboarding-header';
import {
  COMPOSER_MAX_HEIGHT,
  COMPOSER_MIN_HEIGHT,
  getComposerBorderRadius,
  getComposerHeight,
  shouldScrollComposer,
} from './conversation-composer';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import {
  ONBOARDING_HEADER_BUTTON_SIZE,
  ONBOARDING_IOS_TOP_PADDING,
  ONBOARDING_TOP_PADDING,
} from '@/features/onboarding/onboarding-layout';
import {
  ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE,
  ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE,
  ONBOARDING_PREVIEW_HEADER_NAME_TEXT_STYLE,
  ONBOARDING_PREVIEW_BODY_TEXT_BOLD_STYLE,
  ONBOARDING_PREVIEW_BODY_TEXT_STYLE,
} from '@/features/onboarding/onboarding-preview';
import { OnboardingTypewriterText } from '@/features/onboarding/onboarding-typewriter-text';
import type { AllyShape } from '@/features/onboarding/onboarding-state';
import { useTheme } from '@/hooks/use-theme';
import { getMutedOnboardingColor } from '@/features/onboarding/onboarding-motion';

const MESSAGE_MAX_LENGTH = 4_000;
const CONVERSATION_HORIZONTAL_PADDING = 14;
const ALLY_STATUS_LAYOUT = LinearTransition.duration(220).easing(Easing.out(Easing.cubic));

export type ConversationAlly = {
  color: string;
  name: string;
  shape: AllyShape;
};

export type ConversationDisplayMessage = {
  content: string;
  id: string;
  sender: 'assistant' | 'user';
  status?: string | null;
  statusLabel?: string | null;
};

type ConversationLayoutProps = {
  active?: boolean;
  ally: ConversationAlly;
  canSend: boolean;
  children: ReactNode;
  composerHeight: number;
  draft: string;
  editable?: boolean;
  headerMode?: 'standard' | 'onboarding';
  onBack: () => void;
  onChangeDraft: (value: string) => void;
  onComposerHeightChange: (height: number) => void;
  onFocus?: () => void;
  onSend: () => void;
  placeholder: string;
  sendLabel?: string;
  scrollRef?: RefObject<ScrollView | null>;
  onContentSizeChange?: () => void;
  onScroll?: (event: NativeSyntheticEvent<NativeScrollEvent>) => void;
  contentContainerStyle?: StyleProp<ViewStyle>;
  focusComposer?: boolean;
};

export function ConversationLayout({
  active = false,
  ally,
  canSend,
  children,
  composerHeight,
  contentContainerStyle,
  draft,
  editable = true,
  focusComposer = false,
  headerMode = 'standard',
  onBack,
  onChangeDraft,
  onComposerHeightChange,
  onContentSizeChange,
  onFocus,
  onScroll,
  onSend,
  placeholder,
  scrollRef,
  sendLabel = 'Send message',
}: ConversationLayoutProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const composerRef = useRef<TextInput>(null);
  const composerFocusedRef = useRef(false);
  const keyboardScrollRef = scrollRef as RefObject<ComponentRef<typeof KeyboardChatScrollView> | null> | undefined;
  const composerExtraPadding = useSharedValue(Math.max(0, composerHeight - COMPOSER_MIN_HEIGHT));
  const sendColor = useAnimatedColor(headerMode === 'onboarding' ? ally.color : canSend ? ally.color : theme.inactiveButton);
  const sendBackgroundStyle = useAnimatedStyle(() => ({ backgroundColor: sendColor.value }));
  const composerBorderRadius = getComposerBorderRadius(composerHeight);
  const composerTintColor = headerMode === 'onboarding' ? getMutedOnboardingColor(ally.color, 0.02) : undefined;

  useEffect(() => {
    if (!focusComposer || !editable || composerFocusedRef.current) return;
    composerFocusedRef.current = true;
    composerRef.current?.focus();
  }, [editable, focusComposer]);

  useEffect(() => {
    composerExtraPadding.value = Math.max(0, composerHeight - COMPOSER_MIN_HEIGHT);
  }, [composerExtraPadding, composerHeight]);

  return (
    <View style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.content}>
          <ConversationHeader active={active} ally={ally} mode={headerMode} onBack={onBack} />
          <KeyboardChatScrollView
            contentContainerStyle={[styles.messagesContent, contentContainerStyle]}
            extraContentPadding={composerExtraPadding}
            keyboardShouldPersistTaps="handled"
            offset={insets.bottom}
            onContentSizeChange={onContentSizeChange}
            onScroll={onScroll}
            ref={keyboardScrollRef}
            scrollEventThrottle={16}
            showsVerticalScrollIndicator={false}
            style={styles.messagesScroll}
          >
            {children}
          </KeyboardChatScrollView>
          <KeyboardStickyView offset={{ closed: 0, opened: insets.bottom }}>
            <View style={[styles.composerArea, { paddingBottom: Math.max(12, insets.bottom > 0 ? 8 : 12) }]}>
              <View style={[styles.composer, { borderRadius: composerBorderRadius, height: composerHeight }]}>
                <LiquidGlassBackground
                  borderRadius={composerBorderRadius}
                  contentStyle={styles.composerContent}
                  fallbackColor={theme.chatInput}
                  tintColor={composerTintColor}
                >
                  <TextInput
                  accessibilityLabel={`Message ${ally.name}`}
                  autoCapitalize="sentences"
                  autoCorrect
                  editable={editable}
                  maxLength={MESSAGE_MAX_LENGTH}
                  multiline
                  onChangeText={(value) => {
                    onChangeDraft(value);
                    if (!value) onComposerHeightChange(COMPOSER_MIN_HEIGHT);
                  }}
                  onContentSizeChange={({ nativeEvent }) => onComposerHeightChange(getComposerHeight(nativeEvent.contentSize.height, draft.length > 0))}
                  onFocus={onFocus}
                  placeholder={placeholder}
                  placeholderTextColor={theme.placeholderText}
                  selectionColor={ally.color}
                  scrollEnabled={shouldScrollComposer(draft, composerHeight)}
                  style={[styles.composerInput, { color: theme.primaryText }]}
                  textAlignVertical="center"
                  value={draft}
                  ref={composerRef}
                  />
                  <Pressable accessibilityLabel={sendLabel} accessibilityRole="button" accessibilityState={{ disabled: !canSend }} disabled={!canSend} onPress={() => { Keyboard.dismiss(); onSend(); }} style={[styles.sendButton, composerHeight > COMPOSER_MIN_HEIGHT && styles.sendButtonMultiline]}>
                    <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.sendBackground, sendBackgroundStyle]} />
                    <Image accessibilityLabel="" contentFit="contain" source={require('@/assets/allies/icons/send.svg')} style={[styles.sendIcon, { tintColor: theme.buttonText }]} />
                  </Pressable>
                </LiquidGlassBackground>
              </View>
            </View>
          </KeyboardStickyView>
        </View>
      </SafeAreaView>
    </View>
  );
}

function ConversationHeader({ active, ally, mode, onBack }: { active: boolean; ally: ConversationAlly; mode: 'standard' | 'onboarding'; onBack: () => void }) {
  const theme = useTheme();
  const backButton = <OnboardingBackButton accessibilityLabel="Back to Allies" onBack={onBack} />;

  if (mode === 'onboarding') {
    return <View style={[styles.header, { backgroundColor: theme.appBackground }]}>{backButton}</View>;
  }

  return (
    <View style={[styles.header, { backgroundColor: theme.appBackground }]}>
      {backButton}
      <View accessibilityLabel={`${ally.name} Ally`} accessible style={styles.headerIdentity}>
        <OnboardingAllyPreview accessibilityLabel={`${ally.name} Ally`} artworkScale={0.86} color={ally.color} identity={ally.shape} size={40} state={active ? 'thinking' : 'idle'} />
        <Text numberOfLines={1} style={[styles.headerName, { color: theme.primaryText }]}>{ally.name}</Text>
      </View>
      <View accessibilityLabel="Ally settings" accessible style={[styles.headerButton, { backgroundColor: theme.controlSurface }]}>
        <SettingsIcon color={theme.icon} />
      </View>
    </View>
  );
}

export function ConversationMessage({ ally, animateAssistant = true, characterCount, firstMessage = false, message, onRevealComplete, reducedMotion }: { ally: ConversationAlly; animateAssistant?: boolean; characterCount?: number; firstMessage?: boolean; message: ConversationDisplayMessage; onRevealComplete?: () => void; reducedMotion: boolean }) {
  const theme = useTheme();
  const [internalCharacterCount, setInternalCharacterCount] = useState(0);
  const entering = reducedMotion ? undefined : FadeIn.duration(180).easing(Easing.out(Easing.cubic));
  useEffect(() => {
    if (message.sender !== 'assistant' || characterCount !== undefined) return;
    if (!animateAssistant || reducedMotion) {
      onRevealComplete?.();
      return;
    }
    let next = 0;
    const step = Math.max(1, Math.ceil(message.content.length / 62));
    const timer = setInterval(() => {
      next = Math.min(message.content.length, next + step);
      setInternalCharacterCount(next);
      if (next >= message.content.length) {
        clearInterval(timer);
        onRevealComplete?.();
      }
    }, 16);
    return () => clearInterval(timer);
  }, [animateAssistant, characterCount, message.content, message.sender, onRevealComplete, reducedMotion]);

  if (message.sender === 'user') {
    return (
      <Animated.View entering={entering} style={[styles.userMessage, firstMessage && styles.firstMessage, { backgroundColor: ally.color }]}>
        <Text style={styles.userMessageText}>{message.content}</Text>
        {message.statusLabel ? <Text style={styles.userMessageStatus}>{message.statusLabel}</Text> : null}
      </Animated.View>
    );
  }

  const visibleCharacterCount = characterCount ?? (!animateAssistant || reducedMotion ? message.content.length : internalCharacterCount);
  return (
    <Animated.View entering={entering} style={[styles.allyMessage, firstMessage && styles.firstMessage]}>
      {message.content.includes('\n\n') ? (
        <OnboardingTypewriterText
          boldStyle={[styles.messageTextBold, { color: theme.primaryText }]}
          characterCount={visibleCharacterCount}
          greeting={message.content}
          style={[styles.messageText, { color: theme.primaryText }]}
        />
      ) : (
        <Text style={[styles.messageText, { color: theme.primaryText }]}>{message.content.slice(0, visibleCharacterCount)}</Text>
      )}
      {message.status ? <Text style={[styles.messageStatus, { color: theme.supportingText }]}>{message.status}</Text> : null}
    </Animated.View>
  );
}

export function ConversationThinkingRow({ ally, label = 'Thinking', reducedMotion, thinking = true }: { ally: ConversationAlly; label?: string; reducedMotion: boolean; thinking?: boolean }) {
  const theme = useTheme();
  return (
    <Animated.View entering={reducedMotion ? undefined : FadeIn.duration(180).easing(Easing.out(Easing.cubic))} layout={reducedMotion ? undefined : ALLY_STATUS_LAYOUT} style={styles.thinkingRow}>
      <OnboardingAllyPreview accessibilityLabel={thinking ? `${ally.name} is thinking` : ally.name} artworkScale={0.86} color={ally.color} identity={ally.shape} size={ONBOARDING_PREVIEW_CONVERSATION_ALLY_SIZE} state={thinking ? 'thinking' : 'idle'} />
      {thinking ? (
        <Animated.View exiting={reducedMotion ? undefined : FadeOut.duration(120)}>
          <ShinyText accessibilityLabel={label} color={ally.color} paused={false} shineColor={theme.shimmerHighlight} style={styles.thinkingText}>{label}</ShinyText>
        </Animated.View>
      ) : null}
    </Animated.View>
  );
}

function SettingsIcon({ color }: { color: string }) {
  return (
    <Svg fill="none" height={22} viewBox="0 0 24 24" width={22}>
      <Circle cx={12} cy={12} r={7.5} stroke={color} strokeWidth={2} />
      <Circle cx={12} cy={12} r={2.5} fill={color} />
      <Path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" stroke={color} strokeLinecap="round" strokeWidth={1.6} />
    </Svg>
  );
}

const styles = StyleSheet.create({
  allyMessage: { marginTop: 22 },
  composer: { width: '100%' },
  composerArea: { paddingHorizontal: CONVERSATION_HORIZONTAL_PADDING },
  composerContent: { alignItems: 'center', flexDirection: 'row', paddingLeft: 14, paddingRight: 6, width: '100%' },
  composerInput: { ...ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE, flex: 1, includeFontPadding: false, maxHeight: COMPOSER_MAX_HEIGHT - 8, paddingHorizontal: 0, paddingVertical: 8 },
  content: { flex: 1 },
  firstMessage: { marginTop: 0 },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 13, paddingHorizontal: CONVERSATION_HORIZONTAL_PADDING, paddingTop: 0 },
  headerButton: { alignItems: 'center', borderRadius: 999, height: ONBOARDING_HEADER_BUTTON_SIZE, justifyContent: 'center', width: ONBOARDING_HEADER_BUTTON_SIZE },
  headerIdentity: { alignItems: 'center', flex: 1, flexDirection: 'row', justifyContent: 'center', marginHorizontal: 12 },
  headerName: { ...ONBOARDING_PREVIEW_HEADER_NAME_TEXT_STYLE, marginLeft: 12, maxWidth: 180 },
  messageStatus: { fontFamily: 'OpenRundeMedium', fontSize: 12, marginTop: 5 },
  messageText: { ...ONBOARDING_PREVIEW_BODY_TEXT_STYLE },
  messageTextBold: { ...ONBOARDING_PREVIEW_BODY_TEXT_BOLD_STYLE },
  messagesContent: { paddingBottom: 22, paddingHorizontal: CONVERSATION_HORIZONTAL_PADDING },
  messagesScroll: { flex: 1 },
  root: { flex: 1 },
  safeArea: { flex: 1, paddingTop: Platform.OS === 'ios' ? ONBOARDING_IOS_TOP_PADDING : ONBOARDING_TOP_PADDING },
  sendBackground: { borderRadius: 999 },
  sendButton: { alignItems: 'center', borderRadius: 999, height: 36, justifyContent: 'center', width: 36 },
  sendButtonMultiline: { alignSelf: 'flex-end', marginBottom: 6 },
  sendIcon: { height: 18, width: 18 },
  thinkingRow: { alignItems: 'center', flexDirection: 'row', gap: 8, marginTop: 22 },
  thinkingText: { fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22 },
  userMessage: { alignSelf: 'flex-end', borderRadius: 20, marginTop: 14, maxWidth: '88%', paddingHorizontal: 16, paddingVertical: 12 },
  userMessageStatus: { color: 'rgba(255,255,255,0.78)', fontFamily: 'OpenRundeMedium', fontSize: 12, lineHeight: 16, marginTop: 4 },
  userMessageText: { color: '#FFFFFF', fontFamily: 'OpenRundeMedium', fontSize: 16, letterSpacing: -0.5, lineHeight: 22 },
});
