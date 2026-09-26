import type {
  ActivitySnapshotViewModel,
  ActivityState,
  ConversationViewModel,
  MessageAcceptanceViewModel,
  MessageStatus,
  MessageViewModel,
} from '@allies/cloud-client';
import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query';
import * as Crypto from 'expo-crypto';
import { useIsFocused, useLocalSearchParams, useRouter } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Animated, { LinearTransition, useReducedMotion } from 'react-native-reanimated';

import { PrimaryButton } from '@/components/ui/primary-button';
import { getAllyAppearance } from '@/features/allies/ally-appearance';
import { allyKeys, useAlly } from '@/features/allies/queries';
import {
  activityStateForMessage,
  EMPTY_ACTIVITY_PROJECTION,
  findLatestConversationUserMessage,
  hasPermanentMobileActivityGap,
  hasMobileActivityReplayGap,
  insertAcceptedMessage,
  isMobileActivityPollErrorRecoverable,
  isMessageExecutionActive,
  getMobileActivityPollingInterval,
  loadMobileActivityReplay,
  mergeConversationAssistantReplies,
  mergeConversationMessages,
  MOBILE_REPLY_LIMIT_NOTICE,
  projectMobileActivityForMessage,
  refreshMobileConversationHistory,
  replaceNewestConversationPage,
  selectMobileConversationReplies,
  shouldContinueMobileActivityPolling,
  shouldRetryMobileActivityReplay,
  isMobileActivityTerminalForMessage,
  queuedConversationMessages,
} from '@/features/conversation/conversation-state';
import { ConversationLayout, ConversationMessage, ConversationThinkingRow, type ConversationAlly } from '@/features/conversation/conversation-layout';
import { useComposingRuntimeIntent, type RuntimeIntentRequester } from '@/features/conversation/runtime-intent';
import { OnboardingAllyPreview } from '@/features/onboarding/onboarding-ally-preview';
import { useTheme } from '@/hooks/use-theme';
import { pendingCommandStore, type PendingMessageCommand } from '@/lib/pending-command-store';
import { useNativeAppState } from '@/lib/providers/native-lifecycle';
import { useNativeSession } from '@/lib/session/session-context';

const CONVERSATION_PAGE_LIMIT = 50;
const ACTIVITY_LIMIT = 200;

type MessageOperation = {
  controller: AbortController;
  generation: number;
  identity: string;
};

function isTransient(error: unknown): boolean {
  return typeof error === 'object'
    && error !== null
    && 'kind' in error
    && ['network', 'timeout', 'server', 'throttled', 'contract'].includes(String(error.kind));
}

function allyIdFromParam(value: string | string[] | undefined): string | null {
  const allyId = Array.isArray(value) ? value[0] : value;
  return allyId?.trim() || null;
}

export default function AllyConversationRoute() {
  const { allyId: rawAllyId } = useLocalSearchParams<{ allyId?: string }>();
  const allyId = allyIdFromParam(rawAllyId);
  const router = useRouter();

  if (!allyId) return <ConversationState message="That Ally link is not valid." onBack={() => router.replace('/allies' as never)} />;
  return <AllyConversationScreen allyId={allyId} onBack={() => router.replace('/allies' as never)} />;
}

