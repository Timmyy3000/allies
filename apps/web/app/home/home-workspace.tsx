"use client";

import type {
  AssistantReplyViewModel,
  ActivitySnapshotViewModel,
  ActivityState,
  AllyDeletionViewModel,
  AllyViewModel,
  ConversationViewModel,
  MessageViewModel,
  RoutineDiscoveryDetail,
} from "@allies/cloud-client";
import {
  EMPTY_ACTIVITY_PROJECTION,
  isCloudError,
  isActivityTerminal,
  mergeConversationMessageCopies,
  projectActivitySnapshot,
  type ActivityProjection,
} from "@allies/cloud-client";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import Onboarding from "../(onboarding)/_components";
import OnboardingDrawer from "../(onboarding)/_components/onboarding-drawer";
import { hasOnboardingResumePending } from "../(onboarding)/_store/onboarding-resume";
import { OnboardingStateProvider } from "../(onboarding)/_store/onboarding-store";
import { AllyAvatar, type AllyShape } from "../../components/ally-avatar";
import { resolveAllyAppearance } from "../../lib/allies/appearance";
import { readIntegrationReturn, type IntegrationReturn } from "../../lib/integrations/integration-connect";
import { currentAccountQueryOptions } from "../../lib/account/account-query";
import { AuthenticatedAllyFlowProvider } from "../../lib/allies/authenticated-onboarding-flow";
import { alliesQueryOptions, conversationQueryKey } from "../../lib/allies/queries";
import { alliesQueryKey } from "../../lib/allies/query-keys";
import { readActivityStream, type ActivityStreamHandle } from "../../lib/allies/activity-stream";
import { useComposingRuntimeIntent } from "../../lib/allies/runtime-intent";
import {
  EMPTY_ACTIVITY_PRESENTATION,
  mergeActivityPresentation,
  type ActivityPresentationState,
} from "../../lib/allies/activity-presentation";
import {
  EMPTY_ACTIVITY_APPROVAL_PROJECTION,
  mergeActivityApprovals,
  selectActivityApprovals,
} from "../../lib/allies/approval-activity";
import {
  getActivitySseEnabled,
  getCreationWakeEnabled,
  getResponsePresentationMode,
  getWebEnvironment,
} from "../../lib/env";
import { useSession } from "../../lib/session/session-context";
import { InstallInvitation } from "../../lib/pwa/pwa-install";

import {
  buildRoutineActionIdempotencyKey,
  buildRoutineActionEvidence,
  buildRoutineActionMessage,
  buildRoutineActionContext,
  buildProductionConversationFrameModel,
  type ProductionQueuedMessageModel,
  type ProductionConversationFrameActions,
  type ProductionRoutineActionState,
  type QueuedAttachmentPreview,
  type RoutineActionRequest,
} from "./conversation-frame-model";
import {
  classifyConversationAccessError,
  type ConversationAccessFailure,
} from "./conversation-access-error";
import { ConversationFrame } from "./conversation-frame";
import {
  ALLY_DELETION_INITIAL_POLL_MS,
  ALLY_DELETION_MAX_POLL_DURATION_MS,
  ALLY_DELETION_MAX_POLL_MS,
  AllySettingsDialog,
} from "./ally-settings-dialog";
import { useConversationFiles } from "./attachments/use-conversation-files";
import { SafeInputLayer } from "./safe-input-layer";
import { ConversationApprovals, type ApprovalClient } from "./conversation-approvals";
import { AlliesLoading } from "../../components/allies-loading";
import { RecipesButton } from "./recipes-button";
import { latestAllyReply, type AllyReplyPreview } from "./ally-preview";
import { useIsMobileHome } from "./use-is-mobile-home";
import { fileTransfers } from "../../lib/files/transfers";
import styles from "./home.module.css";
import attachmentStyles from "./attachments/attachments.module.css";

const MAX_ALLIES = 10;
const ALLY_LIMIT_MESSAGE = "You can have up to 10 Allies for now.";

const ACTIVITY_INTERVAL_MS = 500;
const DURABLE_REPLY_SNAPSHOT_INTERVAL_MS = 3_000;
const STREAM_RECONNECT_BASE_MS = 500;
const STREAM_RECONNECT_MAX_ATTEMPTS = 5;
const QUEUE_SNAPSHOT_INTERVAL_MS = 3_000;
const IDLE_CONVERSATION_SNAPSHOT_INTERVAL_MS = 10_000;
const ERROR_CONVERSATION_SNAPSHOT_INTERVAL_MS = 30_000;
const ACTIVITY_POLL_LIMIT = 240;
const ACTIVITY_REPLAY_MAX_PAGES = 64;
const ACTIVITY_REPLAY_MAX_BYTES = 4 * 1024 * 1024;
const EMPTY_MESSAGES: MessageViewModel[] = [];
const EMPTY_ASSISTANT_REPLIES: AssistantReplyViewModel[] = [];
const ALLY_PREVIEW_LIMIT = 32;
const QUEUED_MESSAGES_STORAGE_VERSION = "v2";
const MAX_QUEUED_MESSAGES = 32;
export const ALLY_SLEEP_AFTER_MS = 20 * 60 * 1_000;
const ALLY_SLEEP_CLOCK_INTERVAL_MS = 30_000;
const QUEUED_MESSAGE_PERSISTENCE_ERROR = "Message not sent: browser storage is unavailable. Keep this page open, allow site storage or free up space, then try again.";
const QUEUED_MESSAGE_REMOVAL_ERROR = "We couldn't remove this queued message. Try again.";
const MESSAGE_ACCEPTANCE_UNKNOWN_ERROR = "We couldn't confirm your message";
const BLOCKED_QUEUE_HEAD_ERROR = "Your earlier message still needs confirmation. Retry it before sending another message.";
export const ROUTINE_ACTION_SENT_TIMEOUT_MS = 30_000;

type AcceptedOnboardingHandoff = {
  ally: AllyViewModel;
  userId: string;
  workspaceId: string;
  greeting: string;
  reply: string;
};

type AllyDeletionState = NonNullable<AllyViewModel["deletionState"]>;

type DeletionPoll = {
  startedAt: number;
  delay: number;
  timer: number | null;
  controller: AbortController | null;
  stopped: boolean;
};

function allyDeletionState(ally: AllyViewModel): AllyDeletionState {
  return ally.deletionState ?? "active";
}

function isAllyDeleting(ally: AllyViewModel): boolean {
  return allyDeletionState(ally) !== "active";
}

function isAllyScopedQuery(queryKey: readonly unknown[], workspaceId: string, allyId: string): boolean {
  return queryKey[0] === "workspaces"
    && queryKey[1] === workspaceId
    && queryKey[2] === "allies"
    && queryKey[3] === allyId;
}

function queuedMessagesStorageKey(userId: string, workspaceId: string, allyId: string): string {
  return `allies:${QUEUED_MESSAGES_STORAGE_VERSION}:queued-messages:${encodeURIComponent(userId)}:${encodeURIComponent(workspaceId)}:${encodeURIComponent(allyId)}`;
}

function legacyQueuedMessagesStorageKey(workspaceId: string, allyId: string): string {
  return `allies:v1:queued-messages:${workspaceId}:${allyId}`;
}

function queuedMessageFenceKey(storageKey: string): string {
  return `${storageKey}:deleted`;
}

function isQueuedMessageStoragePurged(storageKey: string): boolean {
  try {
    return window.localStorage.getItem(queuedMessageFenceKey(storageKey)) === "1";
  } catch {
    return false;
  }
}

function purgeQueuedMessageStorage(storageKey: string): boolean {
  let purged = true;
  try {
    window.localStorage.setItem(queuedMessageFenceKey(storageKey), "1");
    window.localStorage.removeItem(storageKey);
    const keys: string[] = [];
    const prefix = `${storageKey}:removed:`;
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key?.startsWith(prefix)) keys.push(key);
    }
    keys.forEach((key) => window.localStorage.removeItem(key));
  } catch {
    purged = false;
  }
  return purged;
}

function allySettingsRevision(ally: AllyViewModel): number {
  return ally.settingsRevision ?? 0;
}

function mergeUpdatedAlly(current: AllyViewModel | undefined, updated: AllyViewModel): AllyViewModel {
  return current && allySettingsRevision(current) > allySettingsRevision(updated) ? current : updated;
}

export function hasOnboardingExchange(
  messages: readonly MessageViewModel[],
  greeting: string,
  reply: string,
): boolean {
  return messages.some((message) => message.sender === "assistant" && message.sequence === 1 && message.content === greeting)
    && messages.some((message) => message.sender === "user" && message.sequence === 2 && message.content === reply);
}

type QueuedMessage = {
  fileTransferId?: string;
  id: string;
  content: string;
  intentKey: string;
  queuedAt: number;
  attemptedAt?: number;
};

type AssistantReplyState = {
  conversationId: string | null;
  replies: AssistantReplyViewModel[];
};

export class ActivityReplayBoundError extends Error {
  constructor() {
    super("activity replay bounds exceeded");
    this.name = "ActivityReplayBoundError";
  }
}

type ActivityReplayFailure = "gap" | "expired" | "invalid" | "bounds" | null;

export function activityReplayFailure(error: unknown): ActivityReplayFailure {
  if (error instanceof ActivityReplayBoundError) return "bounds";
  if (!isCloudError(error)) return null;
  if (error.kind === "activity-cursor-gap") return "gap";
  if (error.kind === "activity-cursor-expired") return "expired";
  if (error.kind === "activity-cursor-invalid") return "invalid";
  return null;
}

export function activitySnapshotBytes(snapshot: ActivitySnapshotViewModel): number {
  return new TextEncoder().encode(JSON.stringify({
    activities: snapshot.activities,
    assistantReply: snapshot.assistantReply ?? null,
  })).byteLength;
}

function hasVisibleAssistantText(
  snapshot: ActivitySnapshotViewModel,
  messageId?: string | null,
  turnOrdinal?: number | null,
): boolean {
  return snapshot.activities.some(
    (activity) => activity.kind === "assistant_delta"
      && (!messageId || activity.messageId === messageId)
      && (turnOrdinal === undefined || turnOrdinal === null || activity.conversationTurnOrdinal === turnOrdinal)
      && Boolean(activity.text.trim()),
  ) || Boolean(
    snapshot.assistantReply?.hasFullPrefix
      && (!messageId || snapshot.assistantReply.sourceMessageId === messageId)
      && (turnOrdinal === undefined || turnOrdinal === null
        || snapshot.assistantReply.conversationTurnOrdinal === turnOrdinal)
      && snapshot.assistantReply.content.trim(),
  );
}

export function isAllySleeping(
  ally: AllyViewModel,
  latestMessage: MessageViewModel | null,
  now: number | null,
  recentActivityAt = 0,
): boolean {
  if (ally.provisioningState !== "bound" || !latestMessage || now === null) return false;
  const lastActivityAt = Math.max(Date.parse(latestMessage.createdAt), recentActivityAt);
  return Number.isFinite(lastActivityAt) && now - lastActivityAt >= ALLY_SLEEP_AFTER_MS;
}

