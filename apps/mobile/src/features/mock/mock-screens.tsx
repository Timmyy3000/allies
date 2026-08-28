import { Image } from 'expo-image';
import { useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
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
import { SafeAreaView } from 'react-native-safe-area-context';
import { useReducedMotion } from 'react-native-reanimated';

import { PrimaryButton } from '@/components/ui/primary-button';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import {
  PreviewCard,
  PreviewListRow,
  PreviewPage,
  PreviewSectionTitle,
} from '@/features/app-preview/preview-ui';

import { useMockApp, type MockMessage } from './mock-app';

export function MockAlliesScreen() {
  const mock = useMockApp();
  const router = useRouter();

  return (
    <PreviewPage
      activeRoot="allies"
      subtitle="A trusted team that keeps your work moving."
      title="Your Allies">
      <View style={styles.welcomeCard}>
        <Text style={styles.eyebrow}>GOOD TO SEE YOU, {mock.account.displayName.toUpperCase()}</Text>
        <Text style={styles.welcomeTitle}>What can your Allies help you move forward today?</Text>
      </View>
      <View style={styles.sectionRow}>
        <PreviewSectionTitle>Ready for you</PreviewSectionTitle>
        <Pressable accessibilityRole="button" onPress={() => router.push('/allies/new')}>
          <Text style={styles.addText}>+ New Ally</Text>
        </Pressable>
      </View>
      {mock.allies.map((ally) => (
        <Pressable
          accessibilityLabel={`Open ${ally.name}`}
          accessibilityRole="button"
          key={ally.id}
          onPress={() => router.push(`/allies/${ally.id}` as never)}
          style={({ pressed }) => [styles.allyCard, pressed && styles.pressed]}>
          <OnboardingAllyPreview
            accessibilityLabel={`${ally.name} Ally`}
            color={ally.color}
            identity={ally.shape}
            size={76}
          />
          <View style={styles.allyCopy}>
            <Text numberOfLines={1} style={styles.allyName}>{ally.name}</Text>
            <Text numberOfLines={2} style={styles.allyJob}>{ally.job}</Text>
            <Text style={[styles.readyText, { color: ally.color }]}>Ready</Text>
          </View>
          <Text style={styles.chevron}>›</Text>
        </Pressable>
      ))}
    </PreviewPage>
  );
}

export function MockConversationScreen() {
  const mock = useMockApp();
  const router = useRouter();
  const [draft, setDraft] = useState('');
  const scrollView = useRef<ScrollView>(null);
  const canSend = draft.trim().length > 0 && !mock.isReplying;

  const send = () => {
    if (!canSend) return;
    mock.sendMessage(draft);
    setDraft('');
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.conversationRoot}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.conversationHeader}>
          <Pressable
            accessibilityLabel="Back to Allies"
            accessibilityRole="button"
            onPress={() => router.replace('/allies')}
            style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}>
            <Image
              accessibilityLabel=""
              contentFit="contain"
              source={require('@/assets/allies/icons/back-chevron-icon.svg')}
              style={styles.backIcon}
            />
          </Pressable>
          <View style={styles.headerIdentity}>
            <OnboardingAllyPreview
              accessibilityLabel={`${mock.activeAlly.name} Ally`}
              color={mock.activeAlly.color}
              identity={mock.activeAlly.shape}
              size={34}
            />
            <Text numberOfLines={1} style={styles.headerName}>{mock.activeAlly.name}</Text>
          </View>
          <Pressable
            accessibilityLabel="Open Ally identity"
            accessibilityRole="button"
            onPress={() => router.push(`/allies/${mock.activeAlly.id}/identity` as never)}
            style={({ pressed }) => [styles.infoButton, pressed && styles.pressed]}>
            <Text style={styles.infoText}>i</Text>
          </Pressable>
        </View>

        <ScrollView
          contentContainerStyle={styles.messages}
          keyboardShouldPersistTaps="handled"
          onContentSizeChange={() => scrollView.current?.scrollToEnd({ animated: true })}
          ref={scrollView}
          showsVerticalScrollIndicator={false}>
          <Text style={styles.today}>Today</Text>
          {mock.messages.map((message, index) => (
            <MessageBubble
              animate={message.sender === 'assistant' && index === mock.messages.length - 1 && message.id !== 'welcome'}
              allyName={mock.activeAlly.name}
              key={message.id}
              message={message}
            />
          ))}
          {mock.isReplying ? (
            <View style={styles.thinkingRow}>
              <OnboardingAllyPreview
                accessibilityLabel={`${mock.activeAlly.name} is thinking`}
                color={mock.activeAlly.color}
                identity={mock.activeAlly.shape}
                size={26}
                state="thinking"
              />
              <Text style={[styles.thinkingText, { color: mock.activeAlly.color }]}>Thinking…</Text>
            </View>
          ) : null}
        </ScrollView>

        <View style={styles.composerRow}>
          <View style={styles.composer}>
            <TextInput
              accessibilityLabel={`Message ${mock.activeAlly.name}`}
              editable={!mock.isReplying}
              maxLength={4000}
              multiline
              onChangeText={setDraft}
              onSubmitEditing={send}
              placeholder={`Message ${mock.activeAlly.name}`}
              placeholderTextColor="#A0A0A0"
              style={styles.composerInput}
              value={draft}
            />
            <Pressable
              accessibilityLabel="Send message"
              accessibilityRole="button"
              accessibilityState={{ disabled: !canSend }}
              disabled={!canSend}
              onPress={send}
              style={[styles.sendButton, !canSend && styles.sendButtonDisabled]}>
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

