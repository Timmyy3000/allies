import { Image } from 'expo-image';
import { Alert, Keyboard, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useCallback, useEffect, useRef, useState } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, { Easing, FadeIn, LinearTransition, useAnimatedStyle, useReducedMotion } from 'react-native-reanimated';
import Svg, { Circle, Path } from 'react-native-svg';
import { Directory, File } from 'expo-file-system';

import { useAnimatedColor } from '@/components/ui/use-animated-color';
import { ShinyText } from '@/components/ui/shiny-text';
import { getComposerBorderRadius, getComposerHeight, shouldScrollComposer } from '@/features/conversation/conversation-composer';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import {
  ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE,
} from '@/features/onboarding/onboarding-preview';
import { OnboardingTypewriterText } from '@/features/onboarding/onboarding-typewriter-text';
import { useTheme } from '@/hooks/use-theme';

import {
  addConversationAttachments,
  CONVERSATION_ALLY_SIZE,
  CONVERSATION_INITIAL_CONTENT_OFFSET,
  CONVERSATION_MAX_ATTACHMENTS,
  getAttachmentDisplayName,
  isAttachmentPickerCancellation,
  isConversationNearBottom,
} from './mock-conversation-layout';
import { useMockApp, type MockAlly, type MockAttachment, type MockMessage } from './mock-app';

const COMPOSER_MIN_HEIGHT = 48;
const COMPOSER_MAX_HEIGHT = 96;
const SCREEN_HORIZONTAL_PADDING = 14;
const COMPOSER_HORIZONTAL_PADDING = 20;
const MESSAGE_TYPEWRITER_INTERVAL_MS = 16;
const MESSAGE_TYPEWRITER_DURATION_MS = 1000;
const ALLY_STATUS_LAYOUT = LinearTransition.duration(220).easing(Easing.out(Easing.cubic));
const ATTACHMENT_ERROR = 'Couldn’t add that item. Try again.';

type MockConversationScreenProps = {
  ally: MockAlly;
  onBack: () => void;
};