function AllyConversationScreen({ allyId, onBack }: { allyId: string; onBack: () => void }) {
  const theme = useTheme();
  const router = useRouter();
  const session = useNativeSession();
  const focused = useIsFocused();
  const appState = useNativeAppState();
  const live = focused && appState === 'active';
  const queryClient = useQueryClient();
  const reducedMotion = Boolean(useReducedMotion());
  const allyQuery = useAlly(allyId);
  const workspaceId = session.account?.workspace.id ?? '';
  const sessionIdentity = `${session.status}:${session.account?.userId ?? ''}:${workspaceId}`;
  const canRequest = session.status === 'signed-in'
    && Boolean(workspaceId && session.accountClient && session.adapter);
  const conversationKey = useMemo(() => allyKeys.conversation(workspaceId, allyId), [allyId, workspaceId]);
  const [draft, setDraft] = useState('');
  const [composerHeight, setComposerHeight] = useState(48);
  const [sending, setSending] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingMessage, setPendingMessage] = useState<PendingMessageCommand | null>(null);
  const [pendingLoaded, setPendingLoaded] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [projection, setProjection] = useState(EMPTY_ACTIVITY_PROJECTION);
  const [replayStartCursor, setReplayStartCursor] = useState<string | null>(null);
  const pollingStartedAt = useRef<number | null>(null);
  const pollingConversationId = useRef<string | null>(null);
  const replayProjectionRef = useRef<{
    latestMessageId: string | undefined;
    pages: readonly ActivitySnapshotViewModel[];
  } | null>(null);
  const replayCatchupTargetRef = useRef<number | null>(null);
  const wasLiveRef = useRef(live);
  const foregroundReconciliationRef = useRef<Promise<void> | null>(null);
  const reconciliationControllerRef = useRef<AbortController | null>(null);
  const conversationReadGenerationRef = useRef(0);
  const messageOperationGenerationRef = useRef(0);
  const messageControllerRef = useRef<AbortController | null>(null);
  const sessionIdentityRef = useRef(sessionIdentity);
  const previousSessionIdentityRef = useRef(sessionIdentity);
  const scrollRef = useRef<ScrollView>(null);
  const followLatestRef = useRef(true);

  useEffect(() => {
    sessionIdentityRef.current = sessionIdentity;
  }, [sessionIdentity]);

  const startMessageOperation = useCallback((identity: string): MessageOperation => {
    messageControllerRef.current?.abort();
    const controller = new AbortController();
    messageControllerRef.current = controller;
    return {
      controller,
      generation: ++messageOperationGenerationRef.current,
      identity,
    };
  }, []);

  const isCurrentMessageOperation = useCallback((operation: MessageOperation): boolean => (
    !operation.controller.signal.aborted
    && messageControllerRef.current === operation.controller
    && messageOperationGenerationRef.current === operation.generation
    && sessionIdentityRef.current === operation.identity
  ), []);

  const finishMessageOperation = useCallback((operation: MessageOperation) => {
    if (messageControllerRef.current === operation.controller) messageControllerRef.current = null;
  }, []);

  const requestRuntimeIntent = useCallback<RuntimeIntentRequester>((targetAllyId, occurredAt, idempotencyKey, signal) => {
    if (!session.accountClient || !session.adapter) return Promise.reject(new Error('Cloud account is unavailable'));
    return session.adapter.withRefresh(() => session.accountClient!.requestRuntimeIntent(
      targetAllyId,
      occurredAt,
      idempotencyKey,
      signal,
    ));
  }, [session.accountClient, session.adapter]);
  const { observeEdit } = useComposingRuntimeIntent(allyId, requestRuntimeIntent);

  const conversationQuery = useInfiniteQuery({
    queryKey: conversationKey,
    enabled: canRequest,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => session.adapter!.withRefresh(() => session.accountClient!.getAllyConversation(
      workspaceId,
      allyId,
      { limit: CONVERSATION_PAGE_LIMIT, ...(pageParam ? { cursor: pageParam } : {}), signal },
    )),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    refetchOnWindowFocus: false,
  });
  const conversationId = conversationQuery.data?.pages[0]?.id ?? null;
  const newestConversationMessages = [
    ...(conversationQuery.data?.pages[0]?.messages ?? []),
    ...(conversationQuery.data?.pages[0]?.queue ?? []),
  ];
  const latestConversationUserMessage = findLatestConversationUserMessage(
    newestConversationMessages,
  );
  const conversationExecutionActive = newestConversationMessages.some((message) =>
    message.sender === 'user' && isMessageExecutionActive(message.status));
  const activityQuery = useQuery({
    queryKey: ['allies', 'activity', workspaceId, conversationId],
    enabled: Boolean(canRequest && conversationId),
    queryFn: ({ signal }) => session.adapter!.withRefresh(() => session.accountClient!.getActivities(
        workspaceId,
        conversationId!,
        { limit: ACTIVITY_LIMIT, signal },
      )),
    refetchOnWindowFocus: false,
    retry: false,
    refetchInterval: (query) => {
      const snapshot = query.state.data;
      const activityMessageId = snapshot?.activeMessageId ?? latestConversationUserMessage?.id;
      const terminalForLatestTurn = isMobileActivityTerminalForMessage(snapshot, activityMessageId);
      const pendingExecutionBeyondSnapshot = terminalForLatestTurn && newestConversationMessages.some((message) =>
        message.id !== activityMessageId && message.sender === 'user' && isMessageExecutionActive(message.status));
      const snapshotState = snapshot?.state;
      const state = terminalForLatestTurn
        ? pendingExecutionBeyondSnapshot ? 'queued' : snapshotState
        : conversationExecutionActive ? 'running' : snapshotState;
      if (!isMobileActivityPollErrorRecoverable(query.state.error) || !shouldContinueMobileActivityPolling({
        focused: live,
        state,
        knownExecutionActive: conversationExecutionActive && (!terminalForLatestTurn || pendingExecutionBeyondSnapshot),
      })) {
        pollingStartedAt.current = null;
        return false;
      }
      const observedAt = Math.max(query.state.dataUpdatedAt, query.state.errorUpdatedAt);
      pollingStartedAt.current ??= observedAt;
      return getMobileActivityPollingInterval({
        focused: live,
        state: state!,
        startedAt: pollingStartedAt.current,
        now: observedAt,
      });
    },
    refetchIntervalInBackground: false,
  });
  const activityReplayQuery = useQuery({
    queryKey: ['allies', 'activity-replay', workspaceId, conversationId, replayStartCursor],
    enabled: Boolean(canRequest && conversationId),
    queryFn: ({ signal }) => loadMobileActivityReplay(
      (options) => session.adapter!.withRefresh(() => session.accountClient!.getActivities(
        workspaceId,
        conversationId!,
        options,
      )),
      signal,
      replayStartCursor ?? undefined,
    ),
    retry: (failureCount, error) => !replayStartCursor && shouldRetryMobileActivityReplay(failureCount, error),
    retryDelay: 250,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
  });
  const { data: activityData, isError: activityError, refetch: refetchActivity } = activityQuery;
  const {
    data: activityReplayPages,
    error: activityReplayErrorValue,
    isError: activityReplayIsError,
    isFetching: activityReplayIsFetching,
    refetch: refetchActivityReplay,
  } = activityReplayQuery;
  const activityMessageId = activityData?.activeMessageId
    ?? activityReplayPages?.at(-1)?.activeMessageId
    ?? latestConversationUserMessage?.id;
  const conversationPages = conversationQuery.data?.pages;
  const refetchConversation = conversationQuery.refetch;

  const refreshNewestConversation = useCallback(async (signal?: AbortSignal) => {
    if (!conversationId || !canRequest) return;
    const requestIdentity = sessionIdentity;
    const generation = ++conversationReadGenerationRef.current;
    const newest = await session.adapter!.withRefresh(() => session.accountClient!.getConversation(
      workspaceId,
      conversationId,
      { limit: CONVERSATION_PAGE_LIMIT, signal },
    ));
    if (signal?.aborted || sessionIdentityRef.current !== requestIdentity
      || generation !== conversationReadGenerationRef.current) return;
    queryClient.setQueryData<InfiniteData<ConversationViewModel, string | null>>(
      conversationKey,
      (current) => current ? { ...current, pages: replaceNewestConversationPage(current.pages, newest) } : current,
    );
  }, [canRequest, conversationId, conversationKey, queryClient, session.accountClient, session.adapter, sessionIdentity, workspaceId]);

  useEffect(() => {
    if (!canRequest || !conversationId || !live) return;
    const controller = new AbortController();
    const delay = conversationQuery.data?.pages[0]?.queue?.length ? 3_000 : 10_000;
    const timer = setInterval(() => {
      void refreshNewestConversation(controller.signal).catch(() => undefined);
    }, delay);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [canRequest, conversationId, conversationQuery.data?.pages, live, refreshNewestConversation]);

  const reconcileForeground = useCallback(async () => {
    if (!conversationId || !canRequest || !live) return;
    const controller = new AbortController();
    reconciliationControllerRef.current = controller;
    try {
      await Promise.allSettled([
        refreshMobileConversationHistory(
          () => refreshNewestConversation(controller.signal),
          () => refetchConversation({ throwOnError: true }),
          controller.signal,
        ),
        refetchActivity(),
        refetchActivityReplay(),
      ]);
    } finally {
      if (reconciliationControllerRef.current === controller) reconciliationControllerRef.current = null;
      controller.abort();
    }
  }, [canRequest, conversationId, live, refetchActivity, refetchActivityReplay, refetchConversation, refreshNewestConversation]);

  useEffect(() => {
    if (pollingConversationId.current === conversationId) return;
    pollingConversationId.current = conversationId;
    pollingStartedAt.current = null;
    replayProjectionRef.current = null;
    replayCatchupTargetRef.current = null;
    setReplayStartCursor(null);
    setProjection(EMPTY_ACTIVITY_PROJECTION);
  }, [conversationId]);

  useEffect(() => {
    const latestMessageId = activityMessageId;
    const previousReplay = replayProjectionRef.current;
    if (!conversationId || !activityReplayPages || (
      previousReplay?.pages === activityReplayPages
      && previousReplay.latestMessageId === latestMessageId
    )) return;
    replayProjectionRef.current = { latestMessageId, pages: activityReplayPages };
    setProjection((current) => activityReplayPages.reduce(
      (next, snapshot) => projectMobileActivityForMessage(next, snapshot, latestMessageId),
      current,
    ));
  }, [activityMessageId, activityReplayPages, conversationId]);

  useEffect(() => {
    if (!conversationId || !activityData) return;
    const terminalForLatestTurn = isMobileActivityTerminalForMessage(activityData, activityMessageId);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Merge each live snapshot into the durable local projection.
    setProjection((current) => projectMobileActivityForMessage(current, activityData, activityMessageId));
    if (!terminalForLatestTurn) return;
    const controller = new AbortController();
    void refreshMobileConversationHistory(
      () => refreshNewestConversation(controller.signal),
      () => refetchConversation({ throwOnError: true }),
      controller.signal,
    ).catch(() => undefined);
    return () => controller.abort();
  }, [activityData, activityMessageId, conversationId, refetchConversation, refreshNewestConversation]);

  useEffect(() => {
    if (!conversationId || !activityData || activityReplayIsFetching || activityData.oldestSequence === null || activityData.oldestSequence === undefined) return;
    const currentContiguousSequence = projection.lastContiguousSequence;
    if (activityData.oldestSequence <= currentContiguousSequence + 1) return;
    const target = activityData.latestSequence ?? activityData.oldestSequence;
    if (replayCatchupTargetRef.current === target) return;
    const catchupCursor = activityReplayPages?.at(-1)?.resumeCursor;
    if (!catchupCursor || replayStartCursor === catchupCursor) return;
    replayCatchupTargetRef.current = target;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Advance to the signed cursor required to recover a sliding-tail gap.
    setReplayStartCursor(catchupCursor);
  }, [activityData, activityReplayIsFetching, activityReplayPages, conversationId, projection.lastContiguousSequence, replayStartCursor]);

  useEffect(() => {
    if (previousSessionIdentityRef.current === sessionIdentity) return;
    const previousWasSignedIn = previousSessionIdentityRef.current.startsWith('signed-in:');
    previousSessionIdentityRef.current = sessionIdentity;
    messageOperationGenerationRef.current += 1;
    messageControllerRef.current?.abort();
    messageControllerRef.current = null;
    setSending(false);
    setDeletingId(null);
    setSendError(null);
    setPendingMessage(null);
    setPendingLoaded(false);
    setDraft('');
    reconciliationControllerRef.current?.abort();
    reconciliationControllerRef.current = null;
    foregroundReconciliationRef.current = null;
    wasLiveRef.current = live;
    if (!previousWasSignedIn) return;
    void Promise.all([
      queryClient.cancelQueries({ queryKey: conversationKey }),
      queryClient.cancelQueries({ queryKey: ['allies', 'activity', workspaceId, conversationId] }),
      queryClient.cancelQueries({ queryKey: ['allies', 'activity-replay', workspaceId, conversationId] }),
    ]);
  }, [conversationId, conversationKey, live, queryClient, sessionIdentity, workspaceId]);

  useEffect(() => {
    const wasLive = wasLiveRef.current;
    wasLiveRef.current = live;
    if (!live) {
      reconciliationControllerRef.current?.abort();
      reconciliationControllerRef.current = null;
      foregroundReconciliationRef.current = null;
      return;
    }
    if (wasLive || !conversationId || foregroundReconciliationRef.current) return;
    const reconciliation = reconcileForeground();
    foregroundReconciliationRef.current = reconciliation;
    void reconciliation.then(
      () => {
        if (foregroundReconciliationRef.current === reconciliation) foregroundReconciliationRef.current = null;
      },
      () => {
        if (foregroundReconciliationRef.current === reconciliation) foregroundReconciliationRef.current = null;
      },
    );
  }, [conversationId, live, reconcileForeground]);

  useEffect(() => () => {
    messageOperationGenerationRef.current += 1;
    messageControllerRef.current?.abort();
    messageControllerRef.current = null;
    reconciliationControllerRef.current?.abort();
    reconciliationControllerRef.current = null;
    foregroundReconciliationRef.current = null;
  }, []);

  useEffect(() => {
    if (!conversationId || session.status !== 'signed-in' || !session.account) return;
    const readIdentity = sessionIdentity;
    let mounted = true;
    void pendingCommandStore.readMessage(conversationId, session.account.userId, session.account.workspace.id).then((command) => {
      if (!mounted || sessionIdentityRef.current !== readIdentity) return;
      setPendingMessage(command);
      if (command) setDraft(command.content);
      setPendingLoaded(true);
    }).catch(() => {
      if (mounted && sessionIdentityRef.current === readIdentity) {
        setSendError('We could not read your saved message. Reopen this conversation to retry.');
      }
    });
    return () => {
      mounted = false;
    };
  }, [conversationId, session.account, session.status, sessionIdentity]);

  const messages = (() => {
    try {
      return mergeConversationMessages(conversationPages ?? []);
    } catch {
      return null;
    }
  })();
  const queuedMessages = messages ? queuedConversationMessages(conversationPages ?? [], projection) : [];
  const queuedIds = new Set(queuedMessages.map((message) => message.id));
  const timelineMessages = messages?.filter((message) => !queuedIds.has(message.id)) ?? [];
  const ally = allyQuery.data;
  const appearance = ally ? getAllyAppearance(ally.appearance.key) : null;
  const latestReplaySnapshot = activityReplayPages?.at(-1);
  const terminalActivityForLatestTurn = isMobileActivityTerminalForMessage(activityData, activityMessageId)
    || isMobileActivityTerminalForMessage(latestReplaySnapshot, activityMessageId);
  const pendingExecutionBeyondActivity = terminalActivityForLatestTurn && newestConversationMessages.some((message) =>
    message.id !== activityMessageId && message.sender === 'user' && isMessageExecutionActive(message.status));
  const latestActivityState = activityData?.state ?? latestReplaySnapshot?.state;
  const activityIsActive = latestActivityState === 'queued' || latestActivityState === 'running';
  const active = activityIsActive
    || (conversationExecutionActive && (!terminalActivityForLatestTurn || pendingExecutionBeyondActivity));
  const canSend = pendingLoaded
    && Boolean((pendingMessage?.content ?? draft).trim())
    && !sending
    && !deletingId
    && Boolean(ally)
    && !conversationQuery.isError;
  const acceptMessage = useCallback(async (
    acceptance: MessageAcceptanceViewModel,
    operation: MessageOperation,
    idempotencyKey: string,
  ): Promise<boolean> => {
    if (!isCurrentMessageOperation(operation)) return false;
    if (!conversationId || acceptance.message.sender !== 'user') return false;
    if ('conversationId' in acceptance && acceptance.conversationId !== conversationId) {
      throw new Error('Accepted message belongs to another conversation');
    }
    if (!isCurrentMessageOperation(operation)) return false;
    conversationReadGenerationRef.current += 1;
    await queryClient.cancelQueries({ queryKey: conversationKey });
    if (!isCurrentMessageOperation(operation)) return false;
    let cacheConflict = false;
    try {
      queryClient.setQueryData<InfiniteData<ConversationViewModel, string | null>>(
        conversationKey,
        (current) => current ? { ...current, pages: insertAcceptedMessage(current.pages, acceptance.message) } : current,
      );
    } catch {
      cacheConflict = true;
    }
    if (!isCurrentMessageOperation(operation)) return false;
    await pendingCommandStore.deleteMessage(conversationId, idempotencyKey);
    if (!isCurrentMessageOperation(operation)) return false;
    setPendingMessage(null);
    setDraft('');
    const nextState = activityStateForMessage(acceptance.message.status);
    setProjection((current) => ({ ...current, state: nextState }));
    const executionActive = isMessageExecutionActive(acceptance.message.status);
    try {
      await Promise.all([
        refetchActivity(),
        ...(executionActive ? [] : [refreshNewestConversation(operation.controller.signal)]),
      ]);
    } catch {
      if (!isCurrentMessageOperation(operation)) return false;
      setSendError('Your message was sent. Refresh when your connection is stable.');
      return true;
    }
    if (!isCurrentMessageOperation(operation)) return false;
    if (cacheConflict) setSendError('Your message was sent. Refresh to reconcile the conversation.');
    return true;
  }, [conversationId, conversationKey, isCurrentMessageOperation, queryClient, refetchActivity, refreshNewestConversation]);

  const send = async () => {
    if (!canSend || !conversationId || !session.account || !session.accountClient || !session.adapter) return;
    const operation = startMessageOperation(sessionIdentity);
    const content = (pendingMessage?.content ?? draft).trim();
    const command = pendingMessage ?? {
      kind: 'message' as const,
      conversationId,
      content,
      idempotencyKey: Crypto.randomUUID(),
      createdAt: new Date().toISOString(),
      boundUserId: session.account.userId,
      boundWorkspaceId: session.account.workspace.id,
    };

    setSending(true);
    setSendError(null);
    try {
      if (!pendingMessage) {
        await pendingCommandStore.saveMessage(command);
        if (!isCurrentMessageOperation(operation)) return;
        setPendingMessage(command);
      }
      if (!isCurrentMessageOperation(operation)) return;
      const acceptance = await session.adapter.withRefresh(() => command.retryMessageId
        ? session.accountClient!.retryMessage(
          session.account!.workspace.id,
          command.conversationId,
          command.retryMessageId,
          command.idempotencyKey,
          operation.controller.signal,
        )
        : session.accountClient!.sendMessage(
          session.account!.workspace.id,
          command.conversationId,
          command.content,
          command.idempotencyKey,
          operation.controller.signal,
        ));
      if (!isCurrentMessageOperation(operation)) return;
      const accepted = await acceptMessage(acceptance, operation, command.idempotencyKey);
      if (!accepted || !isCurrentMessageOperation(operation)) return;
    } catch (error) {
      if (!isCurrentMessageOperation(operation)) return;
      setSendError(isTransient(error)
        ? 'We could not confirm your message. Retry the saved message.'
        : 'We could not send your message. Try again.');
      if (!isTransient(error)) {
        try {
          await pendingCommandStore.deleteMessage(conversationId, command.idempotencyKey);
          if (!isCurrentMessageOperation(operation)) return;
          setPendingMessage(null);
        } catch {
          if (!isCurrentMessageOperation(operation)) return;
          setSendError('Your message may have been accepted. Retry it to confirm.');
        }
      }
    } finally {
      const operationIsCurrent = isCurrentMessageOperation(operation);
      finishMessageOperation(operation);
      if (operationIsCurrent) setSending(false);
    }
  };

  const retry = async (message: MessageViewModel) => {
    if (!conversationId || sending || deletingId || !session.account || !session.accountClient || !session.adapter) return;
    const operation = startMessageOperation(sessionIdentity);
    const command = pendingMessage ?? {
      kind: 'message' as const,
      conversationId,
      content: message.content,
      idempotencyKey: Crypto.randomUUID(),
      retryMessageId: message.id,
      createdAt: new Date().toISOString(),
      boundUserId: session.account.userId,
      boundWorkspaceId: session.account.workspace.id,
    };
    setSending(true);
    setSendError(null);
    try {
      if (!pendingMessage) {
        await pendingCommandStore.saveMessage(command);
        if (!isCurrentMessageOperation(operation)) return;
      }
      if (!isCurrentMessageOperation(operation)) return;
      setPendingMessage(command);
      setDraft(command.content);
      if (!isCurrentMessageOperation(operation)) return;
      const acceptance = await session.adapter.withRefresh(() => session.accountClient!.retryMessage(
        session.account!.workspace.id,
        conversationId,
        message.id,
        command.idempotencyKey,
        operation.controller.signal,
      ));
      if (!isCurrentMessageOperation(operation)) return;
      const accepted = await acceptMessage(acceptance, operation, command.idempotencyKey);
      if (!accepted || !isCurrentMessageOperation(operation)) return;
    } catch (error) {
      if (!isCurrentMessageOperation(operation)) return;
      setSendError(isTransient(error) ? 'We could not confirm the retry. Try again.' : 'We could not retry that message.');
      if (!isTransient(error)) {
        try {
          await pendingCommandStore.deleteMessage(conversationId, command.idempotencyKey);
          if (!isCurrentMessageOperation(operation)) return;
          setPendingMessage(null);
        } catch {
          if (!isCurrentMessageOperation(operation)) return;
          setSendError('Your retry may have been accepted. Retry it to confirm.');
        }
      }
    } finally {
      const operationIsCurrent = isCurrentMessageOperation(operation);
      finishMessageOperation(operation);
      if (operationIsCurrent) setSending(false);
    }
  };

  const removeQueued = async (message: MessageViewModel) => {
    if (message.queueState !== 'unclaimed' || message.status !== 'queued' || message.deletedAt
      || sending || deletingId || !conversationId || !session.accountClient || !session.adapter) return;
    const operation = startMessageOperation(sessionIdentity);
    setDeletingId(message.id);
    setSendError(null);
    try {
      const deleted = await session.adapter.withRefresh(() => session.accountClient!.deleteQueuedMessage(
        workspaceId,
        conversationId,
        message.id,
        operation.controller.signal,
      ));
      if (!isCurrentMessageOperation(operation)) return;
      conversationReadGenerationRef.current += 1;
      await queryClient.cancelQueries({ queryKey: conversationKey });
      if (!isCurrentMessageOperation(operation)) return;
      queryClient.setQueryData<InfiniteData<ConversationViewModel, string | null>>(
        conversationKey,
        (current) => current ? { ...current, pages: insertAcceptedMessage(current.pages, deleted) } : current,
      );
      await refreshNewestConversation(operation.controller.signal);
    } catch {
      if (!isCurrentMessageOperation(operation)) return;
      setSendError('We could not confirm removal. The message may have started; check again or try once more.');
      void refreshNewestConversation().catch(() => undefined);
    } finally {
      const operationIsCurrent = isCurrentMessageOperation(operation);
      finishMessageOperation(operation);
      if (operationIsCurrent) setDeletingId(null);
    }
  };

  if (session.status === 'checking' || session.status === 'refreshing' || allyQuery.isPending || conversationQuery.isPending) {
    return <ConversationState busy message="Loading your Ally…" />;
  }
  if (session.status === 'offline-with-session' || session.status === 'unavailable') {
    return <ConversationState message="Reconnect to load this conversation." onBack={onBack} onRetry={() => void session.restore()} />;
  }
  if (allyQuery.isError || conversationQuery.isError || !ally || !appearance || !conversationQuery.data || !messages) {
    return <ConversationState message="We could not load this conversation." onBack={onBack} onRetry={() => void Promise.all([allyQuery.refetch(), conversationQuery.refetch()])} />;
  }

  const durableReplies = mergeConversationAssistantReplies(
    conversationPages ?? [],
    [
      ...(activityReplayPages?.map((page) => page.assistantReply ?? null) ?? []),
      ...(activityData?.assistantReply ? [activityData.assistantReply] : []),
    ],
  );
  const replySelection = selectMobileConversationReplies(messages, projection.turns, durableReplies);
  const activityReplayGap = hasMobileActivityReplayGap(
    activityReplayPages ?? [],
    activityReplayErrorValue,
    replayStartCursor === null,
  );
  const activityReplayError = activityReplayIsError && !activityReplayGap;
  const retryActivityReplay = () => {
    if (replayStartCursor !== null) {
      replayCatchupTargetRef.current = null;
      setReplayStartCursor(null);
      return;
    }
    void refetchActivityReplay();
  };
  const latestUserMessage = messages.filter((message) => message.sender === 'user').at(-1);
  const latestInlineReply = latestUserMessage
    ? replySelection.inlineBySourceMessageId.get(latestUserMessage.id)
    : undefined;
  const terminalStatusShownInline = latestInlineReply?.kind === 'durable'
    && latestInlineReply.reply.status === projection.state;
  const activityLabel = active && latestActivityState !== 'running' ? 'Waking' : 'Thinking';
  const conversationAlly: ConversationAlly = {
    color: appearance.color,
    name: ally.name,
    shape: appearance.shape,
  };

  return (
    <ConversationLayout
      active={active}
      ally={conversationAlly}
      canSend={canSend}
      composerHeight={composerHeight}
      draft={draft}
      editable={!pendingMessage && !sending && !deletingId}
      onBack={onBack}
      onOpenSettings={() => router.push(`/allies/${allyId}/profile` as never)}
      onChangeDraft={(value) => {
        setDraft(value);
        observeEdit(value);
      }}
      onComposerHeightChange={setComposerHeight}
      onContentSizeChange={() => followLatestRef.current && scrollRef.current?.scrollToEnd({ animated: !reducedMotion })}
      onScroll={({ nativeEvent }) => {
        followLatestRef.current = nativeEvent.contentSize.height - (nativeEvent.contentOffset.y + nativeEvent.layoutMeasurement.height) < 80;
      }}
      onSend={() => void send()}
      placeholder={pendingMessage ? 'Retry the saved message' : `Ask ${ally.name}`}
      scrollRef={scrollRef}
      sendLabel={pendingMessage ? 'Retry message' : 'Send message'}
    >
      {conversationQuery.hasNextPage ? (
        <Pressable accessibilityRole="button" disabled={conversationQuery.isFetchingNextPage} onPress={() => void conversationQuery.fetchNextPage()} style={styles.olderButton}>
          <Text style={[styles.olderButtonText, { color: theme.supportingText }]}>{conversationQuery.isFetchingNextPage ? 'Loading…' : 'Earlier messages'}</Text>
        </Pressable>
      ) : null}
      {timelineMessages.length === 0 && queuedMessages.length === 0 ? <Text style={[styles.emptyText, { color: theme.supportingText }]}>Your conversation will appear here.</Text> : null}
      {timelineMessages.map((message) => {
        if (replySelection.suppressedAssistantMessageIds.has(message.id)) return null;
        const inlineReply = message.sender === 'user'
          ? replySelection.inlineBySourceMessageId.get(message.id)
          : undefined;
        return (
          <View key={message.id}>
            <ConversationMessage
              ally={conversationAlly}
              animateAssistant={false}
              message={{
                content: message.content,
                id: message.id,
                sender: message.sender,
                status: message.sender === 'assistant' && message.status !== 'completed' ? message.status : null,
                statusLabel: inlineReply?.kind === 'activity' || message.status !== 'completed'
                  ? messageStatusLabel(inlineReply?.kind === 'activity' ? inlineReply.turn.state : message.status)
                  : null,
              }}
              reducedMotion={reducedMotion}
            />
            {message.sender === 'user' && message.retryable && !pendingMessage ? (
              <Pressable accessibilityRole="button" disabled={sending || Boolean(deletingId)} onPress={() => void retry(message)} style={styles.retryButton}>
                <Text style={[styles.retryButtonText, { color: appearance.color }]}>Retry</Text>
              </Pressable>
            ) : null}
            {inlineReply?.kind === 'durable' ? <AssistantReply reply={inlineReply.reply} streaming={active} /> : null}
            {inlineReply?.kind === 'activity' ? <AssistantTurn turn={inlineReply.turn} streaming={active} /> : null}
          </View>
        );
      })}
      {replySelection.remainingReplies.map((reply) => <AssistantReply key={`reply-${reply.id}`} reply={reply} streaming={active} />)}
      {replySelection.remainingTurns.map((turn) => <AssistantTurn key={turn.messageId} turn={turn} streaming={active} />)}
      {queuedMessages.length ? (
        <View accessibilityLabel="Queued messages" style={[styles.queue, { backgroundColor: theme.controlSurface }]}>
          <View style={styles.queueHeader}>
            <Text style={[styles.queueTitle, { color: theme.supportingText }]}>Queued</Text>
            <Pressable accessibilityRole="button" onPress={() => void refreshNewestConversation()} style={styles.queueRefresh}>
              <Text style={[styles.queueActionText, { color: theme.supportingText }]}>Check again</Text>
            </Pressable>
          </View>
          {queuedMessages.slice(0, 8).map((message) => (
            <View key={`queue-${message.id}`} style={styles.queueRow}>
              <Text numberOfLines={3} style={[styles.queueText, { color: theme.primaryText }]}>{message.content}</Text>
              {message.queueState === 'unclaimed' ? (
                <Pressable
                  accessibilityLabel={`Remove queued message: ${message.content}`}
                  accessibilityRole="button"
                  disabled={sending || Boolean(deletingId)}
                  onPress={() => void removeQueued(message)}
                  style={styles.queueRemove}
                >
                  <Text style={[styles.queueActionText, { color: appearance.color }]}>{deletingId === message.id ? 'Removing…' : 'Remove'}</Text>
                </Pressable>
              ) : <Text style={[styles.queueActionText, { color: theme.supportingText }]}>Next</Text>}
            </View>
          ))}
          {queuedMessages.length > 8 ? <Text style={[styles.queueMore, { color: theme.supportingText }]}>+{queuedMessages.length - 8} more queued</Text> : null}
        </View>
      ) : null}
      <ConversationThinkingRow ally={conversationAlly} label={activityLabel} reducedMotion={reducedMotion} thinking={active} />
      {hasPermanentMobileActivityGap(projection) ? <Text style={styles.reconciliationText}>Some response text arrived out of order. Check again to reconcile it.</Text> : null}
      {projection.state === 'awaiting_action' && !active ? <Text style={[styles.statusText, { color: theme.supportingText }]}>This Ally needs an action before continuing.</Text> : null}
      {projection.state === 'failed' && !active && !terminalStatusShownInline ? <Text style={styles.errorText}>This response failed.</Text> : null}
      {projection.state === 'stopped' && !active && !terminalStatusShownInline ? <Text style={[styles.statusText, { color: theme.supportingText }]}>This response was stopped.</Text> : null}
      {activityError ? (
        <Pressable accessibilityRole="button" onPress={() => void refetchActivity()} style={styles.activityRetry}>
          <Text style={styles.retryButtonText}>Could not check the latest response. Try again.</Text>
        </Pressable>
      ) : null}
      {activityReplayGap ? (
        <>
          <Text style={styles.reconciliationText}>Some earlier response history is no longer available.</Text>
          <Pressable accessibilityRole="button" onPress={retryActivityReplay} style={styles.activityRetry}>
            <Text style={styles.retryButtonText}>Try loading history again.</Text>
          </Pressable>
        </>
      ) : activityReplayError ? (
        <Pressable accessibilityRole="button" onPress={retryActivityReplay} style={styles.activityRetry}>
          <Text style={styles.retryButtonText}>Could not reload response history. Try again.</Text>
        </Pressable>
      ) : null}
      {sendError ? <Text accessibilityRole="alert" style={styles.errorText}>{sendError}</Text> : null}
    </ConversationLayout>
  );
}