export function MockAccountScreen() {
  const mock = useMockApp();
  return (
    <PreviewPage backHref="/settings" subtitle="Your personal Allies profile and workspace." title="Your account">
      <View style={styles.profileHero}>
        <View style={styles.profileInitial}><Text style={styles.profileInitialText}>{mock.account.displayName.charAt(0)}</Text></View>
        <Text style={styles.profileName}>{mock.account.displayName}</Text>
        <Text style={styles.profileEmail}>{mock.account.email}</Text>
      </View>
      <PreviewSectionTitle>Profile</PreviewSectionTitle>
      <PreviewCard>
        <AccountDetail label="Username" value={`@${mock.account.username}`} />
        <AccountDetail label="Workspace" value={mock.account.workspaceName} />
        <AccountDetail label="Account access" value="Google and password" />
      </PreviewCard>
      <PreviewListRow detail="Password, Google, and signed-in devices" href="/settings/account-security" label="Account and security" />
    </PreviewPage>
  );
}

export function MockIdentityScreen() {
  const mock = useMockApp();
  const ally = mock.activeAlly;
  return (
    <PreviewPage backHref={`/allies/${ally.id}`} subtitle="The role, character, and appearance that make this Ally yours." title="Ally identity">
      <View style={styles.identityHero}>
        <OnboardingAllyPreview accessibilityLabel={`${ally.name} Ally`} color={ally.color} identity={ally.shape} size={120} />
        <Text style={styles.identityName}>{ally.name}</Text>
        <Text style={[styles.readyText, { color: ally.color }]}>Ready</Text>
      </View>
      <PreviewCard>
        <AccountDetail label="Job" value={ally.job} />
        <AccountDetail label="Personality" value={ally.personality} />
        <AccountDetail label="Appearance" value={`${ally.shape} · ${ally.color}`} />
      </PreviewCard>
      <PreviewListRow detail="Identity, routines, access, and deletion" href={`/allies/${ally.id}/settings`} label="Open Ally settings" tone="red" />
    </PreviewPage>
  );
}

export function MockCompleteScreen() {
  const mock = useMockApp();
  const router = useRouter();
  return (
    <View style={styles.completeRoot}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.completeSafeArea}>
        <View style={styles.completeContent}>
          <OnboardingAllyPreview
            accessibilityLabel={`${mock.activeAlly.name} Ally`}
            color={mock.activeAlly.color}
            identity={mock.activeAlly.shape}
            size={140}
          />
          <Text style={styles.completeTitle}>Your Ally is ready</Text>
          <Text style={styles.completeBody}>{mock.activeAlly.name} is ready to help you make progress, one clear next step at a time.</Text>
          <PrimaryButton label="Start chatting" onPress={() => router.replace(`/allies/${mock.activeAlly.id}` as never)} />
        </View>
      </SafeAreaView>
    </View>
  );
}

function MessageBubble({ allyName, animate, message }: { allyName: string; animate: boolean; message: MockMessage }) {
  const reducedMotion = useReducedMotion();
  const [characterCount, setCharacterCount] = useState(animate && !reducedMotion ? 0 : message.content.length);

  useEffect(() => {
    if (!animate || reducedMotion) return undefined;
    const timer = setInterval(() => {
      setCharacterCount((current) => {
        const next = Math.min(message.content.length, current + 4);
        if (next === message.content.length) clearInterval(timer);
        return next;
      });
    }, 16);
    return () => clearInterval(timer);
  }, [animate, message.content, reducedMotion]);

  const isUser = message.sender === 'user';
  return (
    <View style={[styles.messageBubble, isUser ? styles.userBubble : styles.allyBubble]}>
      <Text style={styles.messageSender}>{isUser ? 'You' : allyName}</Text>
      <Text style={styles.messageContent}>{message.content.slice(0, characterCount)}</Text>
    </View>
  );
}