export function MockConversationScreen({ ally, onBack }: MockConversationScreenProps) {
  const mock = useMockApp();
  const theme = useTheme();
  const reducedMotion = Boolean(useReducedMotion());
  const scrollRef = useRef<ScrollView>(null);
  const followLatestRef = useRef(true);
  const pendingScrollFrameRef = useRef<number | null>(null);
  const [draft, setDraft] = useState('');
  const [composerHeight, setComposerHeight] = useState(COMPOSER_MIN_HEIGHT);
  const [attachments, setAttachments] = useState<MockAttachment[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [typingState, setTypingState] = useState<{ count: number; id: string } | null>(null);
  const messages = mock.getConversation(ally.id);
  const isReplying = mock.isReplying(ally.id);
  const cancelReply = mock.cancelReply;
  const latestAssistantMessage = [...messages].reverse().find((message) => message.sender === 'assistant');
  const canSend = (Boolean(draft.trim()) || attachments.length > 0) && !isReplying;
  const sendColor = useAnimatedColor(canSend ? ally.color : theme.inactiveButton);
  const sendBackgroundStyle = useAnimatedStyle(() => ({ backgroundColor: sendColor.value }));
  const scheduleScrollToEnd = useCallback((force = false) => {
    if (force) followLatestRef.current = true;
    if (!force && !followLatestRef.current) return;
    if (pendingScrollFrameRef.current !== null) return;

    pendingScrollFrameRef.current = requestAnimationFrame(() => {
      pendingScrollFrameRef.current = null;
      if (!force && !followLatestRef.current) return;
      scrollRef.current?.scrollToEnd({ animated: !reducedMotion });
    });
  }, [reducedMotion]);

  useEffect(() => {
    if (!latestAssistantMessage) return;

    if (reducedMotion) return;

    let nextCharacterCount = 0;
    const step = Math.max(
      1,
      Math.ceil(
        latestAssistantMessage.content.length
          / Math.max(1, Math.floor(MESSAGE_TYPEWRITER_DURATION_MS / MESSAGE_TYPEWRITER_INTERVAL_MS)),
      ),
    );
    const timer = setInterval(() => {
      nextCharacterCount = Math.min(
        latestAssistantMessage.content.length,
        nextCharacterCount + step,
      );
      setTypingState({ count: nextCharacterCount, id: latestAssistantMessage.id });
      if (nextCharacterCount >= latestAssistantMessage.content.length) clearInterval(timer);
    }, MESSAGE_TYPEWRITER_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [latestAssistantMessage, reducedMotion]);

  useEffect(() => {
    scheduleScrollToEnd();
  }, [isReplying, messages.length, reducedMotion, scheduleScrollToEnd, typingState?.count]);

  useEffect(() => () => {
    cancelReply(ally.id);
    if (pendingScrollFrameRef.current !== null) {
      cancelAnimationFrame(pendingScrollFrameRef.current);
      pendingScrollFrameRef.current = null;
    }
  }, [ally.id, cancelReply]);

  const handleSend = () => {
    if (!canSend) return;
    scheduleScrollToEnd(true);
    if (!mock.sendMessage(ally.id, draft, attachments)) return;
    setDraft('');
    setAttachments([]);
    setAttachmentError(null);
    setComposerHeight(COMPOSER_MIN_HEIGHT);
    Keyboard.dismiss();
  };

  const addPickedAttachments = (picked: MockAttachment[]) => {
    if (picked.length === 0) return;
    const nextAttachments = addConversationAttachments(attachments, picked);
    const acceptedCount = nextAttachments.length - attachments.length;
    if (acceptedCount === 0) {
      setAttachmentError(`You can add up to ${CONVERSATION_MAX_ATTACHMENTS} items.`);
      return;
    }
    setAttachments(nextAttachments);
    setAttachmentError(acceptedCount < picked.length ? `You can add up to ${CONVERSATION_MAX_ATTACHMENTS} items.` : null);
  };

  const pickFiles = async () => {
    const result = await File.pickFileAsync({ mimeTypes: '*/*', multipleFiles: true });
    if (!result.canceled) {
      addPickedAttachments(result.result.map((file) => ({
        kind: 'file',
        name: getAttachmentDisplayName(file.name, file.uri, 'file'),
        uri: file.uri,
      })));
    }
  };

  const pickFolder = async () => {
    try {
      const folder = await Directory.pickDirectoryAsync();
      addPickedAttachments([{
        kind: 'folder',
        name: getAttachmentDisplayName(folder.name, folder.uri, 'folder'),
        uri: folder.uri,
      }]);
    } catch (error) {
      if (isAttachmentPickerCancellation(error)) return;
      setAttachmentError(ATTACHMENT_ERROR);
    }
  };

  const handleAddAttachment = () => {
    if (Platform.OS === 'web') {
      setAttachmentError('Attachments are available on mobile.');
      return;
    }

    setAttachmentError(null);
    Alert.alert('Add to your message', undefined, [
      {
        onPress: () => void pickFiles(),
        text: 'Choose files',
      },
      {
        onPress: () => void pickFolder(),
        text: 'Choose folder',
      },
      { style: 'cancel', text: 'Cancel' },
    ]);
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={0}
      style={[styles.root, { backgroundColor: theme.appBackground }]}>
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.content}>
          <View style={[styles.header, { backgroundColor: theme.appBackground }]}>
            <Pressable
              accessibilityLabel="Back to Allies"
              accessibilityRole="button"
              hitSlop={8}
              onPress={onBack}
              style={({ pressed }) => [
                styles.headerButton,
                { backgroundColor: theme.controlSurface },
                pressed && styles.buttonPressed,
              ]}>
              <Image
                accessibilityLabel=""
                contentFit="contain"
                source={require('@/assets/allies/icons/back-chevron-icon.svg')}
                style={[styles.backIcon, { tintColor: theme.icon }]}
              />
            </Pressable>
              <View accessibilityLabel="Ally settings" accessible style={[styles.headerButton, { backgroundColor: theme.controlSurface }]}>
              <SettingsIcon color={theme.icon} />
            </View>
            <Text pointerEvents="none" style={styles.today}>TODAY 9:40 AM</Text>
          </View>

          <ScrollView
            contentContainerStyle={styles.messagesContent}
            keyboardShouldPersistTaps="handled"
            onContentSizeChange={() => scheduleScrollToEnd()}
            onLayout={() => scheduleScrollToEnd()}
            onScroll={({ nativeEvent }) => {
              followLatestRef.current = isConversationNearBottom(
                nativeEvent.contentSize.height,
                nativeEvent.contentOffset.y,
                nativeEvent.layoutMeasurement.height,
              );
            }}
            ref={scrollRef}
            scrollEventThrottle={16}
            showsVerticalScrollIndicator={false}
            style={styles.messagesScroll}>
            {messages.map((message, index) => (
              <ConversationMessage
                ally={ally}
                characterCount={
                  message.id === latestAssistantMessage?.id
                    ? reducedMotion
                      ? message.content.length
                      : typingState?.id === message.id
                        ? typingState.count
                        : 0
                    : message.content.length
                }
                isFirstMessage={index === 0}
                key={message.id}
                message={message}
                reducedMotion={reducedMotion}
              />
            ))}

            <ConversationAllyStatus ally={ally} isReplying={isReplying} reducedMotion={reducedMotion} />
          </ScrollView>

          <View style={styles.composerArea}>
            {attachments.length > 0 ? (
              <View style={[styles.attachmentSummary, { backgroundColor: theme.chatInput }]}>
                <Text numberOfLines={1} style={[styles.attachmentSummaryText, { color: theme.primaryText }]}>
                  {attachments.length === 1
                    ? `${attachments[0].kind === 'folder' ? 'Folder' : 'File'} · ${attachments[0].name}`
                    : `${attachments.length} items ready`}
                </Text>
                <Pressable
                  accessibilityLabel="Remove attachments"
                  accessibilityRole="button"
                  hitSlop={8}
                  onPress={() => {
                    setAttachments([]);
                    setAttachmentError(null);
                  }}
                  style={styles.attachmentRemoveButton}>
                  <Text style={[styles.attachmentRemoveText, { color: theme.primaryText }]}>×</Text>
                </Pressable>
              </View>
            ) : null}
            {attachmentError ? (
              <Text
                accessibilityLiveRegion="polite"
                accessibilityRole="alert"
                style={[styles.attachmentError, { color: theme.errorText }]}
              >
                {attachmentError}
              </Text>
            ) : null}
            <View
              style={[
                styles.composer,
                {
                  backgroundColor: theme.chatInput,
                  borderRadius: getComposerBorderRadius(composerHeight),
                  height: composerHeight,
                },
              ]}>
              <Pressable
                accessibilityLabel="Add files or folder"
                accessibilityRole="button"
                hitSlop={8}
                onPress={handleAddAttachment}
                style={styles.composerAddButton}>
                <Text style={[styles.composerPlus, { color: theme.primaryText }]}>+</Text>
              </Pressable>
              <TextInput
                accessibilityLabel={`Message ${ally.name}`}
                autoCapitalize="sentences"
                autoCorrect
                editable={!isReplying}
                maxLength={4000}
                multiline
                onChangeText={(value) => {
                  setDraft(value);
                  if (!value) setComposerHeight(COMPOSER_MIN_HEIGHT);
                }}
                onContentSizeChange={({ nativeEvent }) =>
                  setComposerHeight(getComposerHeight(nativeEvent.contentSize.height, draft.length > 0))
                }
                onSubmitEditing={handleSend}
                onFocus={() => scheduleScrollToEnd()}
                placeholder={`Ask ${ally.name}`}
                placeholderTextColor={theme.placeholderText}
                selectionColor={ally.color}
                scrollEnabled={shouldScrollComposer(draft, composerHeight)}
                style={[styles.composerInput, { color: theme.primaryText }]}
                textAlignVertical="center"
                value={draft}
              />
              <Pressable
                accessibilityLabel="Send message"
                accessibilityRole="button"
                accessibilityState={{ disabled: !canSend }}
                disabled={!canSend}
                onPress={handleSend}
                style={({ pressed }) => [
                  styles.sendButton,
                  composerHeight > COMPOSER_MIN_HEIGHT && styles.sendButtonExpanded,
                  pressed && styles.buttonPressed,
                ]}>
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
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

function ConversationMessage({
  ally,
  characterCount,
  isFirstMessage,
  message,
  reducedMotion,
}: {
  ally: MockAlly;
  characterCount: number;
  isFirstMessage: boolean;
  message: MockMessage;
  reducedMotion: boolean;
}) {
  const theme = useTheme();
  const isUser = message.sender === 'user';
  const entering = reducedMotion
    ? undefined
    : FadeIn.duration(180).easing(Easing.out(Easing.cubic));

  if (isUser) {
    return (
      <Animated.View
        entering={entering}
        style={[styles.userMessage, isFirstMessage && styles.firstMessage, { backgroundColor: ally.color }]}
      >
        {message.attachments?.map((attachment, index) => (
          <View key={`${attachment.kind}-${attachment.uri}-${index}`} style={styles.attachmentChip}>
            <Text numberOfLines={1} style={styles.attachmentChipText}>
              {attachment.kind === 'folder' ? 'Folder' : 'File'} · {attachment.name}
            </Text>
          </View>
        ))}
        {message.content ? <Text style={styles.userMessageText}>{message.content}</Text> : null}
      </Animated.View>
    );
  }

  const displayCharacterCount = Math.max(0, Math.min(message.content.length, characterCount));
  return (
    <Animated.View entering={entering} style={[styles.allyMessage, isFirstMessage && styles.firstMessage]}>
      {message.content.includes('\n\n') ? (
        <OnboardingTypewriterText
          boldStyle={[styles.messageTextBold, { color: theme.primaryText }]}
          characterCount={displayCharacterCount}
          greeting={message.content}
          style={[styles.messageText, { color: theme.primaryText }]}
        />
      ) : (
        <Text style={[styles.messageText, { color: theme.primaryText }]}>{message.content.slice(0, displayCharacterCount)}</Text>
      )}
    </Animated.View>
  );
}

function ConversationAllyStatus({
  ally,
  isReplying,
  reducedMotion,
}: {
  ally: MockAlly;
  isReplying: boolean;
  reducedMotion: boolean;
}) {
  const theme = useTheme();
  const entering = reducedMotion
    ? undefined
    : FadeIn.duration(180).easing(Easing.out(Easing.cubic));

  return (
    <Animated.View
      entering={entering}
      layout={reducedMotion ? undefined : ALLY_STATUS_LAYOUT}
      style={styles.allyStatusRow}>
      <OnboardingAllyPreview
        accessibilityLabel={isReplying ? `${ally.name} is thinking` : `${ally.name} Ally`}
        allowDownscaling={false}
        artworkScale={0.86}
        color={ally.color}
        identity={ally.shape}
        size={CONVERSATION_ALLY_SIZE}
        state={isReplying ? 'thinking' : 'idle'}
      />
      {isReplying ? (
        <View style={styles.thinkingTextOffset}>
          <ShinyText
            accessibilityLabel="Thinking"
            color={ally.color}
            paused={false}
            shineColor={theme.shimmerHighlight}
            style={styles.thinkingText}>
            Thinking…
          </ShinyText>
        </View>
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
  allyMessage: {
    marginTop: 22,
  },
  attachmentChip: {
    backgroundColor: 'rgba(255, 255, 255, 0.18)',
    borderRadius: 12,
    marginBottom: 6,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  attachmentChipText: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeMedium',
    fontSize: 13,
    includeFontPadding: false,
    lineHeight: 16,
  },
  attachmentError: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 12,
    lineHeight: 16,
    paddingBottom: 4,
    paddingHorizontal: 4,
  },
  attachmentRemoveButton: {
    alignItems: 'center',
    height: 24,
    justifyContent: 'center',
    width: 24,
  },
  attachmentRemoveText: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 20,
    includeFontPadding: false,
    lineHeight: 20,
  },
  attachmentSummary: {
    alignItems: 'center',
    borderRadius: 12,
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 6,
    paddingLeft: 12,
    paddingRight: 4,
    paddingVertical: 4,
  },
  attachmentSummaryText: {
    flex: 1,
    fontFamily: 'OpenRundeMedium',
    fontSize: 13,
    includeFontPadding: false,
    lineHeight: 16,
  },
  allyStatusRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    marginTop: 22,
  },
  backIcon: {
    height: 14,
    width: 8,
  },
  buttonPressed: {
    opacity: 0.76,
    transform: [{ scale: 0.96 }],
  },
  composer: {
    alignItems: 'center',
    flexDirection: 'row',
    overflow: 'hidden',
    paddingLeft: 14,
    paddingRight: 6,
    width: '100%',
  },
  composerAddButton: {
    alignItems: 'center',
    height: 32,
    justifyContent: 'center',
    left: 0,
    position: 'absolute',
    width: 14,
  },
  composerArea: {
    paddingHorizontal: COMPOSER_HORIZONTAL_PADDING,
    paddingBottom: 12,
  },
  composerInput: {
    ...ONBOARDING_PREVIEW_COMPOSER_TEXT_STYLE,
    flex: 1,
    includeFontPadding: false,
    maxHeight: COMPOSER_MAX_HEIGHT - 8,
    paddingHorizontal: 0,
    paddingVertical: 8,
  },
  composerPlus: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 24,
    includeFontPadding: false,
    lineHeight: 24,
    textAlign: 'center',
    width: 14,
  },
  content: {
    flex: 1,
  },
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    left: 0,
    paddingHorizontal: SCREEN_HORIZONTAL_PADDING,
    paddingTop: 10,
    position: 'absolute',
    right: 0,
    top: 0,
    zIndex: 1,
  },
  headerButton: {
    alignItems: 'center',
    borderRadius: 999,
    height: 40,
    justifyContent: 'center',
    width: 40,
  },
  firstMessage: {
    marginTop: 0,
  },
  messageText: {
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    includeFontPadding: false,
    letterSpacing: -0.5,
    lineHeight: 22,
  },
  messageTextBold: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 16,
    includeFontPadding: false,
    letterSpacing: -0.5,
    lineHeight: 22,
  },
  messagesContent: {
    paddingBottom: 20,
    paddingHorizontal: SCREEN_HORIZONTAL_PADDING,
    paddingTop: CONVERSATION_INITIAL_CONTENT_OFFSET,
  },
  messagesScroll: {
    flex: 1,
  },
  root: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  sendBackground: {
    borderRadius: 999,
  },
  sendButton: {
    alignItems: 'center',
    borderRadius: 999,
    height: 40,
    justifyContent: 'center',
    overflow: 'hidden',
    position: 'relative',
    width: 40,
  },
  sendButtonExpanded: {
    alignSelf: 'flex-end',
    marginBottom: 4,
  },
  sendIcon: {
    height: 18,
    width: 18,
  },
  thinkingText: {
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
    includeFontPadding: false,
    letterSpacing: -0.35,
    lineHeight: 18,
  },
  thinkingTextOffset: {
    transform: [{ translateY: 1 }],
  },
  today: {
    color: '#A0A0A0',
    fontFamily: 'OpenRundeMedium',
    fontSize: 12,
    includeFontPadding: false,
    letterSpacing: -0.5,
    lineHeight: 12,
    position: 'absolute',
    left: 0,
    right: 0,
    textAlign: 'center',
    top: 24,
  },
  userMessage: {
    alignSelf: 'flex-end',
    borderRadius: 22,
    marginTop: 22,
    maxWidth: '84%',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  userMessageText: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    includeFontPadding: false,
    letterSpacing: -0.5,
    lineHeight: 18,
  },
});