function AssistantReply({ reply, streaming }: {
  reply: { content: string; status: MessageStatus; isTruncated?: boolean };
  streaming: boolean;
}) {
  const theme = useTheme();
  const statusText = reply.status === 'failed'
    ? 'This response failed.'
    : reply.status === 'stopped'
      ? 'This response was stopped.'
      : null;
  const limitNotice = reply.isTruncated === true ? MOBILE_REPLY_LIMIT_NOTICE : null;
  if (!reply.content && !statusText && !limitNotice) return null;
  return (
    <Animated.View layout={streaming ? LinearTransition.duration(140) : undefined} style={styles.allyMessage}>
      {reply.content ? <Text style={[styles.messageText, { color: theme.primaryText }]}>{reply.content}</Text> : null}
      {statusText ? <Text style={reply.status === 'failed' ? styles.errorText : [styles.statusText, { color: theme.supportingText }]}>{statusText}</Text> : null}
      {limitNotice ? <Text style={[styles.statusText, { color: theme.supportingText }]}>{limitNotice}</Text> : null}
    </Animated.View>
  );
}

function AssistantTurn({ turn, streaming }: { turn: { assistantText: string; messageId: string; state: ActivityState; turnOrdinal: number }; streaming: boolean }) {
  const theme = useTheme();
  if (turn.state === 'failed' || turn.state === 'stopped') {
    return <Text style={turn.state === 'failed' ? styles.errorText : [styles.statusText, { color: theme.supportingText }]}>{turn.state === 'failed' ? 'This response failed.' : 'This response was stopped.'}</Text>;
  }
  if (turn.state === 'reconciliation_needed') return <Text style={styles.reconciliationText}>This response needs review because some activity arrived out of order.</Text>;
  if (!turn.assistantText) return null;
  return (
    <Animated.View layout={streaming ? LinearTransition.duration(140) : undefined} style={styles.allyMessage}>
      <Text style={[styles.messageText, { color: theme.primaryText }]}>{turn.assistantText}</Text>
    </Animated.View>
  );
}