export function HomeWorkspace({ selectedAllyId }: { selectedAllyId: string | null }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const creationWakeEnabled = getCreationWakeEnabled();
  const sessionStatus = session.state.status;
  const restoreSession = session.restore;
  const router = useRouter();
  const restoreStarted = useRef(false);
  const redirectStarted = useRef(false);
  const [allySearch, setAllySearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [sleepClock, setSleepClock] = useState<number | null>(null);
  const [recentActivityByAlly, setRecentActivityByAlly] = useState<Record<string, number>>({});
  const deletionFence = useMemo(() => ({
    deletedAllyIds: new Set<string>(),
    states: new Map<string, AllyDeletionState>(),
    polls: new Map<string, DeletionPoll>(),
  }), []);
  const [localCleanupFailure, setLocalCleanupFailure] = useState<{
    allyName: string;
    queueKeys: string[];
    scope: string;
  } | null>(null);
  const recordAllyActivity = useCallback((allyId: string) => {
    setRecentActivityByAlly((current) => ({ ...current, [allyId]: Date.now() }));
  }, []);

  useEffect(() => {
    const update = () => setSleepClock(Date.now());
    update();
    const interval = window.setInterval(update, ALLY_SLEEP_CLOCK_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (restoreStarted.current || sessionStatus !== "unknown") return;
    restoreStarted.current = true;
    void restoreSession();
  }, [restoreSession, sessionStatus]);

  useEffect(() => {
    if (!hasOnboardingResumePending()) return;
    router.replace("/");
  }, [router]);

  useEffect(() => {
    if (session.state.status !== "signed-out" || redirectStarted.current) return;
    redirectStarted.current = true;
    const inviteRequired = new URLSearchParams(window.location.search).get("auth_error") === "invite_required";
    router.replace(inviteRequired ? "/?auth_error=invite_required" : "/");
  }, [router, session.state.status]);

  const accountQuery = useQuery({
    ...currentAccountQueryOptions(session.client, session.runCloudOperation),
    enabled: session.state.status === "signed-in",
  });
  const workspaceId = accountQuery.data?.workspace.id ?? "";
  const isAllySuppressed = useCallback((allyId: string) => (
    deletionFence.deletedAllyIds.has(allyId) || deletionFence.states.get(allyId) !== undefined
  ), [deletionFence]);
  const normalizeFetchedAllies = useCallback((fetched: AllyViewModel[]): AllyViewModel[] => {
    const visible = fetched
      .filter((ally) => !deletionFence.deletedAllyIds.has(ally.id))
      .map((ally) => {
        const deletionState = deletionFence.states.get(ally.id);
        return deletionState && deletionState !== "active"
          ? { ...ally, deletionState }
          : ally;
      });
    const visibleIds = new Set(visible.map((ally) => ally.id));
    const cached = queryClient.getQueryData<AllyViewModel[]>(alliesQueryKey(workspaceId)) ?? [];
    cached.forEach((ally) => {
      if (visibleIds.has(ally.id) || deletionFence.deletedAllyIds.has(ally.id)) return;
      const deletionState = deletionFence.states.get(ally.id) ?? allyDeletionState(ally);
      if (deletionState === "active") return;
      visible.push({ ...ally, deletionState });
      visibleIds.add(ally.id);
    });
    return visible;
  }, [deletionFence, queryClient, workspaceId]);
  const alliesOptions = useMemo(
    () => alliesQueryOptions({
      listAllies: async (requestedWorkspaceId, signal) => normalizeFetchedAllies(
        await session.client.listAllies(requestedWorkspaceId, signal),
      ),
    }, session.runCloudOperation, workspaceId),
    [normalizeFetchedAllies, session.client, session.runCloudOperation, workspaceId],
  );
  const alliesQuery = useQuery({
    ...alliesOptions,
    enabled: Boolean(workspaceId),
  });
  const allies = useMemo(() => alliesQuery.data ?? [], [alliesQuery.data]);
  const allyLimitReached = allies.length >= MAX_ALLIES;
  const allyPreviewQueries = useQueries({
    queries: allies.slice(0, ALLY_PREVIEW_LIMIT).map((ally) => ({
      queryKey: [...conversationQueryKey(workspaceId, ally.id), "preview"] as const,
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        const readPage = (cursor?: string) => session.runCloudOperation(
          async (operationSignal) => {
            if (isAllySuppressed(ally.id)) {
              throw new Error("Ally conversation is unavailable during deletion");
            }
            const conversation = await session.client.getAllyConversation(workspaceId, ally.id, {
              limit: 20, ...(cursor ? { cursor } : {}), signal: operationSignal,
            });
            if (isAllySuppressed(ally.id)) {
              throw new Error("Ally conversation is unavailable during deletion");
            }
            return conversation;
          }, { signal },
        );
        const first = await readPage();
        let page = first;
        let reply = latestAllyReply(page);
        const cursors = new Set<string>();
        while (!reply && page.nextCursor && cursors.size < 3 && !cursors.has(page.nextCursor)) {
          cursors.add(page.nextCursor);
          page = await readPage(page.nextCursor);
          reply = latestAllyReply(page);
        }
        return { ...first, previewReply: reply, previewHistoryRemaining: Boolean(!reply && page.nextCursor) };
      },
      enabled: Boolean(workspaceId) && !isAllyDeleting(ally) && !isAllySuppressed(ally.id),
      retry: false,
      staleTime: 30_000,
    })),
  });
  const allyPreviews = useMemo(
    () => new Map(allies.slice(0, ALLY_PREVIEW_LIMIT).map((ally, index) => {
      const query = allyPreviewQueries[index];
      const messages = query?.data?.messages ?? [];
      const latestMessage = messages.reduce<MessageViewModel | null>(
        (latest, message) => (!latest || message.sequence > latest.sequence ? message : latest),
        null,
      );
      return [ally.id, {
        latestMessage,
        latestReply: query?.data?.previewReply ?? null,
        historyRemaining: query?.data?.previewHistoryRemaining ?? false,
        isPending: Boolean(query?.isPending), isError: Boolean(query?.isError),
      }] as const;
    })),
    [allies, allyPreviewQueries],
  );
  const creatingAlly = selectedAllyId === "new";
  const isMobileHome = useIsMobileHome();
  const isDesktopDashboard = !isMobileHome;
  const [createOverlayOpen, setCreateOverlayOpen] = useState(false);
  const [settingsAllyId, setSettingsAllyId] = useState<string | null>(null);
  const [routineOpenRequest, setRoutineOpenRequest] = useState<RoutineOpenRequest | null>(null);
  const locationSearch = useSyncExternalStore(subscribeToLocation, readLocationSearch, () => "");
  const [integrationReturn, setIntegrationReturn] = useState<{ allyId: string; value: IntegrationReturn } | null>(null);
  const [handledIntegrationSearch, setHandledIntegrationSearch] = useState("");
  const pendingIntegrationReturn = selectedAllyId && selectedAllyId !== "new" ? readIntegrationReturn(new URLSearchParams(locationSearch)) : null;
  if (pendingIntegrationReturn && selectedAllyId && locationSearch !== handledIntegrationSearch) {
    setHandledIntegrationSearch(locationSearch);
    setIntegrationReturn({ allyId: selectedAllyId, value: pendingIntegrationReturn });
    setSettingsAllyId(selectedAllyId);
  }
  useEffect(() => {
    if (!handledIntegrationSearch || !selectedAllyId) return;
    router.replace(`/home/${encodeURIComponent(selectedAllyId)}`);
  }, [handledIntegrationSearch, router, selectedAllyId]);
  const [dismissedCreateRoute, setDismissedCreateRoute] = useState(false);
  const [acceptedHandoff, setAcceptedHandoff] = useState<AcceptedOnboardingHandoff | null>(null);
  const [handoffReleased, setHandoffReleased] = useState(false);
  const [handoffRetryAvailable, setHandoffRetryAvailable] = useState(false);
  const [handoffRetryToken, setHandoffRetryToken] = useState(0);
  const pendingCreatedAllyId = useRef<string | null>(null);
  const acceptedHandoffRef = useRef<AcceptedOnboardingHandoff | null>(null);

  const activeHandoff = acceptedHandoff
    && acceptedHandoff.userId === accountQuery.data?.userId
    && acceptedHandoff.workspaceId === workspaceId
    ? acceptedHandoff
    : null;
  const handoffIdentityChanged = Boolean(acceptedHandoff && !activeHandoff);
  const selectedAlly = selectedAllyId
    ? allies.find((ally) => ally.id === selectedAllyId)
      ?? (activeHandoff?.ally.id === selectedAllyId ? activeHandoff.ally : null)
    : null;
  const conversationAlly = selectedAlly ?? activeHandoff?.ally ?? null;
  const settingsAlly = settingsAllyId
    ? allies.find((ally) => ally.id === settingsAllyId)
      ?? (activeHandoff?.ally.id === settingsAllyId ? activeHandoff.ally : null)
    : null;
  const stopDeletionPolling = useCallback((allyId: string) => {
    const poll = deletionFence.polls.get(allyId);
    if (!poll) return;
    poll.stopped = true;
    if (poll.timer !== null) window.clearTimeout(poll.timer);
    poll.controller?.abort();
    deletionFence.polls.delete(allyId);
  }, [deletionFence]);
  const completeAllyDeletion = useCallback((allyId: string) => {
    if (deletionFence.deletedAllyIds.has(allyId)) return;
    deletionFence.deletedAllyIds.add(allyId);
    deletionFence.states.delete(allyId);
    stopDeletionPolling(allyId);
    void queryClient.cancelQueries({
      predicate: (query) => isAllyScopedQuery(query.queryKey, workspaceId, allyId),
    });
    queryClient.removeQueries({
      predicate: (query) => isAllyScopedQuery(query.queryKey, workspaceId, allyId),
    });
    queryClient.setQueryData<AllyViewModel[]>(alliesQueryKey(workspaceId), (current) => (
      current?.filter((ally) => ally.id !== allyId)
    ));
    const userId = accountQuery.data?.userId;
    if (userId) {
      const targetAlly = allies.find((ally) => ally.id === allyId);
      const scope = `${userId}:${workspaceId}:${allyId}`;
      const queueKeys = [
        queuedMessagesStorageKey(userId, workspaceId, allyId),
        legacyQueuedMessagesStorageKey(workspaceId, allyId),
      ];
      const queuePurged = queueKeys.map(purgeQueuedMessageStorage).every(Boolean);
      const reportFailure = () => setLocalCleanupFailure({
        allyName: targetAlly?.name ?? "this Ally",
        queueKeys,
        scope,
      });
      if (!queuePurged) reportFailure();
      void fileTransfers(session.client, session.runCloudOperation)
        .clearScope(scope)
        .catch(reportFailure);
    }
    if (selectedAllyId === allyId) router.replace("/home");
  }, [accountQuery.data?.userId, allies, deletionFence, queryClient, router, selectedAllyId, session.client, session.runCloudOperation, stopDeletionPolling, workspaceId]);
  const retryLocalCleanup = useCallback(() => {
    const failure = localCleanupFailure;
    if (!failure) return;
    const queuePurged = failure.queueKeys.map(purgeQueuedMessageStorage).every(Boolean);
    void fileTransfers(session.client, session.runCloudOperation)
      .clearScope(failure.scope)
      .then(() => { if (queuePurged) setLocalCleanupFailure(null); })
      .catch(() => setLocalCleanupFailure(failure));
  }, [localCleanupFailure, session.client, session.runCloudOperation]);
  const applyAllyDeletionStatus = useCallback((status: AllyDeletionViewModel) => {
    if (status.allyId !== "" && deletionFence.deletedAllyIds.has(status.allyId)) return;
    if (status.state === "complete") {
      completeAllyDeletion(status.allyId);
      return;
    }
    const deletionState: AllyDeletionState = status.state === "pending" ? "pending" : "repair_required";
    deletionFence.states.set(status.allyId, deletionState);
    queryClient.setQueryData<AllyViewModel[]>(alliesQueryKey(workspaceId), (current) => (
      current?.map((ally) => ally.id === status.allyId
        ? { ...ally, deletionState }
        : ally)
    ));
  }, [completeAllyDeletion, deletionFence, queryClient, workspaceId]);
  const pollAllyDeletion = useCallback((allyId: string) => {
    const poll = deletionFence.polls.get(allyId);
    if (!poll || poll.stopped || poll.timer !== null || poll.controller !== null) return;
    const schedule = () => {
      const current = deletionFence.polls.get(allyId);
      if (!current || current.stopped || current.timer !== null || current.controller !== null) return;
      if (document.visibilityState === "hidden" || navigator.onLine === false) return;
      const remaining = ALLY_DELETION_MAX_POLL_DURATION_MS - (Date.now() - current.startedAt);
      if (remaining <= 0) {
        current.stopped = true;
        return;
      }
      current.timer = window.setTimeout(async () => {
        current.timer = null;
        if (document.visibilityState === "hidden" || navigator.onLine === false) {
          schedule();
          return;
        }
        const controller = new AbortController();
        current.controller = controller;
        try {
          const status = await session.runCloudOperation(
            (signal) => session.client.getAllyDeletion(workspaceId, allyId, signal),
            { signal: controller.signal, retryTransient: false },
          );
          if (!deletionFence.deletedAllyIds.has(allyId)) {
            applyAllyDeletionStatus(status);
            if (status.state !== "complete") current.delay = Math.min(current.delay * 2, ALLY_DELETION_MAX_POLL_MS);
          }
        } catch {
          current.delay = Math.min(current.delay * 2, ALLY_DELETION_MAX_POLL_MS);
        } finally {
          if (current.controller === controller) current.controller = null;
          if (deletionFence.polls.get(allyId) === current && !current.stopped) schedule();
        }
      }, Math.min(current.delay, ALLY_DELETION_MAX_POLL_MS, remaining));
    };
    schedule();
  }, [applyAllyDeletionStatus, deletionFence, session, workspaceId]);
  const refreshAllyDeletion = useCallback(async (allyId: string) => {
    if (deletionFence.deletedAllyIds.has(allyId)) {
      throw new Error("Ally deletion is already complete");
    }
    const existing = deletionFence.polls.get(allyId);
    if (!existing) {
      deletionFence.polls.set(allyId, {
        startedAt: Date.now(),
        delay: ALLY_DELETION_INITIAL_POLL_MS,
        timer: null,
        controller: null,
        stopped: false,
      });
    } else if (existing.stopped) {
      existing.stopped = false;
      existing.timer = null;
      existing.controller = null;
    }
    const status = await session.runCloudOperation(
      (signal) => session.client.getAllyDeletion(workspaceId, allyId, signal),
      { retryTransient: false },
    );
    if (status.allyId !== allyId) throw new Error("Ally deletion status belongs to a different Ally");
    applyAllyDeletionStatus(status);
    if (status.state !== "complete") pollAllyDeletion(allyId);
    return status;
  }, [applyAllyDeletionStatus, deletionFence, pollAllyDeletion, session, workspaceId]);
  useEffect(() => {
    allies.forEach((ally) => {
      const state = allyDeletionState(ally);
      if (state === "active" || deletionFence.deletedAllyIds.has(ally.id)) return;
      deletionFence.states.set(ally.id, state);
      if (!deletionFence.polls.has(ally.id)) {
        deletionFence.polls.set(ally.id, {
          startedAt: Date.now(),
          delay: ALLY_DELETION_INITIAL_POLL_MS,
          timer: null,
          controller: null,
          stopped: false,
        });
      }
      pollAllyDeletion(ally.id);
    });
  }, [allies, deletionFence, pollAllyDeletion]);
  useEffect(() => {
    const resume = () => {
      if (document.visibilityState === "hidden" || navigator.onLine === false) return;
      deletionFence.polls.forEach((poll, allyId) => {
        if (poll.timer === null && poll.controller === null && !poll.stopped) pollAllyDeletion(allyId);
      });
    };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    return () => {
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
    };
  }, [deletionFence, pollAllyDeletion]);
  useEffect(() => () => {
    [...deletionFence.polls.keys()].forEach(stopDeletionPolling);
  }, [deletionFence, stopDeletionPolling]);
  const openAllySettings = useCallback((allyId: string) => setSettingsAllyId(allyId), []);
  const replaceAlly = useCallback((updated: AllyViewModel) => {
    if (deletionFence.deletedAllyIds.has(updated.id)) return;
    const activeDeletionState = deletionFence.states.get(updated.id);
    const protectedUpdated = activeDeletionState
      ? { ...updated, deletionState: activeDeletionState }
      : updated;
    let mergedResult = protectedUpdated;
    queryClient.setQueryData<AllyViewModel[]>(alliesQueryKey(workspaceId), (current) => {
      if (!current) return [protectedUpdated];
      const existing = current.find((ally) => ally.id === protectedUpdated.id);
      const merged = mergeUpdatedAlly(existing, protectedUpdated);
      mergedResult = merged;
      if (!existing) return [...current, protectedUpdated];
      if (merged === existing) return current;
      return current.map((ally) => ally.id === protectedUpdated.id ? merged : ally);
    });

    const currentHandoff = acceptedHandoffRef.current;
    if (currentHandoff?.ally.id !== updated.id) return;
    const mergedHandoffAlly = mergeUpdatedAlly(currentHandoff.ally, mergedResult);
    if (mergedHandoffAlly === currentHandoff.ally) return;
    const nextHandoff = { ...currentHandoff, ally: mergedHandoffAlly };
    acceptedHandoffRef.current = nextHandoff;
    setAcceptedHandoff(nextHandoff);
  }, [deletionFence, queryClient, workspaceId]);

  if (!creatingAlly && dismissedCreateRoute) {
    setDismissedCreateRoute(false);
  }

  if (creatingAlly && !createOverlayOpen && !dismissedCreateRoute) {
    setCreateOverlayOpen(true);
  }

  const openCreateOverlay = useCallback(() => {
    if (allyLimitReached) return;
    pendingCreatedAllyId.current = null;
    setDismissedCreateRoute(false);
    setCreateOverlayOpen(true);
  }, [allyLimitReached]);

  const closeCreateOverlay = useCallback(() => {
    if (acceptedHandoffRef.current && !handoffReleased) return;
    setCreateOverlayOpen(false);
    if (creatingAlly) setDismissedCreateRoute(true);
  }, [creatingAlly, handoffReleased]);

  const handleCreated = useCallback(
    (ally: AllyViewModel, handoff: { greeting: string; reply: string }) => {
      if (acceptedHandoffRef.current) return;
      const accepted = { ally, userId: accountQuery.data?.userId ?? "", workspaceId, ...handoff };
      acceptedHandoffRef.current = accepted;
      setAcceptedHandoff(accepted);
      setHandoffReleased(false);
      setHandoffRetryAvailable(false);
      queryClient.setQueryData<AllyViewModel[]>(alliesQueryKey(workspaceId), (current) => {
        if (current?.some((item) => item.id === ally.id)) return current;
        return [...(current ?? []), ally];
      });
      pendingCreatedAllyId.current = ally.id;
      router.replace(`/home/${encodeURIComponent(ally.id)}`);
      setCreateOverlayOpen(true);
    },
    [accountQuery.data?.userId, queryClient, router, workspaceId],
  );

  const handleCreateOverlayClosed = useCallback(() => {
    if (acceptedHandoffRef.current && !handoffReleased) return;
    const createdId = pendingCreatedAllyId.current;
    pendingCreatedAllyId.current = null;
    if (createdId || !creatingAlly) return;
    router.replace("/home");
  }, [creatingAlly, handoffReleased, router]);

  const handleHandoffReady = useCallback(() => {
    if (!acceptedHandoffRef.current) return;
    setHandoffRetryAvailable(false);
    setHandoffReleased(true);
    setCreateOverlayOpen(false);
  }, []);

  const retryHandoff = useCallback(() => {
    const accepted = acceptedHandoffRef.current;
    if (!accepted) return;
    setHandoffRetryAvailable(false);
    setHandoffRetryToken((current) => current + 1);
    router.replace(`/home/${encodeURIComponent(accepted.ally.id)}`);
  }, [router]);

  const handleHandoffRetryAvailable = useCallback(() => {
    setHandoffRetryAvailable(true);
  }, []);

  useEffect(() => {
    if (!handoffIdentityChanged) return;
    const task = window.setTimeout(() => {
      acceptedHandoffRef.current = null;
      setAcceptedHandoff(null);
      setHandoffReleased(false);
      setHandoffRetryAvailable(false);
    });
    return () => window.clearTimeout(task);
  }, [handoffIdentityChanged]);

  useEffect(() => {
    if (!handoffReleased || !activeHandoff || selectedAllyId !== activeHandoff.ally.id) return;
    if (!allies.some((ally) => ally.id === activeHandoff.ally.id)) return;
    const task = window.setTimeout(() => {
      acceptedHandoffRef.current = null;
      setAcceptedHandoff(null);
    });
    return () => window.clearTimeout(task);
  }, [activeHandoff, allies, handoffReleased, selectedAllyId]);
  const hasBlockingQueryError = (accountQuery.isError && !accountQuery.data)
    || (alliesQuery.isError && !alliesQuery.data);
  const hasBackgroundQueryError = (accountQuery.isError && Boolean(accountQuery.data))
    || (alliesQuery.isError && Boolean(alliesQuery.data));
  const refetchAccount = accountQuery.refetch;
  const refetchAllies = alliesQuery.refetch;
  const retryWorkspaceQueries = useCallback(() => {
    void Promise.all([refetchAccount(), refetchAllies()]);
  }, [refetchAccount, refetchAllies]);

  if (session.state.status === "unavailable") {
    return (
      <HomeStatus
        title="We couldn't reach your Allies"
        detail="Your account is safe. Try the connection again."
        action={{ label: "Try again", onClick: () => void session.restore() }}
      />
    );
  }
  if (hasBlockingQueryError) {
    return (
      <HomeStatus
        title="We couldn't load your Allies"
        detail="Nothing has been changed."
        action={{
          label: "Try again",
          onClick: retryWorkspaceQueries,
        }}
      />
    );
  }

  const waitingForWorkspace = session.state.status === "unknown"
    || session.state.status === "restoring"
    || session.state.status === "signed-out"
    || !accountQuery.data
    || alliesQuery.isPending;

  if (waitingForWorkspace) {
    return <AlliesLoading />;
  }

  const invalidSelection = Boolean(selectedAllyId && !creatingAlly && !conversationAlly);
  const showDesktopDashboard = isDesktopDashboard;
  const showThread = Boolean(selectedAllyId) || showDesktopDashboard || Boolean(activeHandoff);

  const threadBody = conversationAlly && !isAllyDeleting(conversationAlly) ? (
    <ConversationPane
      key={conversationAlly.id}
      userId={accountQuery.data.userId}
      workspaceId={workspaceId}
      canApprove={accountQuery.data.workspace.capabilities.includes("profile.write")}
      ally={conversationAlly}
      isAllySuppressed={isAllySuppressed}
      onOpenSettings={() => openAllySettings(conversationAlly.id)}
      routineOpenRequest={routineOpenRequest?.allyId === conversationAlly.id ? routineOpenRequest : null}
      onRoutineOpenRequestHandled={() => setRoutineOpenRequest(null)}
      onActivity={() => recordAllyActivity(conversationAlly.id)}
      stateReady={sleepClock !== null && Boolean(allyPreviews.get(conversationAlly.id)) && !allyPreviews.get(conversationAlly.id)?.isPending}
      sleeping={isAllySleeping(conversationAlly, allyPreviews.get(conversationAlly.id)?.latestMessage ?? null, sleepClock, recentActivityByAlly[conversationAlly.id])}
      workspaceRefreshError={hasBackgroundQueryError}
      onRetryWorkspace={retryWorkspaceQueries}
      handoffGreeting={activeHandoff?.ally.id === conversationAlly.id ? activeHandoff.greeting : undefined}
      handoffReply={activeHandoff?.ally.id === conversationAlly.id ? activeHandoff.reply : undefined}
      handoffRouteReady={selectedAllyId === conversationAlly.id}
      handoffRetryToken={handoffRetryToken}
      onHandoffReady={handleHandoffReady}
      onHandoffRetryAvailable={handleHandoffRetryAvailable}
    />
  ) : conversationAlly && isAllyDeleting(conversationAlly) ? (
    <AllyDeletionStatusPane
      ally={conversationAlly}
      onRefresh={() => refreshAllyDeletion(conversationAlly.id)}
    />
  ) : creatingAlly || !selectedAllyId ? (
    <EmptyThread />
  ) : invalidSelection ? (
    <EmptyThread
      title="That Ally isn't in this Workspace"
      detail="Choose one of your Allies to keep talking."
      action={<Link className={styles.primaryAction} href="/home">Back to Allies</Link>}
    />
  ) : <EmptyThread />;

  const createOverlay = (
    <OnboardingDrawer
      open={createOverlayOpen}
      onClose={closeCreateOverlay}
      onClosed={handleCreateOverlayClosed}
    >
      <div className={styles.creationOverlay}>
        {activeHandoff ? (
          <main className="onboarding-handoff">
            <h1>{handoffRetryAvailable ? "Your Ally is still opening" : `Opening ${activeHandoff.ally.name}`}</h1>
            <p role={handoffRetryAvailable ? "alert" : "status"} aria-live="polite">
              {handoffRetryAvailable ? "We couldn't confirm the first conversation yet." : "Keeping your first conversation together…"}
            </p>
            {handoffRetryAvailable ? <button type="button" onClick={retryHandoff}>Try again</button> : null}
          </main>
        ) : (
          allyLimitReached ? (
            <main className="onboarding-handoff">
              <h1>Ally limit reached</h1>
              <p role="status">{ALLY_LIMIT_MESSAGE}</p>
              <button type="button" onClick={closeCreateOverlay}>Back to Allies</button>
            </main>
          ) : <OnboardingStateProvider initialStep="job">
            <AuthenticatedAllyFlowProvider
              workspaceId={workspaceId}
              onCreated={handleCreated}
              creationWakeEnabled={creationWakeEnabled}
            >
              <Onboarding exitHref="/home" onExit={closeCreateOverlay} />
            </AuthenticatedAllyFlowProvider>
          </OnboardingStateProvider>
        )}
      </div>
    </OnboardingDrawer>
  );

  const matchingAllies = allies.filter((ally) => ally.name.toLocaleLowerCase().includes(allySearch.trim().toLocaleLowerCase()));
  const allyRows = (exact: boolean) => allies.length ? (
    <nav className={exact ? styles.exactAllyList : styles.allyList} aria-label="Choose an Ally">
      {matchingAllies.map((ally) => (
        <AllyConversationRow
          key={ally.id}
          ally={ally}
          selected={ally.id === selectedAllyId}
          preview={allyPreviews.get(ally.id)}
          sleepClock={sleepClock}
          recentActivityAt={recentActivityByAlly[ally.id]}
          exact={exact}
        />
      ))}
    </nav>
  ) : (
    <div className={styles.rosterEmpty}>
      <p>No Allies here yet.</p>
      <button
        type="button"
        className={`${styles.primaryAction} ${styles.mobileOnly} ${styles.exactUnstyledButton}`}
        onClick={openCreateOverlay}
      >
        Meet your first Ally
      </button>
    </div>
  );

  const sidebar = (
    <aside className={`${styles.homeSidebar} ${selectedAllyId ? styles.rosterHiddenOnMobile : ""}`} aria-label="Ally sidebar">
      <header className={styles.sidebarHeader}>
        <div className={styles.sidebarProfileControls}>
          <Link
            className={`${styles.exactMobileAction} ${styles.exactMobileActionWash} ${styles.exactMobileProfile}`}
            href="/account"
            aria-label={accountQuery.data.displayName || "Open account"}
          >
            {initials(accountQuery.data.displayName)}
          </Link>
          <RecipesButton className={`${styles.exactMobileAction} ${styles.exactMobileActionCreate}`}>
            <ChefIcon />
          </RecipesButton>
        </div>
        <button
          type="button"
          className={`${styles.exactMobileAction} ${styles.exactMobileActionWash}`}
          aria-label="Search Allies"
          aria-expanded={searchOpen}
          aria-controls="ally-search"
          onClick={() => { setSearchOpen(!searchOpen); setAllySearch(""); }}
        >
          <SearchIcon />
        </button>
      </header>
      {localCleanupFailure ? (
        <p className={styles.localCleanupNotice} role="alert">
          Cloud deletion completed for {localCleanupFailure.allyName}, but this browser could not erase all of its saved local drafts.
          <button type="button" onClick={retryLocalCleanup}>Retry local cleanup</button>
        </p>
      ) : null}
      {/* Restore the view controls when the Routines sidebar is ready.
      <div className={styles.sidebarTabs} aria-label="Sidebar views">
        <button type="button" className={styles.sidebarTab} aria-pressed="true">My allies</button>
        <button type="button" className={`${styles.sidebarTab} ${styles.sidebarTabMuted}`} disabled>Routines</button>
      </div> */}
      {searchOpen ? (
        <input
          id="ally-search"
          className={styles.sidebarSearch}
          type="search"
          aria-label="Filter Allies by name"
          placeholder="Search Allies"
          value={allySearch}
          onChange={(event) => setAllySearch(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") { setAllySearch(""); setSearchOpen(false); }
          }}
        />
      ) : null}
      <div className={styles.sidebarList}>
        {hasBackgroundQueryError && !selectedAllyId ? <WorkspaceRefreshError onRetry={retryWorkspaceQueries} /> : null}
        {allyRows(true)}
        {allies.length > 0 && matchingAllies.length === 0 ? (
          <p role="status" className={styles.sidebarNoResults}>No Allies match your search.</p>
        ) : null}
      </div>
      <footer className={styles.sidebarFooter}>
        <p id="ally-creation-limit" className={styles.allyCreationLimit} role="status">
          {allies.length} / {MAX_ALLIES} Allies{allyLimitReached ? ` · ${ALLY_LIMIT_MESSAGE}` : ""}
        </p>
        <button type="button" className={styles.exactMobileCreate} aria-label="Make an Ally" aria-describedby="ally-creation-limit" disabled={allyLimitReached} onClick={openCreateOverlay}>Make an ally</button>
      </footer>
    </aside>
  );

  const showRoster = !activeHandoff || (handoffReleased && selectedAllyId === activeHandoff.ally.id);

  return (
    <main className={showDesktopDashboard ? styles.homeLayout : styles.exactMobileHost} data-testid={showDesktopDashboard ? "dashboard-ui-push" : "mobile-home-roster"}>
      {showRoster ? sidebar : null}
      {showThread ? (
        <section className={styles.exactThread} aria-label="Selected Ally conversation">
          {threadBody}
        </section>
      ) : null}
      {settingsAlly ? (
        <AllySettingsDialog
          ally={settingsAlly}
          workspaceId={workspaceId}
          onClose={() => {
            setSettingsAllyId(null);
            setIntegrationReturn(null);
          }}
          integrationReturn={integrationReturn?.allyId === settingsAlly.id ? integrationReturn.value : null}
          onSaved={replaceAlly}
          onDeletionStatus={applyAllyDeletionStatus}
          onRefreshDeletion={() => refreshAllyDeletion(settingsAlly.id)}
          onOpenRoutine={(routineId) => {
            setSettingsAllyId(null);
            setRoutineOpenRequest({ allyId: settingsAlly.id, routineId });
            if (selectedAllyId !== settingsAlly.id) router.push(`/home/${encodeURIComponent(settingsAlly.id)}`);
          }}
        />
      ) : null}
      {createOverlay}
      {!selectedAllyId && !createOverlayOpen ? <InstallInvitation /> : null}
    </main>
  );
}

export { resolveAllyAppearance };

function subscribeToLocation(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

function readLocationSearch() {
  return window.location.search;
}

type RoutineOpenRequest = { allyId: string; routineId: string };

function AllyIdentityAvatar({
  ally,
  size,
  thinking = false,
  sleeping = false,
  stateReady = true,
}: {
  ally: AllyViewModel;
  size: number;
  thinking?: boolean;
  sleeping?: boolean;
  stateReady?: boolean;
}) {
  const avatar = resolveAllyAppearance(ally);
  if (!avatar) {
    return (
      <span
        className={styles.appearanceUnavailable}
        data-testid="ally-appearance-unavailable"
        role="img"
        aria-label="Ally appearance unavailable"
        style={{ width: size, height: size }}
      >
        ?
      </span>
    );
  }
  return (
    <AllyAvatar
      stateReady={stateReady}
      shape={avatar.shape}
      color={avatar.color}
      state={thinking || isGettingReady(ally) ? "thinking" : sleeping ? "sleeping" : "idle"}
      size={size}
      label=""
      className={sleeping ? styles.sleepingAvatar : undefined}
    />
  );
}

type AllyPreview = {
  latestMessage: MessageViewModel | null;
  latestReply: AllyReplyPreview | null;
  historyRemaining: boolean;
  isPending: boolean;
  isError: boolean;
};

function previewText(message: AllyReplyPreview | null): string {
  if (!message?.content.trim()) return "No reply yet";
  return message.content
    .replace(/[`*_>#\[\]]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function previewTimestamp(value: string | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function AllyConversationRow({
  ally,
  selected,
  preview,
  sleepClock,
  recentActivityAt,
  exact = false,
}: {
  ally: AllyViewModel;
  selected: boolean;
  preview?: AllyPreview;
  sleepClock: number | null;
  recentActivityAt?: number;
  exact?: boolean;
}) {
  const deleting = isAllyDeleting(ally);
  const latestMessage = deleting ? null : preview?.latestMessage ?? null;
  const sleeping = isAllySleeping(ally, latestMessage, sleepClock, recentActivityAt);
  const rowClassName = `${styles.allyRow} ${selected ? styles.allyRowSelected : ""} ${exact ? styles.exactAllyRow : ""} ${deleting ? styles.allyRowDisabled : ""}`;
  const content = (
    <>
      <span className={styles.allyAvatarWrap}>
        <AllyIdentityAvatar ally={ally} size={48} sleeping={sleeping} stateReady={sleepClock !== null && Boolean(preview) && !preview?.isPending} />
        <span
          className={`${styles.presenceDot} ${ally.provisioningState === "bound" && !sleeping ? styles.presenceDotReady : styles.presenceDotQuiet}`}
          aria-hidden="true"
        />
      </span>
      <span className={styles.allyCopy}>
        <span className={styles.allyMeta}>
          <strong>{ally.name}</strong>
          {latestMessage ? <time dateTime={latestMessage.createdAt}>{previewTimestamp(latestMessage.createdAt)}</time> : null}
        </span>
        {ally.showLabel && ally.label?.trim() ? (
          <span className={styles.allyLabel} title={ally.label.trim()}>{ally.label.trim()}</span>
        ) : null}
        <span className={preview?.isPending ? styles.allyPreviewPending : styles.allyPreview}>
          {deleting
            ? allySecondaryLine(ally)
            : preview === undefined || preview.isError
            ? allySecondaryLine(ally)
            : preview.isPending && !latestMessage
              ? "Opening conversation…"
              : preview.historyRemaining ? "Open conversation" : previewText(preview.latestReply)}
        </span>
      </span>
    </>
  );
  if (deleting) {
    return (
      <div
        className={rowClassName}
        aria-disabled="true"
        data-ally-deletion-state={allyDeletionState(ally)}
        data-ally-sleeping={sleeping ? "true" : "false"}
      >
        {content}
      </div>
    );
  }
  return (
    <Link
      href={`/home/${encodeURIComponent(ally.id)}`}
      className={rowClassName}
      aria-current={selected ? "page" : undefined}
      data-ally-sleeping={sleeping ? "true" : "false"}
    >
      {content}
    </Link>
  );
}

function ConversationPane({
  sleeping,
  stateReady,
  userId,
  workspaceId,
  canApprove,
  ally,
  isAllySuppressed,
  onOpenSettings,
  routineOpenRequest,
  onRoutineOpenRequestHandled,
  onActivity,
  workspaceRefreshError,
  onRetryWorkspace,
  handoffGreeting,
  handoffReply,
  handoffRouteReady,
  handoffRetryToken,
  onHandoffReady,
  onHandoffRetryAvailable,
}: {
  userId: string;
  workspaceId: string;
  canApprove: boolean;
  ally: AllyViewModel;
  isAllySuppressed: (allyId: string) => boolean;
  onOpenSettings?: () => void;
  routineOpenRequest: RoutineOpenRequest | null;
  onRoutineOpenRequestHandled: () => void;
  onActivity: () => void;
  sleeping: boolean;
  stateReady: boolean;
  workspaceRefreshError: boolean;
  onRetryWorkspace: () => void;
  handoffGreeting?: string;
  handoffReply?: string;
  handoffRouteReady?: boolean;
  handoffRetryToken?: number;
  onHandoffReady?: () => void;
  onHandoffRetryAvailable?: () => void;
}) {
  const session = useSession();
  const responsePresentationMode = getResponsePresentationMode();
  const approvalClient = useMemo<ApprovalClient>(() => ({
    getApprovals: (workspace, conversation, signal) => session.runCloudOperation((operationSignal) => session.client.getApprovals(workspace, conversation, operationSignal), { signal, retryTransient: "approval-read" }),
    getApproval: (workspace, conversation, approval, signal) => session.runCloudOperation((operationSignal) => session.client.getApproval(workspace, conversation, approval, operationSignal), { signal, retryTransient: "approval-read" }),
    decideApproval: (workspace, conversation, approval, decision, key, signal) => session.runCloudOperation((operationSignal) => session.client.decideApproval(workspace, conversation, approval, decision, key, operationSignal), { signal, csrf: true, retryTransient: false }),
  }), [session]);
  const requestRuntimeIntent = useCallback(
    (targetAllyId: string, occurredAt: string, idempotencyKey: string, signal?: AbortSignal) =>
      session.runCloudOperation(
        (operationSignal) => session.client.requestRuntimeIntent(targetAllyId, occurredAt, idempotencyKey, operationSignal),
        { csrf: true, retryTransient: true, signal },
      ),
    [session],
  );
  const { observeEdit, observeAttachment, compositionStart, compositionEnd, status: runtimeIntentStatus } = useComposingRuntimeIntent(
    ally.id,
    requestRuntimeIntent,
  );
  const attachmentAccepted = useCallback(() => {
    onActivity();
    observeAttachment();
  }, [observeAttachment, onActivity]);
  const attachments = useConversationFiles(userId, workspaceId, ally.id, attachmentAccepted);
  const fileManager = attachments.manager;
  const fileScope = attachments.scope;
  const preparingFilesRef = useRef(false);
  const [preparingFiles, setPreparingFiles] = useState(false);
  const changeAttachments = attachments.change;
  const queryClient = useQueryClient();
  const [olderMessages, setOlderMessages] = useState<MessageViewModel[]>([]);
  const [nextCursorOverride, setNextCursorOverride] = useState<string | null | undefined>(undefined);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderLoadError, setOlderLoadError] = useState<string | null>(null);
  const [sentMessages, setSentMessages] = useState<MessageViewModel[]>([]);
  const [immediateMessageIds, setImmediateMessageIds] = useState<ReadonlySet<string>>(() => new Set());
  const [draft, setDraft] = useState("");
  const [selectedRoutineId, setSelectedRoutineId] = useState<string | null>(null);
  const [seenRoutineOpenRequest, setSeenRoutineOpenRequest] = useState<RoutineOpenRequest | null>(null);
  if (routineOpenRequest !== seenRoutineOpenRequest) {
    setSeenRoutineOpenRequest(routineOpenRequest);
    if (routineOpenRequest) setSelectedRoutineId(routineOpenRequest.routineId);
  }
  const [routineActionState, setRoutineActionState] = useState<ProductionRoutineActionState | null>(null);
  const routineActionEvidenceRef = useRef<string | null>(null);
  const draftRef = useRef("");
  const [assistantReplyState, setAssistantReplyState] = useState<AssistantReplyState>({
    conversationId: null,
    replies: [],
  });
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const queuedMessagesRef = useRef<QueuedMessage[]>([]);
  const [queuedMessagesLoadedFor, setQueuedMessagesLoadedFor] = useState<string | null>(null);
  const queuedDispatchRef = useRef(false);
  const blockedQueuedMessageIdsRef = useRef<Set<string>>(new Set());
  const [queuePersistenceError, setQueuePersistenceError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [sendingMessageId, setSendingMessageId] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [retryingMessageId, setRetryingMessageId] = useState<string | null>(null);
  const [retriedMessageIds, setRetriedMessageIds] = useState<Set<string>>(() => new Set());
  const [retryError, setRetryError] = useState<string | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activityHistoryError, setActivityHistoryError] = useState<string | null>(null);
  const [activityReplayUnavailable, setActivityReplayUnavailable] = useState(false);
  const intentRef = useRef<{ signature: string; key: string; draftRevision: number } | null>(null);
  const draftRevisionRef = useRef(0);
  const [activeTurn, setActiveTurn] = useState(false);
  const [awaitingVisibleResponse, setAwaitingVisibleResponse] = useState(false);
  const [pollingSettled, setPollingSettled] = useState(false);
  const [streamConnected, setStreamConnected] = useState(false);
  // Polling is only a fallback for when SSE is disabled or keeps failing to reconnect.
  const [streamFallback, setStreamFallback] = useState(false);
  const [streamRetry, setStreamRetry] = useState(0);
  const streamRetryCountRef = useRef(0);
  const lastStreamEventAtRef = useRef(0);
  const [pollBudgetReached, setPollBudgetReached] = useState(false);
  // The poll budget bounds stalls, not long turns: new activity resets it.
  const polledProgressRef = useRef<{ conversationId: string; sequence: number } | null>(null);
  const [projection, setProjection] = useState<ActivityProjection>(EMPTY_ACTIVITY_PROJECTION);
  const [activityPresentation, setActivityPresentation] = useState<ActivityPresentationState>(
    EMPTY_ACTIVITY_PRESENTATION,
  );
  const [activityApprovals, setActivityApprovals] = useState(
    EMPTY_ACTIVITY_APPROVAL_PROJECTION,
  );
  const pollingRef = useRef(false);
  const pollCountRef = useRef(0);
  const activityHistoryLoadedRef = useRef<string | null>(null);
  const previousProvisioningStateRef = useRef(ally.provisioningState);
  const activityReplayRef = useRef<{
    conversationId: string;
    cursor: string | null;
    afterSequence: number;
    blocked: "gap" | "invalid" | null;
  } | null>(null);
  const activityReplayExpiredRestartedRef = useRef(false);
  const [activityHistoryRetry, setActivityHistoryRetry] = useState(0);
  const [conversationAccessFailure, setConversationAccessFailure] = useState<ConversationAccessFailure | null>(null);
  const conversationAccessFailureRef = useRef<ConversationAccessFailure | null>(null);
  const queryAccessFailureRef = useRef<ConversationAccessFailure | null>(null);
  const activityRequestRef = useRef<AbortController | null>(null);
  const activitySnapshotRequestRef = useRef<AbortController | null>(null);
  const activityHistoryRequestRef = useRef<AbortController | null>(null);
  const activityStreamRef = useRef<ActivityStreamHandle | null>(null);
  const activeMessageIdRef = useRef<string | null>(null);
  const activeMessageOrdinalRef = useRef<number | null>(null);
  const conversationMessagesRef = useRef<readonly MessageViewModel[]>(EMPTY_MESSAGES);
  const [deletedMessageIds, setDeletedMessageIds] = useState<Set<string>>(() => new Set());
  const turnGenerationRef = useRef(0);
  const responseStartedRef = useRef(false);
  const olderRequestRef = useRef<AbortController | null>(null);
  const historyRevisionRef = useRef(0);
  const mountedRef = useRef(true);
  const messageCanvasRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(true);
  const queuedMessagesStorageKey = `allies:${QUEUED_MESSAGES_STORAGE_VERSION}:queued-messages:${encodeURIComponent(userId)}:${encodeURIComponent(workspaceId)}:${encodeURIComponent(ally.id)}`;
  const legacyQueuedMessagesStorageKey = `allies:v1:queued-messages:${workspaceId}:${ally.id}`;
  const queuedMessagesReady = queuedMessagesLoadedFor === queuedMessagesStorageKey;

  const presentAssistantReply = useCallback((conversationId: string, reply: AssistantReplyViewModel) => {
    setAssistantReplyState((current) => mergeAssistantReplyState(current, conversationId, [reply]));
  }, []);

  const presentActivitySnapshot = useCallback((snapshot: ActivitySnapshotViewModel) => {
    if (snapshot.assistantReply) presentAssistantReply(snapshot.conversationId, snapshot.assistantReply);
    setActivityApprovals((current) => mergeActivityApprovals(
      current,
      snapshot.conversationId,
      snapshot.activities,
    ));
    setActivityPresentation((current) => mergeActivityPresentation(current, {
      conversationId: snapshot.conversationId,
      activities: snapshot.activities,
    }));
  }, [presentAssistantReply]);

  const presentActivity = useCallback((conversationId: string, activity: ActivitySnapshotViewModel["activities"][number]) => {
    setActivityPresentation((current) => mergeActivityPresentation(current, {
      conversationId,
      activities: [activity],
    }));
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activityRequestRef.current?.abort();
      activitySnapshotRequestRef.current?.abort();
      activityHistoryRequestRef.current?.abort();
      activityStreamRef.current?.close();
      olderRequestRef.current?.abort();
    };
  }, []);


  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        if (window.localStorage.getItem(legacyQueuedMessagesStorageKey)) {
          setQueuePersistenceError("Older queued messages could not be restored safely after account isolation changed.");
        }
      } catch {
        // The v2 queue remains usable when legacy storage cannot be inspected.
      }
      const storedMessages = readLiveQueuedMessages(queuedMessagesStorageKey);
      queuedMessagesRef.current = storedMessages;
      setQueuedMessages(storedMessages);
      setQueuedMessagesLoadedFor(queuedMessagesStorageKey);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [legacyQueuedMessagesStorageKey, queuedMessagesStorageKey]);

  const commitQueuedMessages = useCallback((change: (messages: QueuedMessage[]) => QueuedMessage[]): boolean => {
    const removedIds = readQueuedMessageTombstones(queuedMessagesStorageKey);
    const current = mergeQueuedMessages(
      queuedMessagesRef.current,
      readQueuedMessages(queuedMessagesStorageKey),
    ).filter((message) => !removedIds.has(message.id));
    const next = change(current).filter((message) => !removedIds.has(message.id));
    if (!persistQueuedMessages(queuedMessagesStorageKey, next)) return false;
    queuedMessagesRef.current = next;
    setQueuedMessages(next);
    return true;
  }, [queuedMessagesStorageKey]);

  const removeLocalQueuedMessage = useCallback((id: string): boolean => {
    if (!persistQueuedMessageTombstone(queuedMessagesStorageKey, id)) return false;
    const removed = commitQueuedMessages((messages) => messages.filter((message) => message.id !== id));
    if (!removed) return false;
    blockedQueuedMessageIdsRef.current.delete(id);
    return true;
  }, [commitQueuedMessages, queuedMessagesStorageKey]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea !== window.localStorage) return;
      const tombstonePrefix = queuedMessageTombstonePrefix(queuedMessagesStorageKey);
      if (event.key !== queuedMessagesStorageKey && !event.key?.startsWith(tombstonePrefix)) return;
      const incoming = event.key === queuedMessagesStorageKey ? parseQueuedMessages(event.newValue) : [];
      const removedIds = readQueuedMessageTombstones(queuedMessagesStorageKey);
      const next = mergeQueuedMessages(queuedMessagesRef.current, incoming)
        .filter((message) => !removedIds.has(message.id));
      queuedMessagesRef.current = next;
      persistQueuedMessages(queuedMessagesStorageKey, next);
      setQueuedMessages(next);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [queuedMessagesStorageKey]);

  const conversationQuery = useQuery<ConversationViewModel>({
    queryKey: conversationQueryKey(workspaceId, ally.id),
    enabled: !isAllySuppressed(ally.id) && !isAllyDeleting(ally),
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchInterval: (query) => streamConnected
      ? false
      : query.state.error
      ? ERROR_CONVERSATION_SNAPSHOT_INTERVAL_MS
      : query.state.data?.queue && query.state.data.queue.length > 0
        ? QUEUE_SNAPSHOT_INTERVAL_MS
        : IDLE_CONVERSATION_SNAPSHOT_INTERVAL_MS,
    refetchIntervalInBackground: false,
    queryFn: ({ signal }) =>
      session.runCloudOperation(
        async (operationSignal) => {
          if (isAllySuppressed(ally.id)) throw new Error("Ally conversation is unavailable during deletion");
          const result = await session.client.getAllyConversation(workspaceId, ally.id, { limit: 50, signal: operationSignal });
          if (isAllySuppressed(ally.id)) throw new Error("Ally conversation is unavailable during deletion");
          return result;
        },
        { signal },
      ),
  });
  const conversation = conversationQuery.data;
  const latestConversationMessages = conversation?.messages ?? EMPTY_MESSAGES;
  useEffect(() => { fileManager.observe(latestConversationMessages); }, [fileManager, latestConversationMessages]);
  const latestConversationAssistantReplies = conversation?.assistantReplies ?? EMPTY_ASSISTANT_REPLIES;
  const nextCursor = nextCursorOverride === undefined
    ? conversation?.nextCursor ?? null
    : nextCursorOverride;
  const mergedConversationMessages = mergeConversationMessageCopies(
    olderMessages,
    latestConversationMessages,
    conversation?.queue ?? [],
  );
  const authoritativeConversationMessages = filterAuthoritativeQueueMessages(
    mergedConversationMessages,
    conversation?.queue,
  );
  const conversationQueueMessages = mergeConversationMessageCopies(
    authoritativeConversationMessages,
    sentMessages,
  ).filter((message) => (
    message.sender === "user"
    && isLiveQueuedMessage(message)
    && !deletedMessageIds.has(message.id)
  ));
  const allConversationMessages = mergeConversationMessageCopies(
    authoritativeConversationMessages,
    sentMessages,
  ).filter((message) => !deletedMessageIds.has(message.id) || Boolean(message.deletedAt));
  const activeMessageId = resolveActiveMessageId(
    projection,
    conversationQueueMessages,
    allConversationMessages,
  );
  const activeMessageOrdinal = activeMessageId
    ? allConversationMessages.find((message) => message.id === activeMessageId)?.sequence ?? null
    : null;
  useEffect(() => {
    activeMessageIdRef.current = activeMessageId;
    activeMessageOrdinalRef.current = activeMessageOrdinal;
  }, [activeMessageId, activeMessageOrdinal]);
  useEffect(() => {
    conversationMessagesRef.current = allConversationMessages;
  }, [allConversationMessages]);
  const activePersistedUserMessage = activeMessageId
    ? allConversationMessages.find((message) => message.id === activeMessageId && message.sender === "user")
    : undefined;
  const persistedTurnActive = Boolean(
    activePersistedUserMessage
      && isLiveQueuedMessage(activePersistedUserMessage)
      && (activePersistedUserMessage.queueState !== "unclaimed"
        || projection.activeMessageId === activePersistedUserMessage.id),
  );
  const turnInProgress = activeTurn || persistedTurnActive || streamConnected;
  const conversationId = conversation?.id;

  // Single-flag rollback for refresh-scroll restore: set false to keep follow-latest only.
  const ENABLE_SCROLL_RESTORE = true;
  const SCROLL_ANCHOR_TTL_MS = 3_600_000;
  const scrollAnchorKey = workspaceId && conversationId ? `allies:scroll:${workspaceId}:${conversationId}` : null;
  const restoredScrollRef = useRef<string | null>(null);
  const lastAnchorWriteRef = useRef(0);
  const writeScrollAnchor = useCallback((canvas: HTMLElement) => {
    if (!ENABLE_SCROLL_RESTORE || !scrollAnchorKey) return;
    const now = Date.now();
    if (now - lastAnchorWriteRef.current < 500) return;
    lastAnchorWriteRef.current = now;
    const rows = canvas.querySelectorAll("[data-message-id]");
    let anchored: { messageId: string; sequence: number; offsetPx: number } | null = null;
    for (const row of Array.from(rows)) {
      const el = row as HTMLElement;
      const messageId = el.dataset.messageId ?? "";
      if (el.offsetTop <= canvas.scrollTop + canvas.clientHeight) {
        anchored = { messageId, sequence: Number(el.dataset.sequence ?? 0), offsetPx: canvas.scrollTop - el.offsetTop };
      }
    }
    try {
      window.sessionStorage.setItem(scrollAnchorKey, JSON.stringify({
        atBottom: canvas.scrollHeight - canvas.scrollTop - canvas.clientHeight < 96,
        messageId: anchored?.messageId ?? "",
        sequence: anchored?.sequence ?? 0,
        offsetPx: anchored?.offsetPx ?? 0,
        updatedAt: now,
      }));
    } catch {
      // Private-mode storage may throw; follow-latest remains the fallback.
    }
  }, [scrollAnchorKey]);

  const routineDetailQuery = useQuery<RoutineDiscoveryDetail>({
    queryKey: [...conversationQueryKey(workspaceId, ally.id), "routine-detail", conversationId ?? "none", selectedRoutineId ?? "none"],
    enabled: Boolean(selectedRoutineId && conversationId && !conversationAccessFailure),
    retry: false,
    queryFn: ({ signal }) => {
      const routineId = selectedRoutineId;
      const targetConversationId = conversationId;
      if (!routineId || !targetConversationId) throw new Error("routine detail is unavailable");
      return session.runCloudOperation(
        async (operationSignal) => {
          const detail = await session.client.getRoutine(workspaceId, routineId, operationSignal);
          if (
            detail.mainConversationId !== targetConversationId
            || detail.responsibleAllyId !== ally.id
            || detail.bindingId !== ally.bindingId
          ) {
            throw new Error("routine detail belongs to a different conversation");
          }
          return detail;
        },
        { signal },
      );
    },
  });

  useEffect(() => {
    if (!conversation) return;
    const authoritativeMessages = mergeConversationMessageCopies(
      olderMessages,
      conversation.messages,
      conversation.queue ?? [],
    );
    const deletedIds = authoritativeMessages
      .filter((message) => Boolean(message.deletedAt))
      .map((message) => message.id);
    const authoritativeIds = new Set(authoritativeMessages.map((message) => message.id));
    const receiptTask = authoritativeIds.size > 0
      ? window.setTimeout(() => {
        setSentMessages((current) => {
          const next = current.filter((message) => !authoritativeIds.has(message.id));
          return next.length === current.length ? current : next;
        });
      })
      : null;
    const deletedTask = deletedIds.length > 0
      ? window.setTimeout(() => {
        setDeletedMessageIds((current) => {
          const next = new Set(current);
          for (const id of deletedIds) next.add(id);
          return next.size === current.size ? current : next;
        });
      })
      : null;
    return () => {
      if (receiptTask !== null) window.clearTimeout(receiptTask);
      if (deletedTask !== null) window.clearTimeout(deletedTask);
    };
  }, [conversation, olderMessages]);

  const applyConversationAccessFailure = useCallback((error: unknown): boolean => {
    const failure = classifyConversationAccessError(error);
    if (failure === "recoverable") return false;
    conversationAccessFailureRef.current = failure;
    setConversationAccessFailure(failure);
    activityRequestRef.current?.abort();
    activitySnapshotRequestRef.current?.abort();
    activityHistoryRequestRef.current?.abort();
    activityStreamRef.current?.close();
    olderRequestRef.current?.abort();
    setOlderMessages([]);
    setSentMessages([]);
    setImmediateMessageIds(new Set());
    setProjection(EMPTY_ACTIVITY_PROJECTION);
    setActivityPresentation(EMPTY_ACTIVITY_PRESENTATION);
    setOlderLoadError(null);
    setActivityError(null);
    setActivityHistoryError(null);
    setActivityReplayUnavailable(false);
    setPollBudgetReached(false);
    setActiveTurn(false);
    setAwaitingVisibleResponse(false);
    setPollingSettled(true);
    setStreamConnected(false);
    setRetryingMessageId(null);
    setRetryError(null);
    setSelectedRoutineId(null);
    setRoutineActionState(null);
    if (failure === "session-expired") {
      draftRef.current = "";
      setDraft("");
    }
    return true;
  }, []);

  const queryAccessFailure = conversationQuery.isError
    ? classifyConversationAccessError(conversationQuery.error)
    : null;

  useEffect(() => {
    if (queryAccessFailure && queryAccessFailure !== "recoverable") {
      const task = window.setTimeout(() => {
        queryAccessFailureRef.current = queryAccessFailure;
        applyConversationAccessFailure(conversationQuery.error);
      });
      return () => window.clearTimeout(task);
    }
    if (!conversationQuery.isError && queryAccessFailureRef.current) {
      const previousFailure = queryAccessFailureRef.current;
      const task = window.setTimeout(() => {
        queryAccessFailureRef.current = null;
        conversationAccessFailureRef.current = null;
        setConversationAccessFailure((current) => current === previousFailure ? null : current);
      });
      return () => window.clearTimeout(task);
    }
  }, [applyConversationAccessFailure, conversationQuery.error, conversationQuery.isError, queryAccessFailure]);

  const messages = allConversationMessages.filter((message) => !message.deletedAt);
  const handoffReadyRef = useRef(false);
  const handoffRefreshRef = useRef<{ attempts: number; timer: number | null }>({ attempts: 0, timer: null });
  const handoffMatches = Boolean(
    handoffGreeting
      && handoffReply
      && handoffRouteReady
      && hasOnboardingExchange(messages, handoffGreeting, handoffReply),
  );

  useEffect(() => {
    if (!handoffGreeting || !handoffReply || !handoffMatches || handoffReadyRef.current) return;
    handoffReadyRef.current = true;
    if (handoffRefreshRef.current.timer !== null) window.clearTimeout(handoffRefreshRef.current.timer);
    onHandoffReady?.();
  }, [handoffGreeting, handoffMatches, handoffReply, onHandoffReady]);

  useEffect(() => {
    if (!handoffGreeting || !handoffReply) return;
    handoffReadyRef.current = false;
    const state = handoffRefreshRef.current;
    state.attempts = 0;
    if (state.timer !== null) window.clearTimeout(state.timer);
    let cancelled = false;
    const schedule = () => {
      if (cancelled || handoffReadyRef.current) return;
      if (state.attempts >= 3) {
        onHandoffRetryAvailable?.();
        return;
      }
      state.timer = window.setTimeout(async () => {
        state.timer = null;
        if (cancelled || handoffReadyRef.current) return;
        state.attempts += 1;
        await conversationQuery.refetch().catch(() => undefined);
        schedule();
      }, 2_000);
    };
    schedule();
    return () => {
      cancelled = true;
      if (state.timer !== null) window.clearTimeout(state.timer);
      state.timer = null;
    };
  }, [conversationQuery.refetch, handoffGreeting, handoffReply, handoffRetryToken, onHandoffRetryAvailable]);

  useEffect(() => {
    if (handoffGreeting && handoffReply && conversationQuery.isError && !conversationQuery.data) {
      onHandoffRetryAvailable?.();
    }
  }, [conversationQuery.data, conversationQuery.isError, handoffGreeting, handoffReply, onHandoffRetryAvailable]);

  const assistantReplies = conversation
    ? mergeAssistantReplies(
      conversation.assistantReplies ?? [],
      assistantReplyState.conversationId === conversation.id ? assistantReplyState.replies : [],
    )
    : [];
  const activeUserMessage = turnInProgress || awaitingVisibleResponse
    ? activeMessageId
      ? messages.find((message) => message.id === activeMessageId && message.sender === "user")
      : messages.find((message) => message.sender === "user" && isLiveQueuedMessage(message))
    : undefined;
  const activeProjectedTurn = activeUserMessage
    ? projection.turns.find((turn) => (
      turn.messageId === activeUserMessage.id
      && turn.turnOrdinal === activeUserMessage.sequence
    ))
    : undefined;
  const activeAssistantReply = activeUserMessage
    ? assistantReplies.find((reply) => (
      reply.sourceMessageId === activeUserMessage.id
      && reply.conversationTurnOrdinal === activeUserMessage.sequence
      && reply.hasFullPrefix
    ))
    : undefined;
  const responseStarted = Boolean(activeProjectedTurn?.assistantText.trim())
    || Boolean(activeAssistantReply?.content.trim())
    || Boolean(activeUserMessage && messages.some(
      (message) => message.sender === "assistant"
        && message.sequence > activeUserMessage.sequence
        && !messages.some(
          (candidate) => candidate.sender === "user"
            && candidate.sequence > activeUserMessage.sequence
            && candidate.sequence < message.sequence,
        ),
    ));
  const activeMessageHasProgress = Boolean(activeUserMessage && (
    responseStarted
    || Boolean(activeProjectedTurn && activeProjectedTurn.state !== "queued")
    || projection.pendingActivities?.some((activity) => activity.messageId === activeUserMessage.id)
  ));
  const visibleQueueMessages = conversationQueueMessages.filter((message) => (
    activeMessageOrdinal === null || message.sequence >= activeMessageOrdinal
  ));
  const timelineMessages = messages.filter((message) => (
    !isLiveQueuedMessage(message)
    || Boolean(message.files?.length)
    || Boolean(message.preparation && message.preparation !== "none")
    || immediateMessageIds.has(message.id)
    || message.id === activeMessageId
    || !visibleQueueMessages.some((queued) => queued.id === message.id)
  ));
  const queuedFrameMessages = buildQueuedFrameMessages(
    visibleQueueMessages,
    queuedMessages,
    activeMessageId,
    activeMessageHasProgress,
    messages.some((message) => message.id === activeMessageId),
    (fileTransferId) => {
      const transfer = fileManager.find(fileTransferId);
      if (!transfer) return null;
      return {
        files: transfer.files.map((file) => ({ id: file.id, name: file.name, src: file.src, ready: true, local: true as const })),
        status: localTransferQueueStatus(transfer),
      };
    },
  );
  const waitingForVisibleResponse = awaitingVisibleResponse && !responseStarted;
  const shouldPoll = activeTurn || waitingForVisibleResponse || (!pollingSettled && persistedTurnActive);
  const activityStreamAvailable = Boolean(getWebEnvironment().cloudApiUrl) && getActivitySseEnabled();
  const pollingActive = shouldPoll
    && (streamConnected || !activityStreamAvailable || streamFallback || !activeTurn);
  const activityPollInterval = streamConnected
    ? DURABLE_REPLY_SNAPSHOT_INTERVAL_MS
    : ACTIVITY_INTERVAL_MS;
  const showThinkingState = sending
    || turnInProgress
    || waitingForVisibleResponse
    || messages.some((message) => immediateMessageIds.has(message.id) && isLiveQueuedMessage(message));
  const gettingReady = isGettingReady(ally);

  useEffect(() => {
    if (!activeUserMessage || !turnInProgress) return;
    const durableSuccess = activeAssistantReply?.status === "completed"
      || messages.some((message) => (
        message.sender === "assistant"
        && message.status === "completed"
        && message.sequence > activeUserMessage.sequence
        && !messages.some((candidate) => (
          candidate.sender === "user"
          && candidate.sequence > activeUserMessage.sequence
          && candidate.sequence < message.sequence
        ))
      ));
    if (!durableSuccess) return;
    let current = true;
    queueMicrotask(() => {
      if (!current) return;
      setActiveTurn(false);
      setAwaitingVisibleResponse(false);
      setPollingSettled(true);
    });
    return () => { current = false; };
  }, [activeAssistantReply?.status, activeUserMessage, messages, turnInProgress]);

  useEffect(() => {
    const previousState = previousProvisioningStateRef.current;
    previousProvisioningStateRef.current = ally.provisioningState;
    if (
      (previousState !== "pending" && previousState !== "retryable")
      || ally.provisioningState !== "bound"
    ) return;

    turnGenerationRef.current += 1;
    responseStartedRef.current = false;
    pollCountRef.current = 0;
    setPollBudgetReached(false);
    setPollingSettled(false);
    setActiveTurn(true);
    setAwaitingVisibleResponse(true);
    void queryClient.invalidateQueries({ queryKey: conversationQueryKey(workspaceId, ally.id) });
  }, [ally.id, ally.provisioningState, queryClient, workspaceId]);

  const timelineSignature = [
    timelineMessages.map((message) => `${message.id}:${message.status}`).join("|"),
    projection.turns
      .map((turn) => `${turn.messageId}:${turn.state}:${turn.assistantText.length}`)
      .join("|"),
    assistantReplies
      .map((reply) => `${reply.sourceMessageId}:${reply.status}:${reply.content.length}:${reply.hasFullPrefix}:${reply.isTruncated === true}`)
      .join("|"),
    projection.pendingActivities
      ?.map((activity) => `${activity.id}:${activity.text.length}`)
      .join("|") ?? "",
    (conversation?.routineItems ?? [])
      .map((item) => `${item.kind}:${item.id}:${item.status}:${item.resultInsertion ?? ""}:${item.text?.length ?? 0}`)
      .join("|"),
  ].join("::");
  const routineItems = conversation?.routineItems ?? [];
  const routineActionTargetSignature = routineActionState
    ? buildRoutineActionEvidence(routineActionState, routineItems)
    : null;

  useEffect(() => {
    if (!routineActionState) {
      routineActionEvidenceRef.current = null;
      return;
    }
    if (routineActionEvidenceRef.current === null) {
      routineActionEvidenceRef.current = routineActionTargetSignature;
      return;
    }
    if (routineActionEvidenceRef.current !== routineActionTargetSignature) {
      routineActionEvidenceRef.current = routineActionTargetSignature;
      setRoutineActionState(null);
    }
  }, [routineActionState, routineActionTargetSignature]);

  useEffect(() => {
    if (routineActionState?.status !== "sent") return;
    const key = routineActionState.key;
    const timeout = window.setTimeout(() => {
      setRoutineActionState((current) => current?.key === key ? null : current);
    }, ROUTINE_ACTION_SENT_TIMEOUT_MS);
    return () => window.clearTimeout(timeout);
  }, [routineActionState]);

  const loadOlder = async () => {
    if (conversationAccessFailure || !conversationId || !nextCursor || loadingOlder || !mountedRef.current) return;
    olderRequestRef.current?.abort();
    const controller = new AbortController();
    olderRequestRef.current = controller;
    setLoadingOlder(true);
    setOlderLoadError(null);
    try {
      const page = await session.runCloudOperation((signal) =>
        session.client.getConversation(workspaceId, conversationId, {
          limit: 50,
          cursor: nextCursor,
          signal,
        }), { signal: controller.signal });
      if (controller.signal.aborted || !mountedRef.current) return;
      setOlderMessages((current) => mergeMessages(current, page.messages));
      setAssistantReplyState((current) => mergeAssistantReplyState(
        current,
        conversationId,
        page.assistantReplies ?? EMPTY_ASSISTANT_REPLIES,
      ));
      setNextCursorOverride(page.nextCursor);
      historyRevisionRef.current += 1;
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        if (applyConversationAccessFailure(error)) return;
        setOlderLoadError("We couldn't load earlier messages. Try again.");
      }
    } finally {
      if (olderRequestRef.current === controller) {
        olderRequestRef.current = null;
        if (mountedRef.current) setLoadingOlder(false);
      }
    }
  };

  const preserveLatestConversationWindow = useCallback((
    windowMessages: MessageViewModel[],
    windowReplies: readonly AssistantReplyViewModel[] = EMPTY_ASSISTANT_REPLIES,
  ) => {
    if (windowMessages.length === 0 && windowReplies.length === 0) return;
    if (windowMessages.length > 0) {
      setOlderMessages((current) => mergeMessages(windowMessages, current));
      historyRevisionRef.current += 1;
    }
    if (windowReplies.length > 0 && conversationId) {
      setAssistantReplyState((current) => mergeAssistantReplyState(current, conversationId, windowReplies));
    }
  }, [conversationId]);

  const loadActivityReplay = useCallback(async (
    targetConversationId: string,
    controllerSignal: AbortSignal,
    fromOrigin = false,
  ) => {
    const previous = activityReplayRef.current;
    if (fromOrigin || !previous || previous.conversationId !== targetConversationId) {
      activityReplayRef.current = {
        conversationId: targetConversationId,
        cursor: null,
        afterSequence: 0,
        blocked: null,
      };
      if (previous?.conversationId !== targetConversationId) {
        activityReplayExpiredRestartedRef.current = false;
      }
    }

    const replayState = activityReplayRef.current;
    if (!replayState || replayState.blocked) return null;

    let cursor = replayState.cursor;
    let bytes = 0;
    const seenCursors = new Set<string>();

    for (let page = 0; ; page += 1) {
      if (page >= ACTIVITY_REPLAY_MAX_PAGES) throw new ActivityReplayBoundError();

      const snapshot = await session.runCloudOperation(() =>
        session.client.getActivities(
          workspaceId,
          targetConversationId,
          {
            limit: 200,
            replay: true,
            ...(cursor ? { cursor } : {}),
          },
          controllerSignal,
        ), {
          signal: controllerSignal,
        });
      if (controllerSignal.aborted || !mountedRef.current) return null;

      bytes += activitySnapshotBytes(snapshot);
      if (bytes > ACTIVITY_REPLAY_MAX_BYTES) throw new ActivityReplayBoundError();

      if (hasVisibleAssistantText(
        snapshot,
        snapshot.activeMessageId ?? activeMessageIdRef.current,
        activeMessageOrdinalRef.current,
      )) {
        responseStartedRef.current = true;
        setAwaitingVisibleResponse(false);
      }
      setProjection((current) => projectConversationActivity(current, snapshot, conversationMessagesRef.current));
      presentActivitySnapshot(snapshot);
      const currentState = activityReplayRef.current;
      if (!currentState || currentState.conversationId !== targetConversationId) return null;
      const pageLastSequence = snapshot.activities.reduce(
        (latest, activity) => Math.max(latest, activity.sequence),
        0,
      );
      activityReplayRef.current = {
        ...currentState,
        cursor: snapshot.resumeCursor ?? currentState.cursor,
        afterSequence: Math.max(currentState.afterSequence, pageLastSequence),
      };

      const nextCursor = snapshot.nextCursor ?? null;
      if (!nextCursor) {
        activityReplayExpiredRestartedRef.current = false;
        return snapshot;
      }
      if (nextCursor === cursor || seenCursors.has(nextCursor)) {
        throw new ActivityReplayBoundError();
      }
      seenCursors.add(nextCursor);
      cursor = nextCursor;
    }
  }, [presentActivitySnapshot, session, workspaceId]);

  const loadReplayWithRecovery = useCallback(async (
    targetConversationId: string,
    controllerSignal: AbortSignal,
    fromOrigin = false,
  ) => {
    try {
      return await loadActivityReplay(targetConversationId, controllerSignal, fromOrigin);
    } catch (error) {
      if (
        activityReplayFailure(error) === "expired"
        && !activityReplayExpiredRestartedRef.current
      ) {
        activityReplayExpiredRestartedRef.current = true;
        activityReplayRef.current = {
          conversationId: targetConversationId,
          cursor: null,
          afterSequence: 0,
          blocked: null,
        };
        return loadActivityReplay(targetConversationId, controllerSignal, true);
      }
      throw error;
    }
  }, [loadActivityReplay]);

  const handleActivityReplayFailure = useCallback((error: unknown): boolean => {
    const failure = activityReplayFailure(error);
    if (!failure || failure === "expired") return false;
    const replayState = activityReplayRef.current;
    if (replayState) {
      activityReplayRef.current = {
        ...replayState,
        cursor: null,
        blocked: failure === "gap" || failure === "invalid" ? failure : null,
      };
    }
    setActivityError(null);
    if (failure === "invalid") {
      setActivityReplayUnavailable(true);
      setActivityHistoryError(null);
    } else if (failure === "gap") {
      setActivityReplayUnavailable(false);
      setActivityHistoryError("Some activity history needs repair. Check again.");
    } else {
      setActivityReplayUnavailable(false);
      setActivityHistoryError("Activity history is too large to load safely. Check again.");
    }
    setActiveTurn(false);
    setAwaitingVisibleResponse(false);
    setPollingSettled(true);
    return true;
  }, []);

  const refreshActivitySnapshot = useCallback(async (targetConversationId: string) => {
    if (!mountedRef.current) return;
    activitySnapshotRequestRef.current?.abort();
    const controller = new AbortController();
    activitySnapshotRequestRef.current = controller;
    try {
      const replayState = activityReplayRef.current;
      const snapshot = replayState?.conversationId === targetConversationId
        && replayState.cursor !== null
        && replayState.blocked === null
        ? await loadReplayWithRecovery(targetConversationId, controller.signal)
        : await session.runCloudOperation(() =>
          session.client.getActivities(workspaceId, targetConversationId, 200, controller.signal), {
            signal: controller.signal,
          });
      if (controller.signal.aborted || !mountedRef.current) return;
      if (!snapshot) return;
      if (hasVisibleAssistantText(
        snapshot,
        snapshot.activeMessageId ?? activeMessageIdRef.current,
        activeMessageOrdinalRef.current,
      )) {
        responseStartedRef.current = true;
        setAwaitingVisibleResponse(false);
      }
      setProjection((current) => projectConversationActivity(current, snapshot, conversationMessagesRef.current));
      presentActivitySnapshot(snapshot);
      setActivityError(null);
      setActivityHistoryError(null);
      setActivityReplayUnavailable(false);
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        if (!applyConversationAccessFailure(error) && !handleActivityReplayFailure(error)) {
          setActivityError("We couldn't check the latest response status.");
        }
      }
    } finally {
      if (activitySnapshotRequestRef.current === controller) {
        activitySnapshotRequestRef.current = null;
      }
    }
  }, [applyConversationAccessFailure, handleActivityReplayFailure, loadReplayWithRecovery, presentActivitySnapshot, session, workspaceId]);

  const sendMessageContent = useCallback(async (
    content: string,
    key: string,
    clearSubmittedDraft: boolean,
    queuedMessageId?: string,
    routineRequest?: RoutineActionRequest,
  ): Promise<boolean> => {
    if (conversationAccessFailure || !conversation || !canChat(ally)) return false;
    const activeMessageIdBeforeSend = activeMessageIdRef.current;
    const hadActiveTurnBeforeSend = Boolean(activeMessageIdBeforeSend || turnInProgress);
    const preservedOlderMessages = olderMessages;
    const preservedCursor = nextCursorOverride;
    if (!activeMessageIdBeforeSend && !turnInProgress) {
      turnGenerationRef.current += 1;
      responseStartedRef.current = false;
      activityRequestRef.current?.abort();
    }
    followLatestRef.current = true;
    setSending(true);
    setSendingMessageId(queuedMessageId ?? null);
    setSendError(null);
    setQueuePersistenceError(null);
    try {
      const fileTransferId = queuedMessagesRef.current.find(message => message.id === queuedMessageId)?.fileTransferId;
      if (fileTransferId) await fileManager.restore(fileScope);
      const accepted = fileTransferId ? { conversationId: conversation.id, message: await fileManager.admit(fileTransferId), execution: null, replayed: false } : await session.runCloudOperation(
        (signal) => session.client.sendMessage(workspaceId, conversation.id, content, key, signal, Intl.DateTimeFormat().resolvedOptions().timeZone,
          routineRequest ? buildRoutineActionContext(routineRequest) : undefined),
        { csrf: true },
      );
      if (!accepted?.message) throw { kind: "contract" };
      if (!routineRequest) setRoutineActionState((current) => current?.status === "sent" ? null : current);
      onActivity();
      setSentMessages((current) => mergeMessages(current, [accepted.message]));
      if (queuedMessageId) setImmediateMessageIds((current) => {
        if (!current.has(queuedMessageId)) return current;
        const next = new Set(current);
        next.delete(queuedMessageId);
        next.add(accepted.message.id);
        return next;
      });
      if (queuedMessageId !== undefined) {
        const removed = removeLocalQueuedMessage(queuedMessageId);
        if (removed) {
          blockedQueuedMessageIdsRef.current.delete(queuedMessageId);
          setQueuePersistenceError(null);
        } else {
          blockedQueuedMessageIdsRef.current.add(queuedMessageId);
          setQueuePersistenceError(QUEUED_MESSAGE_REMOVAL_ERROR);
        }
      }
      if (clearSubmittedDraft && draftRef.current.trim() === content) {
        draftRef.current = "";
        setDraft("");
      }
      intentRef.current = null;
      const turnIsActive = accepted.message.status === "queued" || accepted.message.status === "in_progress";
      const acceptedIsActive = activeMessageIdBeforeSend === accepted.message.id
        || (!activeMessageIdBeforeSend && accepted.message.queueState !== "unclaimed");
      if (acceptedIsActive) {
        setProjection((current) => ({
          ...current,
          activeMessageId: accepted.message.id,
          state: activityStateFromMessage(accepted.message.status),
        }));
        setActivityError(null);
        pollCountRef.current = 0;
        setPollBudgetReached(false);
        setPollingSettled(false);
        setActiveTurn(turnIsActive);
        setAwaitingVisibleResponse(turnIsActive || accepted.message.status === "completed");
      }
      if (acceptedIsActive && !turnIsActive) {
        setPollingSettled(true);
        preserveLatestConversationWindow(latestConversationMessages, latestConversationAssistantReplies);
        const preservedHistoryRevision = historyRevisionRef.current;
        await conversationQuery.refetch().catch(() => undefined);
        if (mountedRef.current && historyRevisionRef.current === preservedHistoryRevision) {
          setOlderMessages((current) => mergeMessages(preservedOlderMessages, current));
          if (preservedCursor !== undefined) setNextCursorOverride(preservedCursor);
        }
        await refreshActivitySnapshot(conversation.id);
      }
      return true;
    } catch (error) {
      if (queuedMessageId !== undefined) setImmediateMessageIds((current) => {
        if (!current.has(queuedMessageId)) return current;
        const next = new Set(current);
        next.delete(queuedMessageId);
        return next;
      });
      if (applyConversationAccessFailure(error)) {
        return false;
      }
      if (queuedMessageId !== undefined && !queuedMessagesRef.current.find(message => message.id === queuedMessageId)?.fileTransferId && isDefinitiveMessageRejection(error)) {
        const removed = removeLocalQueuedMessage(queuedMessageId);
        if (removed) {
          blockedQueuedMessageIdsRef.current.delete(queuedMessageId);
          intentRef.current = null;
          setQueuePersistenceError(null);
          const currentDraft = draftRef.current;
          const restoredDraft = !currentDraft.trim() || currentDraft.trim() === content
            ? content
            : `${content}\n\n${currentDraft}`;
          draftRef.current = restoredDraft;
          setDraft(restoredDraft);
        } else {
          blockedQueuedMessageIdsRef.current.add(queuedMessageId);
          setQueuePersistenceError(QUEUED_MESSAGE_REMOVAL_ERROR);
        }
      }
      if (!hadActiveTurnBeforeSend) setAwaitingVisibleResponse(false);
      setSendError(
        isUnknownMessageAcceptance(error)
          ? MESSAGE_ACCEPTANCE_UNKNOWN_ERROR
          : "Your message wasn't accepted. Try the same message again.",
      );
      return false;
    } finally {
      setSending(false);
      setSendingMessageId((current) => current === queuedMessageId ? null : current);
    }
  }, [
    ally,
    applyConversationAccessFailure,
    conversationAccessFailure,
    conversation,
    conversationQuery,
    latestConversationMessages,
    latestConversationAssistantReplies,
    nextCursorOverride,
    onActivity,
    olderMessages,
    preserveLatestConversationWindow,
    refreshActivitySnapshot,
    removeLocalQueuedMessage,
    fileManager,
    fileScope,
    session,
    turnInProgress,
    workspaceId,
  ]);

  const sendRoutineAction = useCallback(async (request: RoutineActionRequest): Promise<boolean> => {
    if (conversationAccessFailure || !conversation || !canChat(ally)) return false;
    const key = buildRoutineActionIdempotencyKey(request);
    if (routineActionState?.key === key) return false;
    routineActionEvidenceRef.current = buildRoutineActionEvidence(request, conversation?.routineItems ?? []);
    setRoutineActionState({
      key,
      routineId: request.routineId,
      action: request.action,
      runId: request.runId,
      approvalRequestId: request.approvalRequestId,
      status: "sending",
    });
    const accepted = await sendMessageContent(buildRoutineActionMessage(request), key, false, undefined, request);
    if (!mountedRef.current) return accepted;
    setRoutineActionState((current) => current?.key === key
      ? accepted ? { ...current, status: "sent" } : null
      : current);
    return accepted;
  }, [
    ally,
    conversation,
    conversationAccessFailure,
    routineActionState?.key,
    sendMessageContent,
  ]);

  const submit = useCallback(async (showImmediately = false) => {
    if (preparingFilesRef.current) return;
    if (conversationAccessFailure || !conversation || !queuedMessagesReady || !canChat(ally)) return;
    const content = draft.trim();
    if (!content && !attachments.files.length) return;
    const signature = `${conversation.id}:${content}`;
    const key = intentRef.current?.signature === signature
      && intentRef.current.draftRevision === draftRevisionRef.current
      ? intentRef.current.key
      : `message-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
    intentRef.current = { signature, key, draftRevision: draftRevisionRef.current };
    const removedIds = readQueuedMessageTombstones(queuedMessagesStorageKey);
    const queuedMessagesSnapshot = mergeQueuedMessages(
      queuedMessagesRef.current,
      readQueuedMessages(queuedMessagesStorageKey),
    ).filter((message) => !removedIds.has(message.id));
    const blockedHead = queuedMessagesSnapshot[0];
    const retryingBlockedHead = blockedHead
      && blockedQueuedMessageIdsRef.current.has(blockedHead.id)
      && blockedHead.content === content
      && (!blockedHead.fileTransferId || fileManager.find(blockedHead.fileTransferId)?.files.map(f => f.id).join() === attachments.files.map(f => f.id).join());
    if (retryingBlockedHead) {
      blockedQueuedMessageIdsRef.current.delete(blockedHead.id);
      const accepted = await sendMessageContent(content, blockedHead.intentKey, true, blockedHead.id);
      if (accepted && blockedHead.fileTransferId) attachments.change([]);
      if (!accepted) blockedQueuedMessageIdsRef.current.add(blockedHead.id);
      return;
    }
    if (queuedMessagesSnapshot.length >= MAX_QUEUED_MESSAGES) {
      setQueuePersistenceError(`You can queue up to ${MAX_QUEUED_MESSAGES} messages. Send or remove one before adding another.`);
      return;
    }
    let fileTransferId: string | undefined;
    if (attachments.files.length) {
      preparingFilesRef.current = true;
      setPreparingFiles(true);
      try {
        const transfer = await fileManager.prepare(fileScope, workspaceId, ally.id, conversation.id, content, attachments.files);
        fileTransferId = transfer.id;
      } catch (error) {
        setSendError(error instanceof Error ? error.message : "Your files could not be saved. Try again.");
        return;
      } finally {
        preparingFilesRef.current = false;
        setPreparingFiles(false);
      }
    }
    const nextMessage = {
      id: `queued-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`,
      content,
      intentKey: key,
      ...(fileTransferId ? { fileTransferId } : {}),
      queuedAt: Math.max(Date.now(), (queuedMessagesSnapshot.at(-1)?.queuedAt ?? 0) + 1),
    };
    if (!commitQueuedMessages((messages) => [...messages, nextMessage])) {
      setQueuePersistenceError(QUEUED_MESSAGE_PERSISTENCE_ERROR);
      return;
    }
    setQueuePersistenceError(null);
    setSendError(
      blockedHead && blockedQueuedMessageIdsRef.current.has(blockedHead.id)
        ? BLOCKED_QUEUE_HEAD_ERROR
        : null,
    );
    if (showImmediately && !turnInProgress && queuedMessagesSnapshot.length === 0) {
      setImmediateMessageIds((current) => new Set([...current, nextMessage.id]));
    }
    draftRef.current = "";
    setDraft("");
    attachments.change([]);
    intentRef.current = null;
  }, [conversationAccessFailure, conversation, queuedMessagesReady, ally, draft, attachments, queuedMessagesStorageKey, sendMessageContent, fileManager, fileScope, workspaceId, commitQueuedMessages, turnInProgress]);

  useEffect(() => {
    const removedIds = readQueuedMessageTombstones(queuedMessagesStorageKey);
    const liveMessages = mergeQueuedMessages(
      queuedMessagesRef.current,
      readQueuedMessages(queuedMessagesStorageKey),
    ).filter((message) => !removedIds.has(message.id));
    const nextMessage = liveMessages.find((message) => !blockedQueuedMessageIdsRef.current.has(message.id));
    if (
      (liveMessages[0]?.fileTransferId && blockedQueuedMessageIdsRef.current.has(liveMessages[0].id))
      ||
      !nextMessage
      || !queuedMessagesReady
      || sending
      || queuedDispatchRef.current
      || conversationAccessFailure
      || !conversation
      || !canChat(ally)
    ) return;

    queuedDispatchRef.current = true;
    intentRef.current = {
      signature: `${conversation.id}:${nextMessage.content}`,
      key: nextMessage.intentKey,
      draftRevision: draftRevisionRef.current,
    };
    void withQueueMessageLock(queuedMessagesStorageKey, nextMessage.id, async () => {
      if (!markQueuedMessageAttempt(queuedMessagesStorageKey, nextMessage.id, commitQueuedMessages)) return false;
      return sendMessageContent(nextMessage.content, nextMessage.intentKey, false, nextMessage.id);
    })
      .then((accepted) => {
        if (accepted || conversationAccessFailureRef.current) return;
        if (!queuedMessagesRef.current.some((message) => message.id === nextMessage.id)) return;
        blockedQueuedMessageIdsRef.current.add(nextMessage.id);
        if (!mountedRef.current) return;
        if (nextMessage.fileTransferId) {
          const transfer = fileManager.find(nextMessage.fileTransferId);
          if (transfer && !(fileManager.drafts.get(fileScope)?.length)) changeAttachments(transfer.files);
        }
        const currentDraft = draftRef.current;
        if (!currentDraft.trim()) {
          draftRef.current = nextMessage.content;
          setDraft(nextMessage.content);
        }
      })
      .finally(() => {
        queuedDispatchRef.current = false;
      });
  }, [
    ally,
    conversationAccessFailure,
    conversation,
    queuedMessages,
    queuedMessagesLoadedFor,
    queuedMessagesReady,
    queuedMessagesStorageKey,
    commitQueuedMessages,
    sendMessageContent,
    sending,
    fileManager,
    fileScope,
    changeAttachments,
  ]);

  const retry = async (message: MessageViewModel) => {
    if (conversationAccessFailure || !conversation || retryingMessageId || !message.retryable) return;
    const key = `message-retry-${message.id}-${message.sequence}`;
    setRetryingMessageId(message.id);
    setRetryError(null);
    turnGenerationRef.current += 1;
    responseStartedRef.current = false;
    activityRequestRef.current?.abort();
    followLatestRef.current = true;
    try {
      const accepted = await session.runCloudOperation(
        (signal) => session.client.retryMessage(workspaceId, conversation.id, message.id, key, signal),
        { csrf: true },
      );
      setSentMessages((current) => mergeMessages(current, [accepted.message]));
      setRetriedMessageIds((current) => new Set(current).add(message.id));
      setProjection((current) => ({ ...current, state: activityStateFromMessage(accepted.message.status) }));
      setPollingSettled(false);
      setPollBudgetReached(false);
      const turnIsActive = accepted.message.status === "queued" || accepted.message.status === "in_progress";
      setActiveTurn(turnIsActive);
      setAwaitingVisibleResponse(turnIsActive || accepted.message.status === "completed");
      pollCountRef.current = 0;
    } catch (error) {
      if (applyConversationAccessFailure(error)) return;
      setAwaitingVisibleResponse(false);
      setRetryError("We couldn't retry that message. Try again in a moment.");
    } finally {
      setRetryingMessageId(null);
    }
  };

  const checkActivity = useCallback(async () => {
    if (
      conversationAccessFailure
      || !shouldPoll
      || !conversationId
      || pollingRef.current
      || document.visibilityState !== "visible"
      || !mountedRef.current
    ) return;
    const companionSnapshot = streamConnected;
    // While connected, the snapshot is only a stall watchdog: skip it while events keep arriving.
    if (
      companionSnapshot
      && Date.now() - lastStreamEventAtRef.current < DURABLE_REPLY_SNAPSHOT_INTERVAL_MS
    ) return;
    if (pollCountRef.current >= ACTIVITY_POLL_LIMIT) {
      // A live stream is still the source of truth, so only a polling fallback gives up.
      if (companionSnapshot) return;
      if (!pollBudgetReached) setPollBudgetReached(true);
      setActiveTurn(false);
      setAwaitingVisibleResponse(false);
      setPollingSettled(true);
      return;
    }
    activityRequestRef.current?.abort();
    const controller = new AbortController();
    activityRequestRef.current = controller;
    pollingRef.current = true;
    pollCountRef.current += 1;
    try {
      const replayState = activityReplayRef.current;
      const snapshot = companionSnapshot
        ? await session.runCloudOperation(() =>
          session.client.getActivities(workspaceId, conversationId, 200, controller.signal), {
            signal: controller.signal,
          })
        : replayState?.conversationId === conversationId
          && replayState.cursor !== null
          && replayState.blocked === null
          ? await loadReplayWithRecovery(conversationId, controller.signal)
          : await session.runCloudOperation(() =>
          session.client.getActivities(workspaceId, conversationId, 200, controller.signal), {
            signal: controller.signal,
          });
      if (controller.signal.aborted || !mountedRef.current) return;
      if (!snapshot) return;
      const progress = polledProgressRef.current;
      if (progress?.conversationId !== conversationId || snapshot.lastContiguousSequence > progress.sequence) {
        if (progress?.conversationId === conversationId) pollCountRef.current = 0;
        polledProgressRef.current = { conversationId, sequence: snapshot.lastContiguousSequence };
      }
      const currentActiveMessageId = activeMessageIdRef.current;
      const snapshotOwnsActiveMessage = snapshotCanOwnActiveMessage(
        currentActiveMessageId,
        activeMessageOrdinalRef.current,
        snapshot,
        conversationMessagesRef.current,
      );
      if (snapshotOwnsActiveMessage && hasVisibleAssistantText(
        snapshot,
        snapshot.activeMessageId ?? currentActiveMessageId,
        snapshotMessageOrdinal(snapshot, conversationMessagesRef.current) ?? activeMessageOrdinalRef.current,
      )) {
        responseStartedRef.current = true;
        setAwaitingVisibleResponse(false);
      }
      setProjection((current) => projectConversationActivity(current, snapshot, conversationMessagesRef.current));
      presentActivitySnapshot(snapshot);
      setActivityError(null);
      setActivityHistoryError(null);
      setActivityReplayUnavailable(false);
      if (snapshotOwnsActiveMessage && isActivityTerminal(snapshot.state)) {
        setActiveTurn(false);
        setAwaitingVisibleResponse(
          snapshot.state === "completed" && !responseStartedRef.current,
        );
        setPollingSettled(true);
        if (controller.signal.aborted || !mountedRef.current) return;
        preserveLatestConversationWindow(latestConversationMessages, latestConversationAssistantReplies);
        await queryClient.invalidateQueries({
          queryKey: conversationQueryKey(workspaceId, ally.id),
        });
      }
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        const accessFailure = applyConversationAccessFailure(error);
        const replayFailure = !accessFailure && !companionSnapshot
          ? handleActivityReplayFailure(error)
          : false;
        if (!accessFailure && !replayFailure) {
          setActivityError("We couldn't check the latest response status.");
          if (!companionSnapshot) {
            setActiveTurn(false);
            setAwaitingVisibleResponse(false);
            setPollingSettled(true);
          }
        }
      }
    } finally {
      if (activityRequestRef.current === controller) {
        activityRequestRef.current = null;
        pollingRef.current = false;
      }
    }
  }, [
    ally.id,
    applyConversationAccessFailure,
    conversationAccessFailure,
    conversationId,
    handleActivityReplayFailure,
    latestConversationMessages,
    latestConversationAssistantReplies,
    loadReplayWithRecovery,
    presentActivitySnapshot,
    preserveLatestConversationWindow,
    queryClient,
    session,
    pollBudgetReached,
    shouldPoll,
    streamConnected,
    workspaceId,
  ]);

  useEffect(() => {
    if (conversationAccessFailure || !conversationId || activityHistoryLoadedRef.current === conversationId) return;
    activityHistoryLoadedRef.current = conversationId;
    const generationAtStart = turnGenerationRef.current;
    const controller = new AbortController();
    activityHistoryRequestRef.current = controller;
    activityReplayExpiredRestartedRef.current = false;
    setActivityHistoryError(null);
    setActivityReplayUnavailable(false);
    void loadReplayWithRecovery(conversationId, controller.signal, true)
      .then((snapshot) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        if (!snapshot) return;
        setProjection((current) => projectConversationActivity(current, snapshot, conversationMessagesRef.current));
        setActivityHistoryError(null);
        setActivityError(null);
        setActivityReplayUnavailable(false);
        if (
          isActivityTerminal(snapshot.state)
          && turnGenerationRef.current === generationAtStart
        ) {
          setActiveTurn(false);
          setPollingSettled(true);
          void queryClient.invalidateQueries({ queryKey: conversationQueryKey(workspaceId, ally.id) });
        }
      })
      .catch((error) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        if (applyConversationAccessFailure(error) || handleActivityReplayFailure(error)) return;
        if (activityHistoryLoadedRef.current === conversationId) {
          activityHistoryLoadedRef.current = null;
        }
        setActivityHistoryError("We couldn't check the latest response status.");
      });
    return () => {
      if (activityHistoryLoadedRef.current === conversationId) {
        activityHistoryLoadedRef.current = null;
      }
      controller.abort();
      if (activityHistoryRequestRef.current === controller) {
        activityHistoryRequestRef.current = null;
      }
    };
  }, [
    activityHistoryRetry,
    ally.id,
    applyConversationAccessFailure,
    conversationAccessFailure,
    conversationId,
    handleActivityReplayFailure,
    loadReplayWithRecovery,
    queryClient,
    workspaceId,
  ]);

  const retryActivityHistory = () => {
    activityHistoryLoadedRef.current = null;
    activityReplayRef.current = conversationId
      ? { conversationId, cursor: null, afterSequence: 0, blocked: null }
      : null;
    activityReplayExpiredRestartedRef.current = false;
    setActivityReplayUnavailable(false);
    setActivityHistoryError(null);
    setActivityHistoryRetry((current) => current + 1);
  };

  useEffect(() => {
    if (conversationAccessFailure || !conversationId || !activeTurn) {
      activityStreamRef.current?.close();
      activityStreamRef.current = null;
      return;
    }
    const baseUrl = getWebEnvironment().cloudApiUrl;
    if (!baseUrl || !getActivitySseEnabled()) return;
    const controller = new AbortController();
    const targetConversationId = conversationId;
    const generationAtOpen = turnGenerationRef.current;
    let streamEndedNormally = false;
    let fallbackStarted = false;
    let reconnectTimer: number | undefined;
    const startPollingFallback = () => {
      if (fallbackStarted) return;
      fallbackStarted = true;
      setStreamConnected(false);
      pollCountRef.current = 0;
      setPollBudgetReached(false);
      // The stream resumes from its cursor, so reconnecting loses nothing; poll only as a last resort.
      if (streamRetryCountRef.current < STREAM_RECONNECT_MAX_ATTEMPTS) {
        const delay = STREAM_RECONNECT_BASE_MS * 2 ** streamRetryCountRef.current;
        streamRetryCountRef.current += 1;
        reconnectTimer = window.setTimeout(() => {
          if (mountedRef.current) setStreamRetry((current) => current + 1);
        }, delay);
        return;
      }
      setStreamFallback(true);
    };
    const stream = readActivityStream({
      baseUrl,
      workspaceId,
      conversationId: targetConversationId,
      cursor: activityReplayRef.current?.conversationId === targetConversationId
        ? activityReplayRef.current.cursor
        : null,
      signal: controller.signal,
      onOpen: () => {
        if (!mountedRef.current) return;
        streamRetryCountRef.current = 0;
        setStreamFallback(false);
        setStreamConnected(true);
        setActivityError(null);
        activityRequestRef.current?.abort();
      },
      onEvent: (event) => {
        if (!mountedRef.current) return;
        lastStreamEventAtRef.current = Date.now();
        pollCountRef.current = 0;
        if ("conversationId" in event && event.conversationId !== targetConversationId) {
          controller.abort();
          startPollingFallback();
          return;
        }
        if (event.type === "activity") {
          setActivityApprovals((current) => mergeActivityApprovals(
            current,
            targetConversationId,
            [event.activity],
          ));
          const currentActiveMessageId = activeMessageIdRef.current;
          const currentActiveMessageOrdinal = activeMessageOrdinalRef.current;
          const eventIsActive = (!currentActiveMessageId || event.activity.messageId === currentActiveMessageId)
            && (currentActiveMessageOrdinal === null
              || event.activity.conversationTurnOrdinal === currentActiveMessageOrdinal);
          if (eventIsActive && event.activity.kind === "assistant_delta" && event.activity.text.trim()) {
            responseStartedRef.current = true;
            setAwaitingVisibleResponse(false);
          }
          const streamSnapshot = {
            conversationId: targetConversationId,
            activities: [event.activity],
            lastContiguousSequence: event.activity.sequence,
            lastContiguousActivitySequence: event.activity.sequence,
            resumeCursor: event.cursor,
            nextCursor: null,
            latestSequence: event.activity.sequence,
          };
          // The stream never resends an event, so out-of-scope ones must still fill the sequence.
          setProjection((current) => eventIsActive
            ? projectConversationActivity(current, {
              ...streamSnapshot,
              activeMessageId: currentActiveMessageId ?? event.activity.messageId,
              state: event.activity.state,
            }, conversationMessagesRef.current)
            : projectActivitySnapshot(current, {
              ...streamSnapshot,
              activeMessageId: current.activeMessageId,
              state: current.state,
            }));
          presentActivity(targetConversationId, event.activity);
          const replayState = activityReplayRef.current;
          if (replayState?.conversationId === targetConversationId) {
            activityReplayRef.current = {
              ...replayState,
              cursor: event.cursor,
              afterSequence: Math.max(replayState.afterSequence, event.activity.sequence),
            };
          }
        } else if (event.type === "terminal") {
          if (turnGenerationRef.current !== generationAtOpen) {
            streamEndedNormally = true;
            setStreamConnected(false);
            controller.abort();
            return;
          }
          streamEndedNormally = true;
          setStreamConnected(false);
          setProjection((current) => ({ ...current, state: event.state }));
          setActiveTurn(false);
          setAwaitingVisibleResponse(
            event.state === "completed" && !responseStartedRef.current,
          );
          setPollingSettled(true);
          setActivityError(null);
          preserveLatestConversationWindow(latestConversationMessages, latestConversationAssistantReplies);
          void queryClient.invalidateQueries({ queryKey: conversationQueryKey(workspaceId, ally.id) });
        }
      },
      onError: (error) => {
        if (!mountedRef.current || streamEndedNormally) return;
        if (error.status === 401 || error.status === 403 || error.status === 404) {
          setStreamConnected(false);
          applyConversationAccessFailure({
            kind: error.status === 401 ? "unauthorized" : error.status === 403 ? "forbidden" : "not-found",
            status: error.status,
          });
          return;
        }
        startPollingFallback();
      },
    });
    activityStreamRef.current = stream;
    return () => {
      window.clearTimeout(reconnectTimer);
      controller.abort();
      stream.close();
      if (activityStreamRef.current === stream) activityStreamRef.current = null;
      setStreamConnected(false);
    };
  }, [
    activeTurn,
    applyConversationAccessFailure,
    conversationAccessFailure,
    ally.id,
    conversationId,
    latestConversationMessages,
    latestConversationAssistantReplies,
    preserveLatestConversationWindow,
    queryClient,
    presentActivity,
    streamRetry,
    workspaceId,
  ]);

  useEffect(() => {
    if (!pollingActive) {
      activityRequestRef.current?.abort();
      return;
    }
    const interval = window.setInterval(() => void checkActivity(), activityPollInterval);
    return () => {
      window.clearInterval(interval);
      activityRequestRef.current?.abort();
    };
  }, [activityPollInterval, checkActivity, pollingActive]);

  useEffect(() => {
    if (!followLatestRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const canvas = messageCanvasRef.current;
      if (typeof canvas?.scrollTo === "function") {
        // Instant pin: successive smooth scrolls interrupt each other mid-stream and never reach bottom.
        canvas.scrollTo({ top: canvas.scrollHeight, behavior: "auto" });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [timelineSignature]);

  useEffect(() => {
    const canvas = messageCanvasRef.current;
    const content = canvas?.firstElementChild;
    if (!canvas || !content || typeof ResizeObserver === "undefined") return;
    // Late layout (activity groups, markdown, media, fonts) must not push a pinned conversation around.
    const observer = new ResizeObserver(() => {
      const restorePending = ENABLE_SCROLL_RESTORE && scrollAnchorKey && restoredScrollRef.current !== scrollAnchorKey;
      if (followLatestRef.current && !restorePending) canvas.scrollTop = canvas.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [ENABLE_SCROLL_RESTORE, conversationId, scrollAnchorKey]);

  useEffect(() => {
    if (!ENABLE_SCROLL_RESTORE || !scrollAnchorKey || !conversationQuery.isSuccess) return;
    if (restoredScrollRef.current === scrollAnchorKey) return;
    const frame = window.requestAnimationFrame(() => {
      const canvas = messageCanvasRef.current;
      if (!canvas) return;
      const scrollTo = (top: number) => {
        if (typeof canvas.scrollTo === "function") canvas.scrollTo({ top });
        else canvas.scrollTop = top;
      };
      const atBottom = () => {
        scrollTo(canvas.scrollHeight);
        restoredScrollRef.current = scrollAnchorKey;
      };
      let raw: string | null = null;
      try {
        raw = window.sessionStorage.getItem(scrollAnchorKey);
      } catch {
        raw = null;
      }
      if (!raw) {
        atBottom();
        return;
      }
      let anchor: { atBottom: boolean; messageId: string; sequence: number; offsetPx: number; updatedAt: number } | null = null;
      try {
        anchor = JSON.parse(raw);
      } catch {
        anchor = null;
      }
      if (!anchor || Date.now() - anchor.updatedAt > SCROLL_ANCHOR_TTL_MS || anchor.atBottom) {
        atBottom();
        return;
      }
      const el = anchor.messageId ? canvas.querySelector(`[data-message-id="${anchor.messageId}"]`) : null;
      if (el instanceof HTMLElement) {
        scrollTo(Math.min(Math.max(el.offsetTop + anchor.offsetPx, 0), canvas.scrollHeight));
        restoredScrollRef.current = scrollAnchorKey;
      } else if (timelineMessages.length === 0) {
        return;
      } else if (anchor.sequence < (timelineMessages[0]?.sequence ?? 0)) {
        scrollTo(0);
        restoredScrollRef.current = scrollAnchorKey;
      } else {
        atBottom();
        return;
      }
      followLatestRef.current = canvas.scrollHeight - canvas.scrollTop - canvas.clientHeight < 96;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [ENABLE_SCROLL_RESTORE, SCROLL_ANCHOR_TTL_MS, scrollAnchorKey, conversationQuery.isSuccess, timelineMessages]);

  const unavailableNotice = provisioningNotice(ally);
  const resolvedAppearanceValue = resolveAllyAppearance(ally);
  const allyAccent = resolvedAppearanceValue?.color ?? "#ff5800";
  const resolvedAppearance = resolvedAppearanceValue ?? { shape: "ghosty" as AllyShape, color: allyAccent };
  const conversationLoadError = conversationQuery.isError
    && !conversationQuery.data
    && queryAccessFailure === "recoverable"
    ? "We couldn't open this conversation."
    : null;
  const effectiveConversationAccessFailure = conversationAccessFailure
    ?? (queryAccessFailure && queryAccessFailure !== "recoverable" ? queryAccessFailure : null);
  const scopedActivityPresentation = activityPresentation.conversationId === (conversationId ?? null)
    ? activityPresentation
    : EMPTY_ACTIVITY_PRESENTATION;
  const scopedActivityApprovals = activityApprovals.conversationId === (conversationId ?? null)
    ? selectActivityApprovals(activityApprovals)
    : [];
  const baseFrameModel = buildProductionConversationFrameModel({
    ally,
    resolvedAppearance,
    appearanceAvailable: Boolean(resolvedAppearanceValue),
    messages: timelineMessages,
    assistantReplies,
    projection,
    activityPresentation: scopedActivityPresentation,
    queuedMessages: queuedFrameMessages,
    queuedMessagesReady,
    activeMessageId,
    activeMessageHasProgress,
    draft,
    conversationAvailable: Boolean(conversation),
    isLoading: conversationQuery.isPending,
    loadError: conversationLoadError,
    accessFailure: effectiveConversationAccessFailure,
    olderMessagesAvailable: Boolean(nextCursor),
    loadingOlder,
    olderLoadError,
    workspaceRefreshError,
    activityError,
    activityHistoryError,
    activityReplayUnavailable,
    pollBudgetReached,
    retryError,
    sendError: queuePersistenceError ?? sendError,
    unavailableNotice,
    sending,
    retryingMessageId,
    showThinkingState,
    responseStarted,
    gettingReady,
    streaming: shouldPoll || streamConnected,
    responsePresentationMode,
    retriedMessageIds,
    routineItems: conversation?.routineItems ?? [],
    routineDetail: {
      routineId: selectedRoutineId,
      detail: routineDetailQuery.data ?? null,
      loading: Boolean(selectedRoutineId && routineDetailQuery.isPending && !routineDetailQuery.isError),
      error: routineDetailQuery.isError ? "We couldn't load this routine's details." : null,
    },
    routineAction: routineActionState,
  });
  const removeQueuedMessage = async (id: string) => {
    const localMessage = queuedMessagesRef.current.find((message) => message.id === id);
    if (localMessage?.fileTransferId) {
      try {
        await fileManager.restore(fileScope);
        const recovered = await fileManager.cancel(localMessage.fileTransferId);
        if (!removeLocalQueuedMessage(id)) throw new Error(QUEUED_MESSAGE_REMOVAL_ERROR);
        blockedQueuedMessageIdsRef.current.delete(id);
        attachments.change([...recovered.files, ...(fileManager.drafts.get(fileScope) ?? [])]);
        restoreFileText(recovered.content);
      } catch { setQueuePersistenceError("Cancellation could not be confirmed. Your file draft is still saved."); }
      return;
    }
    const cloudMessage = conversationQueueMessages.find((message) => message.id === id);
    if (cloudMessage) {
      if (!isCloudQueueMessageRemovable(cloudMessage) || !conversation) return;
      const hasAttachments = Boolean(cloudMessage.files?.length
        || (cloudMessage.preparation && cloudMessage.preparation !== "none" && cloudMessage.preparation !== "ready"));
      await withQueueMessageLock(queuedMessagesStorageKey, id, async () => {
        try {
          let cancelledDraft: { content: string; files: { id: string; name: string }[] } | null = null;
          if (hasAttachments) {
            const liveRecord = fileManager.snapshot().find((record) => (
              record.reservation?.message.id === id && record.phase !== "ready" && record.phase !== "cancelled"
            ));
            if (liveRecord) {
              try {
                await fileManager.restore(fileScope);
                await fileManager.cancel(liveRecord.id);
              } catch {
                // The server cancel below still governs; a stuck local upload must not block removal.
              }
            }
            const result = await session.runCloudOperation(
              (signal) => session.client.files.cancel(
                workspaceId,
                conversation.id,
                id,
                cloudMessage.revision ?? 0,
                signal,
              ),
              { csrf: true },
            );
            cancelledDraft = result.draft;
          }
          const tombstone = await session.runCloudOperation(
            (signal) => session.client.deleteQueuedMessage(workspaceId, conversation.id, id, signal),
            { csrf: true },
          );
          if (!tombstone.deletedAt) throw { kind: "contract" };
          if (cancelledDraft) {
            restoreFileText(cancelledDraft.content);
            attachments.change([
              ...cancelledDraft.files.map((f) => ({
                id: crypto.randomUUID(),
                name: f.name,
                size: cloudMessage.files?.find((r) => r.id === f.id)?.size ?? 0,
              })),
              ...(fileManager.drafts.get(fileScope) ?? []),
            ]);
          }
          setDeletedMessageIds((current) => {
            if (current.has(tombstone.id)) return current;
            return new Set(current).add(tombstone.id);
          });
          setSentMessages((current) => mergeMessages(current, [tombstone]));
          setQueuePersistenceError(null);
          await queryClient.invalidateQueries({ queryKey: conversationQueryKey(workspaceId, ally.id) });
        } catch (error) {
          if (applyConversationAccessFailure(error)) return;
          setQueuePersistenceError(QUEUED_MESSAGE_REMOVAL_ERROR);
        }
      });
      return;
    }
    if (!localMessage) return;
    if (!supportsQueueMessageLocks()) return;
    const localRemoval = await withQueueMessageLock(queuedMessagesStorageKey, id, async () => {
      const persisted = readQueuedMessages(queuedMessagesStorageKey)
        .find((message) => message.id === id);
      if (!persisted) return "failed" as const;
      if (persisted.attemptedAt !== undefined) {
        return "attempted" as const;
      }
      return removeLocalQueuedMessage(id) ? "removed" as const : "failed" as const;
    });
    if (localRemoval === "removed") {
      setQueuePersistenceError(null);
    } else {
      setQueuePersistenceError(QUEUED_MESSAGE_REMOVAL_ERROR);
    }
  };
  const fileMessageIds = new Set(timelineMessages.filter(message => message.files?.length || message.preparation && message.preparation !== "none").map(message => message.id));
  const queuedAttachmentIds = queuedAttachmentQueueIds(timelineMessages, activeMessageId);
  const visibleFrameMessages = baseFrameModel.messages.map((message) => immediateMessageIds.has(message.id) || (fileMessageIds.has(message.id) && !queuedAttachmentIds.has(message.id))
    ? { ...message, queued: false, ...(message.queued && fileMessageIds.has(message.id) && !queuedAttachmentIds.has(message.id) && !message.statusLabel ? { statusLabel: "Queued" } : {}) } : message);
  const lastSequence = Math.max(0, ...visibleFrameMessages.map((message) => message.sequence));
  const immediateFrameMessages = queuedMessages.filter((message) => !baseFrameModel.timeline.accessCopy && immediateMessageIds.has(message.id)).map((message, index) => ({
    id: message.id,
    sender: "user" as const,
    content: message.content,
    sequence: lastSequence + index + 1,
    createdAt: new Date(message.queuedAt).toISOString(),
    statusLabel: sendingMessageId === message.id ? null : "Not confirmed",
    retryable: false,
    queued: false,
  }));
  const frameModel = {
    ...baseFrameModel,
    composer: { ...baseFrameModel.composer, disabled: baseFrameModel.composer.disabled || preparingFiles },
    messages: [...visibleFrameMessages, ...immediateFrameMessages],
    queuedMessages: baseFrameModel.queuedMessages.filter((message) => !immediateMessageIds.has(message.id) && !(fileMessageIds.has(message.id) && !queuedAttachmentIds.has(message.id))),
  };
  const frameActions: ProductionConversationFrameActions = {
    onDraftChange: (value) => {
      const beganInteracting = !draftRef.current.trim() && Boolean(value.trim());
      draftRevisionRef.current += 1;
      draftRef.current = value;
      setDraft(value);
      if (beganInteracting) onActivity();
      observeEdit(value);
    },
    onCompositionStart: compositionStart,
    onCompositionEnd: compositionEnd,
    onSubmit: (showImmediately) => void submit(showImmediately),
    onRetryMessage: (messageId) => {
      const message = timelineMessages.find((candidate) => candidate.id === messageId);
      if (message) void retry(message);
    },
    onLoadOlder: () => void loadOlder(),
    onRetryConversation: () => void conversationQuery.refetch(),
    onRetryWorkspace,
    onRemoveQueuedMessage: (id) => void removeQueuedMessage(id),
    onCheckAgain: () => {
      pollCountRef.current = 0;
      setPollBudgetReached(false);
      setActivityError(null);
      setPollingSettled(false);
      setActiveTurn(true);
    },
    onRetryActivityHistory: retryActivityHistory,
    onOpenRoutine: (routineId) => {
      if ((conversation?.routineItems ?? []).some((item) => item.routineId === routineId)) {
        setSelectedRoutineId(routineId);
      }
    },
    onCloseRoutine: () => {
      setSelectedRoutineId(null);
      onRoutineOpenRequestHandled();
    },
    onRetryRoutineDetail: () => void routineDetailQuery.refetch(),
    onRoutineAction: sendRoutineAction,
    onScroll: (event) => {
      const canvas = event.currentTarget;
      followLatestRef.current = canvas.scrollHeight - canvas.scrollTop - canvas.clientHeight < 96;
      writeScrollAnchor(canvas);
    },
  };

  const restoreFileText = (content: string) => { const combined = [content, draftRef.current].filter(Boolean).join("\n\n"); draftRef.current = combined; setDraft(combined); void conversationQuery.refetch(); };
  const frame = <><ConversationFrame settingsHref={`/allies/${encodeURIComponent(ally.id)}/settings`} stateReady={stateReady} sleeping={sleeping} runtimeIntentStatus={runtimeIntentStatus} model={frameModel} actions={frameActions} onOpenSettings={onOpenSettings} canvasRef={messageCanvasRef}
    fileRecovery={attachments.cancelled.map(record => <div className={attachmentStyles.savedDraft} key={record.id} role="group" aria-label="Saved cancelled file message"><span>Saved cancelled message · {record.files.length} files</span><button type="button" onClick={() => { attachments.restoreDraft(record); restoreFileText(record.content); }}>Restore draft</button><button type="button" onClick={() => attachments.discard(record.id)}>Discard saved copy</button></div>)}
    attachments={attachments.tray} onAttach={preparingFiles ? undefined : attachments.open}
    onFilesDrop={preparingFiles ? undefined : attachments.addFiles}
    onFileOpen={attachments.openFile}
    publications={id => attachments.publications(id, assistantReplies.filter(reply => reply.sourceMessageId === id).flatMap(reply => reply.publications ?? []))}
    onQueueAttachmentOpen={(file) => attachments.openFile(file.id)}
    messageAttachments={id => {
      const message = timelineMessages.find(message => message.id === id);
      const local = queuedMessages.find(message => message.id === id);
      return message
        ? attachments.render(message, restoreFileText, conversationId ?? "", (messageId) => void removeQueuedMessage(messageId))
        : local?.fileTransferId ? attachments.pending(local.fileTransferId) : null;
    }}
  />{attachments.overlays(allyAccent)}</>;
  return <ConversationApprovals
    client={approvalClient}
    workspaceId={workspaceId}
    conversationId={conversationId ?? ""}
    allyName={ally.name}
    accent={allyAccent}
    canApprove={canApprove}
    enabled={Boolean(conversationId && !conversationAccessFailure)}
    activityApprovals={scopedActivityApprovals}
    liveUpdatesConnected={streamConnected}
  >
    {frame}
    <SafeInputLayer workspaceId={workspaceId} allyId={ally.id} allyName={ally.name} accent={allyAccent} shape={resolvedAppearance.shape} />
  </ConversationApprovals>;
}

function HomeStatus({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <main className={styles.statusPage}>
      <span className={styles.statusAlly} aria-hidden="true" />
      <h1>{title}</h1>
      <p>{detail}</p>
      {action ? <button type="button" onClick={action.onClick}>{action.label}</button> : null}
    </main>
  );
}

function WorkspaceRefreshError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className={styles.inlineError} role="alert">
      <span>We couldn&apos;t refresh your Allies. Your current workspace is still shown.</span>
      <button type="button" onClick={onRetry}>Try again</button>
    </div>
  );
}

function EmptyThread({
  title,
  detail,
  action,
}: {
  title?: string;
  detail?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className={styles.emptyThread} data-testid="empty-thread">
      {title || detail || action ? (
        <>
          <div className={styles.emptyAlly} aria-hidden="true">
            <AllyAvatar shape="ghosty" color="#ff5800" size={92} label="" />
          </div>
          {title ? <h1>{title}</h1> : null}
          {detail ? <p>{detail}</p> : null}
          {action ? <div className={styles.emptyAction}>{action}</div> : null}
        </>
      ) : null}
    </div>
  );
}

function AllyDeletionStatusPane({
  ally,
  onRefresh,
}: {
  ally: AllyViewModel;
  onRefresh: () => Promise<AllyDeletionViewModel>;
}) {
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const state = allyDeletionState(ally);
  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setError(null);
    try {
      await onRefresh();
    } catch {
      setError("We couldn't check deletion yet. Try again when you're online.");
    } finally {
      setRefreshing(false);
    }
  };
  return (
    <div className={styles.emptyThread} data-testid="ally-deletion-status" role="status">
      <div className={styles.emptyAlly} aria-hidden="true">
        <AllyAvatar shape="ghosty" color="#ff5800" size={92} label="" />
      </div>
      <h1>{state === "repair_required" ? "Deletion needs attention" : `Deleting ${ally.name}`}</h1>
      <p>{state === "repair_required"
        ? "We couldn't finish removing this Ally. It stays unavailable until cleanup is confirmed."
        : "Deletion is still in progress. This Ally stays unavailable until cleanup is confirmed."}</p>
      {error ? <p role="alert">{error}</p> : null}
      <div className={styles.emptyAction}>
        <button type="button" onClick={() => void handleRefresh()} disabled={refreshing}>
          {refreshing ? "Checking…" : "Refresh deletion status"}
        </button>
      </div>
    </div>
  );
}

function mergeMessages(...groups: MessageViewModel[][]): MessageViewModel[] {
  return mergeConversationMessageCopies(...groups);
}

export function mergeAssistantReplies(
  ...groups: readonly (readonly AssistantReplyViewModel[])[]
): AssistantReplyViewModel[] {
  const bySourceMessageId = new Map<string, AssistantReplyViewModel>();
  for (const group of groups) {
    for (const reply of group) {
      const current = bySourceMessageId.get(reply.sourceMessageId);
      if (!current || preferAssistantReply(current, reply)) {
        bySourceMessageId.set(reply.sourceMessageId, current
          && isTerminalReplyStatus(reply.status)
          && !reply.hasFullPrefix
          && current.hasFullPrefix
          ? { ...reply, content: current.content, hasFullPrefix: true }
          : reply);
      }
    }
  }
  return [...bySourceMessageId.values()].sort(
    (left, right) => left.conversationTurnOrdinal - right.conversationTurnOrdinal
      || left.sourceMessageId.localeCompare(right.sourceMessageId),
  );
}

function mergeAssistantReplyState(
  current: AssistantReplyState,
  conversationId: string,
  incoming: readonly AssistantReplyViewModel[],
): AssistantReplyState {
  if (incoming.length === 0 && current.conversationId === conversationId) return current;
  return {
    conversationId,
    replies: current.conversationId === conversationId
      ? mergeAssistantReplies(current.replies, incoming)
      : [...incoming],
  };
}

function preferAssistantReply(
  current: AssistantReplyViewModel,
  incoming: AssistantReplyViewModel,
): boolean {
  const currentTerminal = isTerminalReplyStatus(current.status);
  const incomingTerminal = isTerminalReplyStatus(incoming.status);
  if (currentTerminal !== incomingTerminal) return incomingTerminal;
  const currentUpdatedAt = Date.parse(current.updatedAt);
  const incomingUpdatedAt = Date.parse(incoming.updatedAt);
  if (currentTerminal && incomingTerminal) {
    return Number.isFinite(currentUpdatedAt)
      && Number.isFinite(incomingUpdatedAt)
      && incomingUpdatedAt > currentUpdatedAt;
  }
  if (current.hasFullPrefix !== incoming.hasFullPrefix) return incoming.hasFullPrefix;
  if (Number.isFinite(currentUpdatedAt) && Number.isFinite(incomingUpdatedAt)
    && currentUpdatedAt !== incomingUpdatedAt) {
    return incomingUpdatedAt > currentUpdatedAt;
  }
  if (current.content.length !== incoming.content.length) return incoming.content.length > current.content.length;
  if (current.isTruncated !== incoming.isTruncated) return incoming.isTruncated === true;
  return incoming.status !== current.status && isLaterReplyStatus(incoming.status, current.status);
}

function isTerminalReplyStatus(status: AssistantReplyViewModel["status"]): boolean {
  return status === "completed" || status === "failed" || status === "stopped";
}

function isLaterReplyStatus(
  incoming: AssistantReplyViewModel["status"],
  current: AssistantReplyViewModel["status"],
): boolean {
  const rank: Record<AssistantReplyViewModel["status"], number> = {
    queued: 0,
    in_progress: 1,
    awaiting_action: 2,
    completed: 3,
    failed: 3,
    stopped: 3,
  };
  return rank[incoming] > rank[current];
}

function canChat(ally: AllyViewModel): boolean {
  return ally.provisioningState === "bound" && !isAllyDeleting(ally);
}

function isGettingReady(ally: AllyViewModel): boolean {
  return ally.provisioningState === "pending" || ally.provisioningState === "retryable";
}

function allySecondaryLine(ally: AllyViewModel): string {
  if (allyDeletionState(ally) === "pending") return "Deleting…";
  if (allyDeletionState(ally) === "repair_required") return "Deletion needs attention";
  if (ally.provisioningState === "bound") return ally.job;
  return provisioningLabel(ally.provisioningState);
}

function provisioningLabel(state: AllyViewModel["provisioningState"]): string {
  return {
    pending: "Getting ready",
    retryable: "Getting ready",
    failed: "Setup failed",
    incompatible: "Needs an update",
    repair_required: "Needs repair",
    bound: "Ready",
  }[state];
}

function provisioningNotice(ally: AllyViewModel): string | null {
  if (isGettingReady(ally) || ally.provisioningState === "bound") return null;
  if (ally.provisioningState === "failed") return `${ally.name}'s setup failed.`;
  if (ally.provisioningState === "repair_required") return `${ally.name} needs repair before messaging.`;
  return `${ally.name} needs an update before messaging.`;
}

function isLiveQueuedMessage(message: MessageViewModel): boolean {
  return message.sender === "user"
    && !message.deletedAt
    && message.status !== "completed"
    && message.status !== "failed"
    && message.status !== "stopped";
}

function isCloudQueueMessageRemovable(message: MessageViewModel): boolean {
  return isLiveQueuedMessage(message)
    && message.status === "queued"
    && message.queueState === "unclaimed"
    && !message.deletedAt;
}

export function projectConversationActivity(
  current: ActivityProjection,
  snapshot: ActivitySnapshotViewModel,
  messages: readonly MessageViewModel[],
): ActivityProjection {
  const currentActiveMessageId = current.activeMessageId;
  if (
    currentActiveMessageId
    && !snapshotCanOwnActiveMessage(
      currentActiveMessageId,
      messages.find((message) => message.id === currentActiveMessageId)?.sequence
        ?? current.turns.find((turn) => turn.messageId === currentActiveMessageId)?.turnOrdinal
        ?? null,
      snapshot,
      messages,
    )
  ) {
    return projectActivitySnapshot(current, {
      ...snapshot,
      activeMessageId: currentActiveMessageId,
      state: current.state,
    });
  }
  if (currentActiveMessageId && snapshot.activeMessageId === undefined) {
    return projectActivitySnapshot(current, {
      ...snapshot,
      activeMessageId: currentActiveMessageId,
    });
  }
  return projectActivitySnapshot(current, snapshot);
}

function snapshotMessageOrdinal(
  snapshot: ActivitySnapshotViewModel,
  messages: readonly MessageViewModel[],
): number | null {
  const id = snapshot.activeMessageId;
  return messages.find((message) => message.id === id)?.sequence
    ?? snapshot.activities.find((activity) => activity.messageId === id)?.conversationTurnOrdinal
    ?? (snapshot.assistantReply?.sourceMessageId === id ? snapshot.assistantReply?.conversationTurnOrdinal : null)
    ?? null;
}

function snapshotCanOwnActiveMessage(
  currentId: string | null | undefined,
  currentOrdinal: number | null,
  snapshot: ActivitySnapshotViewModel,
  messages: readonly MessageViewModel[],
): boolean {
  if (!currentId || snapshot.activeMessageId === undefined || snapshot.activeMessageId === currentId) return true;
  const incomingOrdinal = snapshotMessageOrdinal(snapshot, messages);
  if (currentOrdinal !== null && incomingOrdinal !== null) return incomingOrdinal > currentOrdinal;
  const currentMessage = messages.find((message) => message.id === currentId);
  return Boolean(currentMessage && !isLiveQueuedMessage(currentMessage));
}

function resolveActiveMessageId(
  projection: ActivityProjection,
  queue: readonly MessageViewModel[],
  messages: readonly MessageViewModel[],
): string | null {
  if (projection.activeMessageId) {
    const projectedMessage = messages.find((message) => message.id === projection.activeMessageId);
    if (projectedMessage && isLiveQueuedMessage(projectedMessage)) return projection.activeMessageId;
  }
  const claimed = queue.find((message) => message.queueState === "claimed");
  if (claimed) return claimed.id;
  const projected = projection.turns.find((turn) => (
    (turn.state === "queued" || turn.state === "running")
      && messages.some((message) => message.id === turn.messageId && isLiveQueuedMessage(message))
  ));
  if (projected) return projected.messageId;
  const fallback = messages
    .filter((message) => isLiveQueuedMessage(message) && message.queueState !== "unclaimed")
    .sort((left, right) => left.sequence - right.sequence || left.id.localeCompare(right.id))[0];
  return fallback?.id ?? null;
}

function filterAuthoritativeQueueMessages(
  messages: readonly MessageViewModel[],
  queue: readonly MessageViewModel[] | undefined,
): MessageViewModel[] {
  if (queue === undefined) return [...messages];
  const queueIds = new Set(queue.map((message) => message.id));
  return messages.filter((message) => (
    !isLiveQueuedMessage(message) || queueIds.has(message.id)
  ));
}

export interface LocalQueuedAttachments {
  files: QueuedAttachmentPreview[];
  status: string | null;
}

export function localTransferQueueStatus(transfer: {
  phase: string;
  files: readonly { state: string; progress: number }[];
}): string | null {
  if (transfer.phase === "failed") return "Needs attention";
  if (transfer.phase === "checking") return "Checking file…";
  if (transfer.phase !== "uploading") return null;
  if (transfer.files.some((file) => file.state === "validating" || file.state === "receiving")) return "Checking file…";
  const pending = transfer.files.filter((file) => file.state === "pending");
  if (!pending.length) return null;
  return `Uploading ${Math.min(...pending.map((file) => file.progress))}%`;
}

export function buildQueuedFrameMessages(
  cloudQueue: readonly MessageViewModel[],
  localQueue: readonly QueuedMessage[],
  activeMessageId: string | null,
  activeMessageHasProgress: boolean,
  activeMessageInTimeline = true,
  resolveLocalFiles?: (fileTransferId: string) => LocalQueuedAttachments | null,
): ProductionQueuedMessageModel[] {
  const items: ProductionQueuedMessageModel[] = [];
  for (const message of cloudQueue) {
    if (!isLiveQueuedMessage(message)) continue;
    if (message.id === activeMessageId && activeMessageInTimeline) continue;
    items.push({
      id: message.id,
      content: message.content,
      removable: isCloudQueueMessageRemovable(message),
      statusLabel: cloudQueuedAttachmentStatus(message) ?? (message.id === activeMessageId && !activeMessageHasProgress ? "Queued" : null),
      ...(message.files?.length ? {
        attachments: message.files.map((file) => ({
          id: file.id,
          name: file.name,
          ready: file.state === "ready" || file.state === "retained",
        })),
      } : {}),
    });
  }
  for (const message of localQueue) {
    const resolved = message.fileTransferId ? resolveLocalFiles?.(message.fileTransferId) ?? null : null;
    items.push({
      id: message.id,
      content: message.content,
      removable: supportsQueueMessageLocks() && message.attemptedAt === undefined,
      statusLabel: resolved?.status ?? null,
      ...(resolved ? { attachments: resolved.files } : {}),
    });
  }
  return items;
}

function cloudQueuedAttachmentStatus(message: MessageViewModel): string | null {
  if (message.preparation === "uploading"
    || message.files?.some((file) => file.state === "pending" || file.state === "receiving" || file.state === "validating")) {
    return "Uploading…";
  }
  return null;
}

const FAILED_FILE_PREPARATIONS: ReadonlySet<string> = new Set(["failed", "needs_retry"]);
const FAILED_FILE_STATES: ReadonlySet<string> = new Set(["failed", "rejected"]);

export function queuedAttachmentQueueIds(
  timelineMessages: readonly MessageViewModel[],
  activeMessageId: string | null,
): Set<string> {
  return new Set(timelineMessages.filter((message) => {
    if (!message.files?.length && !(message.preparation && message.preparation !== "none")) return false;
    if (!isLiveQueuedMessage(message)) return false;
    if (message.id === activeMessageId) return false;
    if (message.queueState === "claimed") return false;
    if (message.preparation && FAILED_FILE_PREPARATIONS.has(message.preparation)) return false;
    if (message.files?.some((file) => FAILED_FILE_STATES.has(file.state))) return false;
    return true;
  }).map((message) => message.id));
}

function activityStateFromMessage(status: MessageViewModel["status"]): ActivityState {
  return status === "in_progress" ? "running" : status;
}

function isUnknownMessageAcceptance(error: unknown): boolean {
  if (!isCloudError(error)) return true;
  return error.kind === "network"
    || error.kind === "timeout"
    || error.kind === "server"
    || error.kind === "aborted";
}

function isDefinitiveMessageRejection(error: unknown): boolean {
  return isCloudError(error) && error.kind === "validation" && error.status === 422;
}

function initials(name: string): string {
  const value = name.trim();
  if (!value) return "A";
  return value.split(/\s+/u).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

function ChefIcon() {
  return <Image src="/home/mobile-roster/chef.svg" alt="" width={22} height={22} aria-hidden="true" />;
}

function SearchIcon() {
  return <Image src="/home/mobile-roster/search.svg" alt="" width={22} height={22} aria-hidden="true" />;
}

function readQueuedMessages(storageKey: string): QueuedMessage[] {
  if (isQueuedMessageStoragePurged(storageKey)) return [];
  try {
    return parseQueuedMessages(window.localStorage.getItem(storageKey));
  } catch {
    return [];
  }
}

function parseQueuedMessages(stored: string | null): QueuedMessage[] {
  try {
    if (!stored) return [];
    const value: unknown = JSON.parse(stored);
    if (!Array.isArray(value)) return [];
    const seenIds = new Set<string>();
    const seenIntentKeys = new Set<string>();
    return value.flatMap((message, index): QueuedMessage[] => {
      if (!message || typeof message !== "object") return [];
      const item = message as Partial<QueuedMessage>;
      const valid = typeof item.id === "string"
        && typeof item.content === "string"
        && (item.content.length > 0 || typeof item.fileTransferId === "string" && /^[0-9a-f-]{36}$/.test(item.fileTransferId))
        && item.content.length <= 16_000
        && typeof item.intentKey === "string";
      if (!valid || seenIds.has(item.id as string) || seenIntentKeys.has(item.intentKey as string)) return [];
      seenIds.add(item.id as string);
      seenIntentKeys.add(item.intentKey as string);
      return [{
        id: item.id as string,
        content: item.content as string,
        intentKey: item.intentKey as string,
        ...(typeof item.fileTransferId === "string" && /^[0-9a-f-]{36}$/.test(item.fileTransferId) ? { fileTransferId: item.fileTransferId } : {}),
        queuedAt: typeof item.queuedAt === "number" && Number.isFinite(item.queuedAt) ? item.queuedAt : index,
        ...(typeof item.attemptedAt === "number" && Number.isFinite(item.attemptedAt)
          ? { attemptedAt: item.attemptedAt }
          : {}),
      }];
    }).slice(0, MAX_QUEUED_MESSAGES);
  } catch {
    return [];
  }
}

function readLiveQueuedMessages(storageKey: string): QueuedMessage[] {
  const removedIds = readQueuedMessageTombstones(storageKey);
  return readQueuedMessages(storageKey).filter((message) => !removedIds.has(message.id));
}

function mergeQueuedMessages(...groups: QueuedMessage[][]): QueuedMessage[] {
  const byId = new Map<string, QueuedMessage>();
  for (const group of groups) {
    for (const message of group) {
      const current = byId.get(message.id);
      if (current?.attemptedAt !== undefined && message.attemptedAt === undefined) continue;
      byId.set(message.id, message);
    }
  }
  return [...byId.values()]
    .sort((left, right) => left.queuedAt - right.queuedAt || left.id.localeCompare(right.id))
    .slice(0, MAX_QUEUED_MESSAGES);
}

function markQueuedMessageAttempt(
  storageKey: string,
  messageId: string,
  commit: (change: (messages: QueuedMessage[]) => QueuedMessage[]) => boolean,
): boolean {
  let found = false;
  const committed = commit((messages) => messages.map((message) => {
    if (message.id !== messageId) return message;
    found = true;
    return { ...message, attemptedAt: message.attemptedAt ?? Date.now() };
  }));
  if (!committed || !found) return false;
  try {
    const persisted = readQueuedMessages(storageKey).find((message) => message.id === messageId);
    return persisted?.attemptedAt !== undefined;
  } catch {
    return false;
  }
}

async function withQueueMessageLock<T>(
  storageKey: string,
  messageId: string,
  task: () => Promise<T>,
): Promise<T> {
  if (supportsQueueMessageLocks()) {
    return navigator.locks.request(
      `allies-queued-message:${storageKey}:${messageId}`,
      { mode: "exclusive" },
      task,
    );
  }
  return task();
}

function supportsQueueMessageLocks(): boolean {
  return typeof navigator !== "undefined" && Boolean(navigator.locks);
}

function queuedMessageTombstonePrefix(storageKey: string) {
  return `${storageKey}:removed:`;
}

const QUEUED_MESSAGE_TOMBSTONE_LIMIT = 256;

function listQueuedMessageTombstones(storageKey: string) {
  const prefix = queuedMessageTombstonePrefix(storageKey);
  const tombstones: Array<{ id: string; key: string; removedAt: number }> = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (!key?.startsWith(prefix)) continue;
    const removedAt = Number(window.localStorage.getItem(key));
    if (!Number.isFinite(removedAt)) continue;
    tombstones.push({ id: decodeURIComponent(key.slice(prefix.length)), key, removedAt });
  }
  return tombstones;
}

function readQueuedMessageTombstones(storageKey: string): Set<string> {
  try {
    return new Set(listQueuedMessageTombstones(storageKey).map((tombstone) => tombstone.id));
  } catch {
    return new Set();
  }
}

function persistQueuedMessageTombstone(storageKey: string, messageId: string): boolean {
  if (isQueuedMessageStoragePurged(storageKey)) return true;
  try {
    window.localStorage.setItem(
      `${queuedMessageTombstonePrefix(storageKey)}${encodeURIComponent(messageId)}`,
      String(Date.now()),
    );
    listQueuedMessageTombstones(storageKey)
      .sort((left, right) => right.removedAt - left.removedAt)
      .forEach((tombstone, index) => {
        if (index >= QUEUED_MESSAGE_TOMBSTONE_LIMIT) window.localStorage.removeItem(tombstone.key);
      });
    return true;
  } catch {
    return false;
  }
}

function persistQueuedMessages(storageKey: string, messages: QueuedMessage[]): boolean {
  if (isQueuedMessageStoragePurged(storageKey)) {
    purgeQueuedMessageStorage(storageKey);
    return true;
  }
  try {
    if (messages.length) {
      window.localStorage.setItem(storageKey, JSON.stringify(messages));
    } else {
      window.localStorage.removeItem(storageKey);
    }
    return true;
  } catch {
    return false;
  }
}
