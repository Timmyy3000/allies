import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';
import { Image } from 'expo-image';
import { useIsFocused, useLocalSearchParams, useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  ACTIVE_ACTIVITY_STATES,
  EMPTY_ACTIVITY_PROJECTION,
  hasPermanentActivityGap,
  projectActivitySnapshot,
  type ActivityProjection,
  type ActivitySnapshotViewModel,
  type AllyViewModel,
  type ConversationViewModel,
  type MessageViewModel,
} from '@allies/cloud-client';
import * as Crypto from 'expo-crypto';

import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { useAllySessionIndex } from '@/features/allies/ally-session-index';
import { getAllyAppearance } from '@/features/allies/ally-appearance';
import { pendingCommandStore, type PendingMessageCommand } from '@/lib/pending-command-store';
import { useNativeSession } from '@/lib/session/session-context';
import { useMockApp } from '@/features/mock/mock-app';
import { MockConversationScreen } from '@/features/mock/mock-screens';

import {
  createConversationScrollIntent,
  insertAcceptedMessage,
  isActivityPollingAllowed,
  isMessageTerminal,
  mergeConversationMessages,
  queuedConversationMessages,
  replaceNewestConversationPage,
  shouldKeepPendingMessage,
} from '@/features/conversation/conversation-state';

const MESSAGE_MAX_LENGTH = 4000;
const CONVERSATION_PAGE_LIMIT = 50;
const ACTIVITY_LIMIT = 200;

function allyIdFromParam(value: string | string[] | undefined): string | null {
  const allyId = Array.isArray(value) ? value[0] : value;
  return allyId?.trim() || null;
}

function activityLabel(state: string): string {
  return {
    queued: 'Queued',
    in_progress: 'In progress',
    running: 'Working',
    awaiting_action: 'Waiting for you',
    completed: 'Complete',
    failed: 'Could not complete',
    stopped: 'Stopped',
    reconciliation_needed: 'Needs reconciliation',
    unknown: 'Status unavailable',
  }[state] ?? 'Status unavailable';
}

function messageLabel(sender: string): string {
  if (sender === 'user') return 'You';
  if (sender === 'assistant') return 'Ally';
  return 'Message';
}

export default function AllyConversationScreen() {
  const mock = useMockApp();
  const session = useNativeSession();
  const { allyId } = useLocalSearchParams<{ allyId?: string }>();
  return mock.isMock ? <MockConversationScreen /> : (
    <CloudAllyConversationScreen key={`${session.account?.userId ?? ''}:${session.account?.workspace.id ?? ''}:${allyId ?? ''}`} />
  );
}