function messageStatusLabel(status: MessageStatus | ActivityState): string | null {
  return {
    queued: 'Queued',
    in_progress: 'Working',
    running: 'Working',
    awaiting_action: 'Needs action',
    completed: null,
    failed: 'Failed',
    stopped: 'Stopped',
    reconciliation_needed: 'Needs review',
  }[status];
}

function ConversationState({ busy = false, message, onBack, onRetry }: { busy?: boolean; message: string; onBack?: () => void; onRetry?: () => void }) {
  const theme = useTheme();
  return (
    <SafeAreaView style={[styles.state, { backgroundColor: theme.appBackground }]}>
      {busy ? <OnboardingAllyPreview accessibilityLabel="Ally loading" color="#FF5800" identity="boxy" size={64} state="thinking" /> : null}
      <Text style={[styles.stateText, { color: theme.primaryText }]}>{message}</Text>
      {onRetry ? <PrimaryButton bottomMargin={12} label="Try again" onPress={onRetry} /> : null}
      {onBack ? <PrimaryButton accentColor={theme.neutralButtonSurface} bottomMargin={0} label="Back to Allies" labelColor={theme.neutralButtonText} onPress={onBack} /> : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  allyMessage: { marginTop: 22 },
  backIcon: { height: 14, width: 8 },
  composer: { alignItems: 'center', flexDirection: 'row', overflow: 'hidden', paddingLeft: 14, paddingRight: 6, width: '100%' },
  composerArea: { paddingHorizontal: 14 },
  content: { flex: 1 },
  emptyText: { fontFamily: 'OpenRundeMedium', fontSize: 15, marginTop: 28, textAlign: 'center' },
  errorText: { color: '#B3261E', fontFamily: 'OpenRundeMedium', fontSize: 14, lineHeight: 20, marginTop: 16, textAlign: 'center' },
  activityRetry: { alignSelf: 'center', marginTop: 16, paddingHorizontal: 12, paddingVertical: 4 },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between', paddingBottom: 13, paddingHorizontal: 14, paddingTop: 10 },
  headerButton: { alignItems: 'center', borderRadius: 999, height: 40, justifyContent: 'center', width: 40 },
  headerIdentity: { alignItems: 'center', flex: 1, flexDirection: 'row', justifyContent: 'center', marginHorizontal: 12 },
  headerName: { fontFamily: 'OpenRundeSemibold', fontSize: 18, includeFontPadding: true, letterSpacing: -1, lineHeight: 24, marginLeft: 12, maxWidth: 180 },
  messageStatus: { fontFamily: 'OpenRundeMedium', fontSize: 12, marginTop: 5 },
  messageText: { fontFamily: 'OpenRundeMedium', fontSize: 16, letterSpacing: -0.5, lineHeight: 22 },
  messageTextBold: { fontFamily: 'OpenRundeSemibold', fontSize: 16, letterSpacing: -0.5, lineHeight: 22 },
  messagesContent: { paddingBottom: 22, paddingHorizontal: 14 },
  olderButton: { alignSelf: 'center', paddingHorizontal: 14, paddingVertical: 10 },
  olderButtonText: { fontFamily: 'OpenRundeSemibold', fontSize: 13 },
  queue: { borderRadius: 18, marginTop: 18, paddingHorizontal: 14, paddingVertical: 10 },
  queueActionText: { fontFamily: 'OpenRundeSemibold', fontSize: 12 },
  queueHeader: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  queueMore: { fontFamily: 'OpenRundeMedium', fontSize: 12, marginTop: 8 },
  queueRefresh: { paddingHorizontal: 8, paddingVertical: 6 },
  queueRemove: { paddingLeft: 12, paddingVertical: 10 },
  queueRow: { alignItems: 'center', flexDirection: 'row', minHeight: 42 },
  queueText: { flex: 1, fontFamily: 'OpenRundeMedium', fontSize: 14, lineHeight: 19 },
  queueTitle: { fontFamily: 'OpenRundeSemibold', fontSize: 13 },
  reconciliationText: { color: '#B3261E', fontFamily: 'OpenRundeMedium', fontSize: 14, lineHeight: 20, marginTop: 16, textAlign: 'center' },
  retryButton: { alignSelf: 'flex-end', marginTop: 4, paddingHorizontal: 10, paddingVertical: 4 },
  retryButtonText: { fontFamily: 'OpenRundeSemibold', fontSize: 13 },
  root: { flex: 1 },
  safeArea: { flex: 1 },
  sendBackground: { borderRadius: 999 },
  sendButton: { alignItems: 'center', borderRadius: 999, height: 36, justifyContent: 'center', width: 36 },
  sendIcon: { height: 18, width: 18 },
  state: { alignItems: 'center', flex: 1, justifyContent: 'center', paddingHorizontal: 24 },
  stateText: { fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22, marginBottom: 24, marginTop: 16, textAlign: 'center' },
  statusText: { fontFamily: 'OpenRundeMedium', fontSize: 14, lineHeight: 20, marginTop: 16, textAlign: 'center' },
  thinkingRow: { alignItems: 'center', flexDirection: 'row', gap: 8, marginTop: 22 },
  thinkingText: { fontFamily: 'OpenRundeMedium', fontSize: 16, lineHeight: 22 },
  userMessage: { alignSelf: 'flex-end', borderRadius: 20, marginTop: 14, maxWidth: '88%', paddingHorizontal: 16, paddingVertical: 12 },
  userMessageStatus: { color: 'rgba(255,255,255,0.78)', fontFamily: 'OpenRundeMedium', fontSize: 12, lineHeight: 16, marginTop: 4 },
  userMessageText: { color: '#FFFFFF', fontFamily: 'OpenRundeMedium', fontSize: 16, letterSpacing: -0.5, lineHeight: 22 },
});