function AccountDetail({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.accountDetail}>
      <Text style={styles.accountLabel}>{label}</Text>
      <Text style={styles.accountValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  accountDetail: { borderBottomColor: '#DEDEDE', borderBottomWidth: 1, paddingVertical: 16 },
  accountLabel: { color: '#777777', fontFamily: 'OpenRundeSemibold', fontSize: 12, textTransform: 'uppercase' },
  accountValue: { color: '#111111', fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginTop: 6 },
  addText: { color: '#FF5800', fontFamily: 'OpenRundeSemibold', fontSize: 14 },
  allyBubble: { alignSelf: 'flex-start', backgroundColor: '#F3F3F3' },
  allyCard: { alignItems: 'center', borderColor: '#EAEAEA', borderRadius: 28, borderWidth: 1, flexDirection: 'row', marginTop: 12, padding: 16 },
  allyCopy: { flex: 1, marginLeft: 16 },
  allyJob: { color: '#686868', fontFamily: 'OpenRundeMedium', fontSize: 14, lineHeight: 19, marginTop: 4 },
  allyName: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 20, letterSpacing: -0.5, lineHeight: 25 },
  backButton: { alignItems: 'center', backgroundColor: '#F3F3F3', borderRadius: 20, height: 40, justifyContent: 'center', width: 40 },
  backIcon: { height: 18, width: 18 },
  chevron: { color: '#B0B0B0', fontFamily: 'OpenRundeMedium', fontSize: 30, marginLeft: 8 },
  composer: { alignItems: 'flex-end', backgroundColor: '#F3F3F3', borderRadius: 28, flexDirection: 'row', minHeight: 54, paddingBottom: 6, paddingLeft: 18, paddingRight: 6, paddingTop: 6 },
  composerInput: { color: '#111111', flex: 1, fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 21, maxHeight: 110, minHeight: 42, paddingVertical: 10 },
  composerRow: { backgroundColor: '#FFFFFF', paddingHorizontal: 16, paddingTop: 10 },
  conversationHeader: { alignItems: 'center', borderBottomColor: '#EFEFEF', borderBottomWidth: 1, flexDirection: 'row', minHeight: 72, paddingHorizontal: 16 },
  conversationRoot: { backgroundColor: '#FFFFFF', flex: 1 },
  completeBody: { color: '#606060', fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginBottom: 30, marginTop: 12, maxWidth: 310, textAlign: 'center' },
  completeContent: { alignItems: 'center', flex: 1, justifyContent: 'center', paddingHorizontal: 28 },
  completeRoot: { backgroundColor: '#FFFFFF', flex: 1 },
  completeSafeArea: { flex: 1 },
  completeTitle: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 30, letterSpacing: -1, lineHeight: 36, marginTop: 26, textAlign: 'center' },
  eyebrow: { color: '#FF5800', fontFamily: 'OpenRundeSemibold', fontSize: 11, letterSpacing: 0.8 },
  headerIdentity: { alignItems: 'center', flex: 1, flexDirection: 'row', justifyContent: 'center', paddingHorizontal: 8 },
  headerName: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 18, letterSpacing: -1, lineHeight: 24, marginLeft: 10, maxWidth: 180 },
  identityHero: { alignItems: 'center', paddingVertical: 12 },
  identityName: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 28, letterSpacing: -1, lineHeight: 36, marginTop: 16 },
  infoButton: { alignItems: 'center', borderColor: '#D9D9D9', borderRadius: 20, borderWidth: 1.5, height: 40, justifyContent: 'center', width: 40 },
  infoText: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 16 },
  messageBubble: { borderRadius: 22, marginTop: 14, maxWidth: '88%', paddingHorizontal: 16, paddingVertical: 13 },
  messageContent: { color: '#111111', fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginTop: 5 },
  messageSender: { color: '#777777', fontFamily: 'OpenRundeSemibold', fontSize: 12 },
  messages: { flexGrow: 1, paddingBottom: 18, paddingHorizontal: 16 },
  pressed: { opacity: 0.72, transform: [{ scale: 0.99 }] },
  profileEmail: { color: '#6F6F6F', fontFamily: 'OpenRundeMedium', fontSize: 15, marginTop: 4 },
  profileHero: { alignItems: 'center', paddingVertical: 12 },
  profileInitial: { alignItems: 'center', backgroundColor: '#FF5800', borderRadius: 48, height: 96, justifyContent: 'center', width: 96 },
  profileInitialText: { color: '#FFFFFF', fontFamily: 'OpenRundeSemibold', fontSize: 38 },
  profileName: { color: '#111111', fontFamily: 'OpenRundeSemibold', fontSize: 26, letterSpacing: -1, lineHeight: 33, marginTop: 14 },
  readyText: { fontFamily: 'OpenRundeSemibold', fontSize: 13, marginTop: 8 },
  safeArea: { flex: 1 },
  sectionRow: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', marginTop: 10 },
  sendButton: { alignItems: 'center', backgroundColor: '#FF5800', borderRadius: 21, height: 42, justifyContent: 'center', width: 42 },
  sendButtonDisabled: { backgroundColor: '#D8D8D8' },
  sendIcon: { height: 18, width: 18 },
  thinkingRow: { alignItems: 'center', flexDirection: 'row', gap: 9, marginTop: 18 },
  thinkingText: { fontFamily: 'OpenRundeSemibold', fontSize: 14 },
  today: { alignSelf: 'center', color: '#999999', fontFamily: 'OpenRundeSemibold', fontSize: 12, marginBottom: 4, marginTop: 12 },
  userBubble: { alignSelf: 'flex-end', backgroundColor: '#FFF0E8' },
  welcomeCard: { backgroundColor: '#111111', borderRadius: 28, padding: 22 },
  welcomeTitle: { color: '#FFFFFF', fontFamily: 'OpenRundeSemibold', fontSize: 23, letterSpacing: -0.7, lineHeight: 29, marginTop: 9 },
});