function CloudAllyConversationScreen() {
  const { allyId: allyIdParam } = useLocalSearchParams<{ allyId?: string }>();
  const allyId = allyIdFromParam(allyIdParam);
  const router = useRouter();
  const focused = useIsFocused();
  const insets = useSafeAreaInsets();
  const session = useNativeSession();
  const queryClient = useQueryClient();
  const { addReachableAllyId } = useAllySessionIndex();
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [foreground, setForeground] = useState(AppState.currentState === 'active');
  const mounted = useRef(true);
  const mutation = useRef<AbortController | null>(null);
  const conversationReadGeneration = useRef(0);
  const [message, setMessage] = useState<string | null>(null);
  const [pendingMessage, setPendingMessage] = useState<PendingMessageCommand | null>(null);
  const [pendingLoaded, setPendingLoaded] = useState(false);
  const [activityProjection, setActivityProjection] = useState<ActivityProjection>(EMPTY_ACTIVITY_PROJECTION);
  const conversationScrollRef = useRef<ScrollView>(null);
  const scrollIntent = useRef(createConversationScrollIntent()).current;
  const pollingStartedAt = useRef<number | null>(null);
  const pollingConversationId = useRef<string | null>(null);
  const projectionConversationId = useRef<string | null>(null);
  const wasFocused = useRef(focused);

  useEffect(() => {
    mounted.current = true;
    const listener = AppState.addEventListener('change', (state) => setForeground(state === 'active'));
    return () => {
      mounted.current = false;
      mutation.current?.abort();
      listener.remove();
    };
  }, []);

  const workspaceId = session.status === 'signed-in' && session.account ? session.account.workspace.id : '';
  const canRequest = Boolean(allyId && workspaceId && session.accountClient && session.adapter);
  const conversationQueryKey = useMemo(
    () => ['workspaces', workspaceId, 'allies', allyId, 'conversation'] as const,
    [allyId, workspaceId],
  );
  const refreshNewestConversation = useCallback(async (signal?: AbortSignal) => {
    if (!allyId || !workspaceId || !session.accountClient || !session.adapter) return;
    const generation = ++conversationReadGeneration.current;
    const newest = await session.adapter.withRefresh(() => session.accountClient!.getAllyConversation(
      workspaceId,
      allyId,
      { limit: CONVERSATION_PAGE_LIMIT, signal },
    ));
    if (!mounted.current || signal?.aborted || generation !== conversationReadGeneration.current) return;
    queryClient.setQueryData<InfiniteData<ConversationViewModel, string | null>>(
      conversationQueryKey,
      (current) => current ? { ...current, pages: replaceNewestConversationPage(current.pages, newest) } : current,
    );
  }, [allyId, conversationQueryKey, queryClient, session.accountClient, session.adapter, workspaceId]);
  const allyQuery = useQuery<AllyViewModel>({
    queryKey: ['allies', workspaceId, allyId],
    enabled: canRequest,
    queryFn: ({ signal }) => session.adapter!.withRefresh(() => session.accountClient!.getAlly(workspaceId, allyId!, signal)),
    refetchOnWindowFocus: false,
  });
  const conversationQuery = useInfiniteQuery({
    queryKey: conversationQueryKey,
    enabled: canRequest,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => session.adapter!.withRefresh(() => session.accountClient!.getAllyConversation(
      workspaceId,
      allyId!,
      { limit: CONVERSATION_PAGE_LIMIT, cursor: pageParam ?? undefined, signal },
    )),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    refetchOnWindowFocus: false,
  });
  const conversationId = conversationQuery.data?.pages[0]?.id ?? null;
  const hasQueuedMessages = Boolean(conversationQuery.data?.pages[0]?.queue?.length);
  useEffect(() => {
    if (!canRequest || !conversationId || !focused || !foreground) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    const poll = async () => {
      try {
        await refreshNewestConversation(controller.signal);
        failures = 0;
      } catch {
        failures += 1;
      }
      if (!controller.signal.aborted) schedule();
    };
    const schedule = () => {
      timer = setTimeout(() => void poll(), failures
        ? Math.min(30_000, 3000 * 2 ** Math.min(failures, 4))
        : hasQueuedMessages ? 3000 : 10_000);
    };
    schedule();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [canRequest, conversationId, focused, foreground, hasQueuedMessages, refreshNewestConversation]);
  const activityQuery = useQuery({
    queryKey: ['workspaces', workspaceId, 'conversations', conversationId, 'activities'],
    enabled: Boolean(canRequest && conversationId),
    queryFn: ({ signal }) => session.adapter!.withRefresh(() => session.accountClient!.getActivities(
      workspaceId,
      conversationId!,
      ACTIVITY_LIMIT,
      signal,
    )),
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const state = (query.state.data as ActivitySnapshotViewModel | undefined)?.state ?? 'unknown';
      if (pollingConversationId.current !== conversationId) {
        pollingConversationId.current = conversationId;
        pollingStartedAt.current = null;
      }
      if (!focused || !foreground) return false;
      if (query.state.error) return 30_000;
      if (!hasQueuedMessages && !ACTIVE_ACTIVITY_STATES.includes(state as ActivitySnapshotViewModel['state'])) {
        pollingStartedAt.current = null;
        return false;
      }
      pollingStartedAt.current ??= Date.now();
      return isActivityPollingAllowed({
        focused,
        state,
        startedAt: pollingStartedAt.current,
        now: Date.now(),
      }) ? 3000 : 30_000;
    },
  });
  const refetchAlly = allyQuery.refetch;
  const refetchActivity = activityQuery.refetch;
  const activeMessageId = activityQuery.data?.activeMessageId;
  const activityState = activityQuery.data?.state;

  useEffect(() => {
    if (!activityQuery.data || !conversationId) return;
    setActivityProjection((current) => {
      if (projectionConversationId.current !== conversationId) {
        projectionConversationId.current = conversationId;
        return projectActivitySnapshot(EMPTY_ACTIVITY_PROJECTION, activityQuery.data);
      }
      return projectActivitySnapshot(current, activityQuery.data);
    });
  }, [activityQuery.data, activityQuery.dataUpdatedAt, conversationId]);

  useEffect(() => {
    if (activityState === undefined) return;
    const controller = new AbortController();
    void refreshNewestConversation(controller.signal).catch(() => undefined);
    return () => controller.abort();
  }, [activeMessageId, activityState, refreshNewestConversation]);

  useEffect(() => {
    const visible = focused && foreground;
    const regainedFocus = visible && !wasFocused.current;
    wasFocused.current = visible;
    if (!regainedFocus) return;
    void Promise.all([refetchAlly(), refreshNewestConversation(), refetchActivity()]).catch(() => undefined);
  }, [focused, foreground, refetchActivity, refetchAlly, refreshNewestConversation]);

  useEffect(() => {
    if (!conversationId || session.status !== 'signed-in' || !session.account) return;
    let active = true;
    void pendingCommandStore.readMessage(
      conversationId,
      session.account.userId,
      session.account.workspace.id,
    ).then((command) => {
      if (active) {
        setPendingMessage(command);
        if (command) setDraft(command.content);
        setPendingLoaded(true);
      }
    }).catch(() => {
      if (active) setMessage('We could not read your saved message. Reopen this conversation to retry.');
    });
    return () => {
      active = false;
    };
  }, [conversationId, session.account, session.status]);

  useEffect(() => {
    if (allyQuery.data && allyId) {
      addReachableAllyId(allyId);
    }
  }, [addReachableAllyId, allyId, allyQuery.data]);

  const conversationPages = conversationQuery.data?.pages;
  const messages = useMemo(() => {
    if (!conversationPages?.length) return { items: [] as MessageViewModel[], conflict: false };
    try {
      return { items: mergeConversationMessages(conversationPages), conflict: false };
    } catch {
      return { items: [] as MessageViewModel[], conflict: true };
    }
  }, [conversationPages]);
  const queuedMessages = useMemo(
    () => queuedConversationMessages(conversationPages ?? [], activityProjection),
    [conversationPages, activityProjection],
  );
  const queuedIds = new Set(queuedMessages.map((item) => item.id));

  if (!allyId) return <ErrorState message="This Ally link is not valid." onBack={() => router.replace('/allies' as never)} />;
  if (session.status === 'offline-with-session' || session.status === 'unavailable') {
    return (
      <ErrorState
        message={session.status === 'offline-with-session'
          ? 'You are offline. Reconnect to load this conversation.'
          : 'Your session is unavailable on this device.'}
        onBack={() => router.replace('/allies' as never)}
        onRetry={() => void session.restore()}
      />
    );
  }
  if (allyQuery.isPending || conversationQuery.isPending) return <LoadingState />;
  if (allyQuery.isError || !allyQuery.data || conversationQuery.isError || !conversationQuery.data) {
    const loadMessage = allyQuery.data?.retryable
      ? 'This Ally needs a retry before its conversation is ready.'
      : 'We could not load this Ally.';
    return (
      <ErrorState
        message={loadMessage}
        onBack={() => router.replace('/allies' as never)}
        onRetry={() => void Promise.all([allyQuery.refetch(), conversationQuery.refetch()])}
      />
    );
  }

  const ally = allyQuery.data;
  const appearance = getAllyAppearance(ally.appearance.key);
  const canSend = pendingLoaded && Boolean((pendingMessage?.content ?? draft).trim()) && !sending && !deletingId && session.status === 'signed-in';

  const send = async () => {
    if (!canSend || mutation.current || !conversationId || !session.account || !session.accountClient || !session.adapter) return;
    const command: PendingMessageCommand = pendingMessage ?? {
      kind: 'message',
      conversationId,
      content: draft,
      idempotencyKey: Crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      boundUserId: session.account.userId,
      boundWorkspaceId: session.account.workspace.id,
    };

    setSending(true);
    setMessage(null);
    const controller = new AbortController();
    mutation.current = controller;
    try {
      if (!pendingMessage) {
        await pendingCommandStore.saveMessage(command);
        setPendingMessage(command);
      }
      if (!mounted.current) return;
      const acceptance = await session.adapter.withRefresh(() => session.accountClient!.sendMessage(
        session.account!.workspace.id,
        command.conversationId,
        command.content,
        command.idempotencyKey,
        controller.signal,
      ));
      if (!mounted.current) return;
      conversationReadGeneration.current += 1;
      await queryClient.cancelQueries({ queryKey: conversationQueryKey });
      if (!mounted.current) return;
      let cacheConflict = false;
      try {
        scrollIntent.requestLatest();
        queryClient.setQueryData<InfiniteData<ConversationViewModel, string | null>>(
          conversationQueryKey,
          (current) => current ? { ...current, pages: insertAcceptedMessage(current.pages, acceptance.message) } : current,
        );
      } catch {
        cacheConflict = true;
      }
      try {
        await pendingCommandStore.deleteMessage(conversationId, command.idempotencyKey);
      } catch {
        setMessage('Your message was accepted, but its saved retry could not be cleared. Retry once to confirm it.');
        return;
      }
      if (!mounted.current) return;
      setPendingMessage(null);
      setDraft('');
      try {
        if (isMessageTerminal(acceptance.message.status)) {
          await Promise.all([refreshNewestConversation(), activityQuery.refetch()]);
        } else {
          await activityQuery.refetch();
        }
      } catch {
        setMessage('Your message was sent. Refresh when your connection is stable.');
      }
      if (cacheConflict) setMessage('Your message was sent, but the conversation data changed unexpectedly. Refresh to reconcile it.');
    } catch (error) {
      if (!mounted.current) return;
      if (shouldKeepPendingMessage(error)) {
        setMessage('We could not confirm your message. Retry the saved message.');
      } else {
        try {
          await pendingCommandStore.deleteMessage(conversationId, command.idempotencyKey);
        } catch {
          setMessage('Your saved message could not be cleared. Retry the same message to confirm it.');
          return;
        }
        if (!mounted.current) return;
        setPendingMessage(null);
        setMessage('We could not send your message. Try again.');
      }
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (mounted.current) setSending(false);
    }
  };

  const removeQueued = async (item: MessageViewModel) => {
    if (item.queueState !== 'unclaimed' || item.status !== 'queued' || item.deletedAt
      || mutation.current || sending || deletingId || !conversationId || !session.accountClient || !session.adapter) return;
    const controller = new AbortController();
    mutation.current = controller;
    setDeletingId(item.id);
    setMessage(null);
    try {
      const deleted = await session.adapter.withRefresh(() =>
        session.accountClient!.deleteQueuedMessage(workspaceId, conversationId, item.id, controller.signal));
      if (!mounted.current) return;
      conversationReadGeneration.current += 1;
      await queryClient.cancelQueries({ queryKey: conversationQueryKey });
      if (!mounted.current) return;
      queryClient.setQueryData<InfiniteData<ConversationViewModel, string | null>>(
        conversationQueryKey,
        (current) => current ? { ...current, pages: insertAcceptedMessage(current.pages, deleted) } : current,
      );
      await refreshNewestConversation(controller.signal);
    } catch {
      if (!mounted.current) return;
      setMessage('We could not confirm removal. The message may have started; refresh or try again.');
      void refreshNewestConversation().catch(() => undefined);
    } finally {
      if (mutation.current === controller) mutation.current = null;
      if (mounted.current) setDeletingId(null);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.root}>
      <StatusBar style="dark" />
      <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
        <View style={styles.header}>
          <Pressable accessibilityLabel="Back to Allies" accessibilityRole="button" onPress={() => router.replace('/allies' as never)} style={styles.headerButton}>
            <Text style={styles.headerButtonText}>Back</Text>
          </Pressable>
          <View style={styles.headerAlly}>
            <OnboardingAllyPreview accessibilityLabel={`${ally.name} Ally`} color={appearance.color} identity={appearance.shape} size={42} />
            <Text numberOfLines={1} style={styles.headerName}>{ally.name}</Text>
          </View>
          <Pressable accessibilityLabel="Open Ally identity" accessibilityRole="button" onPress={() => router.push(`/allies/${ally.id}/identity` as never)} style={styles.headerButton}>
            <Text style={styles.headerButtonText}>Identity</Text>
          </Pressable>
        </View>

        <ScrollView
          contentContainerStyle={styles.conversationContent}
          keyboardShouldPersistTaps="handled"
          maintainVisibleContentPosition={{ minIndexForVisible: 0 }}
          onContentSizeChange={() => {
            if (scrollIntent.consumeLatest()) conversationScrollRef.current?.scrollToEnd({ animated: false });
          }}
          ref={conversationScrollRef}
          showsVerticalScrollIndicator={false}>
          {messages.conflict ? (
            <Text style={styles.errorText}>We received conflicting conversation data. Refresh to try again.</Text>
          ) : messages.items.length ? messages.items.filter((item) => !queuedIds.has(item.id)).map((item) => (
            <View
              key={item.id}
              style={[
                styles.messageBubble,
                item.sender === 'user'
                  ? styles.userBubble
                  : item.sender === 'assistant'
                    ? styles.allyBubble
                    : styles.unknownBubble,
              ]}>
              <Text style={styles.messageSender}>{messageLabel(item.sender)}</Text>
              <Text style={styles.messageContent}>{item.content}</Text>
            </View>
          )) : <Text style={styles.emptyText}>Your conversation will appear here.</Text>}

          {activityProjection.turns.map((turn) => (
            <View key={`${turn.turnOrdinal}:${turn.messageId}`} style={styles.activityBlock}>
              <Text style={styles.activityState}>{activityLabel(turn.state)}</Text>
              <Text style={styles.activityText}>
                {turn.assistantText || turn.state === 'failed'
                  ? turn.assistantText || 'This response failed. Try sending your message again.'
                  : turn.state === 'stopped'
                    ? 'This response was stopped.'
                    : 'Waiting for the Ally response…'}
              </Text>
            </View>
          ))}

          {activityQuery.data ? <Text style={styles.statusText}>{activityLabel(activityProjection.state)}</Text> : null}
          {activityQuery.isError ? (
            <Pressable accessibilityRole="button" onPress={() => void activityQuery.refetch()}>
              <Text style={styles.errorText}>We could not check the latest response status. Tap to retry.</Text>
            </Pressable>
          ) : null}
          {hasPermanentActivityGap(activityProjection) ? (
            <Text style={styles.errorText}>Part of this response is still being reconciled. Refresh to try again.</Text>
          ) : null}
          {conversationQuery.hasNextPage ? (
            <Pressable
              accessibilityRole="button"
              disabled={conversationQuery.isFetchingNextPage}
              onPress={() => {
                scrollIntent.preservePosition();
                void conversationQuery.fetchNextPage();
              }}
              style={styles.loadEarlier}>
              <Text style={styles.loadEarlierText}>{conversationQuery.isFetchingNextPage ? 'Loading…' : 'Load earlier'}</Text>
            </Pressable>
          ) : null}
          {message ? <Text style={styles.errorText}>{message}</Text> : null}
        </ScrollView>

        {queuedMessages.length ? (
          <View accessibilityLabel="Queued messages" style={styles.queue}>
            <Text style={styles.messageSender}>Queued</Text>
            <ScrollView style={styles.queueItems}>
              {queuedMessages.map((item) => (
                <View key={item.id} style={styles.queueRow}>
                  <Text style={styles.queueText}>{item.content}</Text>
                  {item.queueState === 'unclaimed' ? (
                    <Pressable accessibilityRole="button" accessibilityLabel={`Remove queued message: ${item.content}`}
                      disabled={sending || Boolean(deletingId)} onPress={() => void removeQueued(item)}
                      style={styles.queueRemove}>
                      <Text>{deletingId === item.id ? 'Removing…' : 'Remove'}</Text>
                    </Pressable>
                  ) : null}
                </View>
              ))}
            </ScrollView>
          </View>
        ) : null}
        <View style={[styles.composerRow, { paddingBottom: Math.max(12, insets.bottom > 0 ? 8 : 12) }]}>
          <View style={styles.composer}>
            <TextInput
              accessibilityLabel="Message your Ally"
              editable={!pendingMessage && !sending && session.status === 'signed-in'}
              maxLength={MESSAGE_MAX_LENGTH}
              multiline
              onChangeText={setDraft}
              placeholder={pendingMessage ? 'Retry the saved message' : `Message ${ally.name}`}
              placeholderTextColor="#A8A8A8"
              style={styles.composerInput}
              value={draft}
            />
            <Pressable accessibilityLabel={pendingMessage ? 'Retry message' : 'Send message'} accessibilityRole="button" accessibilityState={{ disabled: !canSend }} disabled={!canSend} onPress={() => void send()} style={styles.sendButton}>
              <Image accessibilityLabel="" contentFit="contain" source={require('@/assets/allies/icons/send.svg')} style={styles.sendIcon} />
            </Pressable>
          </View>
          <View style={styles.footerActions}>
            <Pressable
              accessibilityRole="button"
              onPress={() => {
                scrollIntent.requestLatest();
                void Promise.all([refreshNewestConversation(), activityQuery.refetch()]).catch(() => {
                  setMessage('We could not refresh this conversation. Try again.');
                });
              }}>
              <Text style={styles.refreshText}>Refresh</Text>
            </Pressable>
            <Text style={styles.characterCount}>{draft.length}/{MESSAGE_MAX_LENGTH}</Text>
          </View>
        </View>
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

function LoadingState() {
  return (
    <View style={styles.centered}>
      <StatusBar style="dark" />
      <ActivityIndicator color="#FF5800" />
      <Text style={styles.loadingText}>Loading your Ally…</Text>
    </View>
  );
}

function ErrorState({ message, onBack, onRetry }: { message: string; onBack: () => void; onRetry?: () => void }) {
  return (
    <View style={styles.centered}>
      <StatusBar style="dark" />
      <Text style={styles.loadingText}>{message}</Text>
      {onRetry ? (
        <Pressable accessibilityRole="button" onPress={onRetry} style={styles.backAction}>
          <Text style={styles.backActionText}>Try again</Text>
        </Pressable>
      ) : null}
      <Pressable accessibilityRole="button" onPress={onBack} style={styles.backAction}>
        <Text style={styles.backActionText}>Back to Allies</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  queue: { paddingHorizontal: 20, paddingBottom: 12 },
  queueItems: { maxHeight: 140 },
  queueRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 4 },
  queueText: { flex: 1, color: '#606060', fontSize: 14 },
  queueRemove: { padding: 12 },
  activityBlock: {
    borderLeftColor: '#FF5800',
    borderLeftWidth: 2,
    marginTop: 18,
    paddingLeft: 12,
  },
  activityState: {
    color: '#FF5800',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
  },
  activityText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
    lineHeight: 21,
    marginTop: 4,
  },
  allyBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#F3F3F3',
  },
  backAction: {
    backgroundColor: '#FF5800',
    borderRadius: 999,
    marginTop: 22,
    paddingHorizontal: 20,
    paddingVertical: 12,
  },
  backActionText: {
    color: '#FFFFFF',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 15,
  },
  characterCount: {
    color: '#8A8A8A',
    fontFamily: 'OpenRundeMedium',
    fontSize: 12,
  },
  centered: {
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 28,
  },
  composer: {
    alignItems: 'center',
    backgroundColor: '#F3F3F3',
    borderRadius: 20,
    flexDirection: 'row',
    minHeight: 52,
    paddingLeft: 14,
    paddingRight: 6,
  },
  composerInput: {
    color: '#121212',
    flex: 1,
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 21,
    maxHeight: 100,
    paddingHorizontal: 0,
    paddingVertical: 10,
  },
  composerRow: {
    paddingHorizontal: 20,
  },
  conversationContent: {
    paddingBottom: 22,
    paddingHorizontal: 20,
  },
  emptyText: {
    color: '#8A8A8A',
    fontFamily: 'OpenRundeMedium',
    fontSize: 15,
    marginTop: 28,
    textAlign: 'center',
  },
  errorText: {
    color: '#A54242',
    fontFamily: 'OpenRundeMedium',
    fontSize: 14,
    lineHeight: 19,
    marginTop: 18,
    textAlign: 'center',
  },
  footerActions: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 4,
    paddingTop: 8,
  },
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    minHeight: 72,
    paddingHorizontal: 14,
  },
  headerAlly: {
    alignItems: 'center',
    flex: 1,
    flexDirection: 'row',
    justifyContent: 'center',
  },
  headerButton: {
    minWidth: 68,
    paddingHorizontal: 4,
    paddingVertical: 10,
  },
  headerButtonText: {
    color: '#FF5800',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
  },
  headerName: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 18,
    marginLeft: 8,
    maxWidth: 130,
  },
  loadEarlier: {
    alignSelf: 'center',
    borderColor: '#D6D6D6',
    borderRadius: 999,
    borderWidth: 1,
    marginTop: 22,
    paddingHorizontal: 18,
    paddingVertical: 10,
  },
  loadEarlierText: {
    color: '#111111',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 14,
  },
  loadingText: {
    color: '#606060',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    marginTop: 16,
    textAlign: 'center',
  },
  messageBubble: {
    borderRadius: 20,
    marginTop: 14,
    maxWidth: '88%',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  messageContent: {
    color: '#111111',
    fontFamily: 'OpenRundeMedium',
    fontSize: 16,
    lineHeight: 22,
    marginTop: 4,
  },
  messageSender: {
    color: '#7A7A7A',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 12,
  },
  refreshText: {
    color: '#FF5800',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
  },
  root: {
    backgroundColor: '#FFFFFF',
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  sendButton: {
    alignItems: 'center',
    backgroundColor: '#FF5800',
    borderRadius: 999,
    height: 36,
    justifyContent: 'center',
    width: 36,
  },
  sendIcon: {
    height: 18,
    width: 18,
  },
  statusText: {
    color: '#8A8A8A',
    fontFamily: 'OpenRundeSemibold',
    fontSize: 13,
    marginTop: 18,
  },
  userBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#FFF0E8',
  },
  unknownBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#FAFAFA',
    borderColor: '#E5E5E5',
    borderWidth: 1,
  },
});
