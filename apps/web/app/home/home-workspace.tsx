"use client";

import type {
  ActivitySnapshotViewModel,
  ActivityState,
  AllyViewModel,
  MessageViewModel,
} from "@allies/cloud-client";
import {
  EMPTY_ACTIVITY_PROJECTION,
  isCloudError,
  isActivityTerminal,
  projectActivitySnapshot,
  type ActivityProjection,
  type AssistantTurnProjection,
} from "@allies/cloud-client";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Streamdown } from "streamdown";
import {
  Fragment,
  type CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import Onboarding from "../(onboarding)/_components";
import { OnboardingStateProvider } from "../(onboarding)/_store/onboarding-store";
import { AllyAvatar, ALLY_SHAPES, type AllyShape } from "../../components/ally-avatar";
import { ShinyText } from "../../components/text-animations/shiny-text";
import { currentAccountQueryOptions } from "../../lib/account/account-query";
import { AuthenticatedAllyFlowProvider } from "../../lib/allies/authenticated-onboarding-flow";
import { alliesQueryOptions, conversationQueryKey } from "../../lib/allies/queries";
import { alliesQueryKey } from "../../lib/allies/query-keys";
import { readActivityStream, type ActivityStreamHandle } from "../../lib/allies/activity-stream";
import { useComposingRuntimeIntent } from "../../lib/allies/runtime-intent";
import { getActivitySseEnabled, getWebEnvironment } from "../../lib/env";
import { useSession } from "../../lib/session/session-context";
import {
  WAITLIST_APPEARANCE_CATALOG_VERSION,
  WAITLIST_COLORS,
} from "../../lib/waitlist/catalog";

import styles from "./home.module.css";

const ACTIVITY_INTERVAL_MS = 500;
const ACTIVITY_POLL_LIMIT = 240;
const ACTIVITY_REPLAY_MAX_PAGES = 64;
const ACTIVITY_REPLAY_MAX_BYTES = 4 * 1024 * 1024;
const EMPTY_MESSAGES: MessageViewModel[] = [];
const ALLY_PREVIEW_LIMIT = 32;
const QUEUED_MESSAGES_STORAGE_VERSION = "v1";
export const ALLY_SLEEP_AFTER_MS = 10 * 60 * 1_000;
const ALLY_SLEEP_CLOCK_INTERVAL_MS = 30_000;

type QueuedMessage = {
  id: string;
  content: string;
  intentKey: string;
  queuedAt: number;
  state: "queued" | "dispatching" | "blocked";
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

function activitySnapshotBytes(snapshot: unknown): number {
  const encoded = JSON.stringify(snapshot);
  return new TextEncoder().encode(encoded).byteLength;
}

function hasVisibleAssistantText(snapshot: ActivitySnapshotViewModel): boolean {
  return snapshot.activities.some(
    (activity) => activity.kind === "assistant_delta" && Boolean(activity.text.trim()),
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
  const sessionStatus = session.state.status;
  const restoreSession = session.restore;
  const router = useRouter();
  const restoreStarted = useRef(false);
  const redirectStarted = useRef(false);
  const [sleepClock, setSleepClock] = useState<number | null>(null);
  const [recentActivityByAlly, setRecentActivityByAlly] = useState<Record<string, number>>({});
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
    if (session.state.status !== "signed-out" || redirectStarted.current) return;
    redirectStarted.current = true;
    router.replace("/sign-in?returnTo=%2Fhome");
  }, [router, session.state.status]);

  const accountQuery = useQuery({
    ...currentAccountQueryOptions(session.client, session.runCloudOperation),
    enabled: session.state.status === "signed-in",
  });
  const workspaceId = accountQuery.data?.workspace.id ?? "";
  const alliesOptions = useMemo(
    () => alliesQueryOptions(session.client, session.runCloudOperation, workspaceId),
    [session.client, session.runCloudOperation, workspaceId],
  );
  const alliesQuery = useQuery({
    ...alliesOptions,
    enabled: Boolean(workspaceId),
  });
  const allies = useMemo(() => alliesQuery.data ?? [], [alliesQuery.data]);
  const allyPreviewQueries = useQueries({
    queries: allies.slice(0, ALLY_PREVIEW_LIMIT).map((ally) => ({
      queryKey: [...conversationQueryKey(workspaceId, ally.id), "preview"] as const,
      queryFn: ({ signal }: { signal: AbortSignal }) => session.runCloudOperation(
        (operationSignal) => session.client.getAllyConversation(workspaceId, ally.id, {
          limit: 1,
          signal: operationSignal,
        }),
        { signal },
      ),
      enabled: Boolean(workspaceId),
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
      return [ally.id, { latestMessage, isPending: Boolean(query?.isPending), isError: Boolean(query?.isError) }] as const;
    })),
    [allies, allyPreviewQueries],
  );
  const selectedAlly = selectedAllyId
    ? allies.find((ally) => ally.id === selectedAllyId) ?? null
    : null;
  const creatingAlly = selectedAllyId === "new";

  const handleCreated = useCallback(
    (ally: AllyViewModel) => {
      queryClient.setQueryData<AllyViewModel[]>(alliesQueryKey(workspaceId), (current) => {
        if (current?.some((item) => item.id === ally.id)) return current;
        return [...(current ?? []), ally];
      });
      router.replace(`/home/${encodeURIComponent(ally.id)}`);
    },
    [queryClient, router, workspaceId],
  );
  const hasBlockingQueryError = (accountQuery.isError && !accountQuery.data)
    || (alliesQuery.isError && !alliesQuery.data);
  const hasBackgroundQueryError = (accountQuery.isError && Boolean(accountQuery.data))
    || (alliesQuery.isError && Boolean(alliesQuery.data));
  const refetchAccount = accountQuery.refetch;
  const refetchAllies = alliesQuery.refetch;
  const retryWorkspaceQueries = useCallback(() => {
    void Promise.all([refetchAccount(), refetchAllies()]);
  }, [refetchAccount, refetchAllies]);

  if (session.state.status === "unknown" || session.state.status === "restoring") {
    return <HomeStatus title="Restoring your Allies" detail="Checking your secure session…" />;
  }
  if (session.state.status === "signed-out") {
    return <HomeStatus title="Opening sign-in" detail="Taking you to Google…" />;
  }
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
  if (!accountQuery.data || alliesQuery.isPending) {
    return <HomeStatus title="Gathering your Allies" detail="Opening your conversations…" />;
  }

  const invalidSelection = Boolean(selectedAllyId && !creatingAlly && !selectedAlly);

  return (
    <main className={`${styles.page} ${!selectedAllyId ? styles.rosterPage : ""}`}>
      <section
        className={`${styles.roster} ${selectedAllyId ? styles.rosterHiddenOnMobile : ""}`}
        aria-label="Ally conversations"
      >
        <header className={styles.rosterHeader}>
          <Link className={styles.brandButton} href="/home" aria-label="Allies home">
            <Image src="/allies-icon.svg" alt="Allies" width={48} height={48} priority unoptimized />
          </Link>
          <Link
            className={styles.newAllyButton}
            href="/home/new"
            aria-label="Meet another Ally"
          >
            <PlusIcon />
          </Link>
        </header>

        <div className={styles.rosterSearch}>
          <SearchIcon />
          <span>Search</span>
        </div>

        <div className={styles.rosterTabs}>
          <span className={`${styles.rosterTab} ${styles.rosterTabActive}`}>
            My allies
          </span>
          <span className={`${styles.rosterTab} ${styles.rosterTabMuted}`}>
            Routines
          </span>
        </div>

        {hasBackgroundQueryError && !selectedAllyId ? (
          <WorkspaceRefreshError onRetry={retryWorkspaceQueries} />
        ) : null}

        {allies.length ? (
          <nav className={styles.allyList} aria-label="Choose an Ally">
            {allies.map((ally) => (
              <AllyConversationRow
                key={ally.id}
                ally={ally}
                selected={ally.id === selectedAllyId}
                preview={allyPreviews.get(ally.id)}
                sleepClock={sleepClock}
                recentActivityAt={recentActivityByAlly[ally.id]}
              />
            ))}
          </nav>
        ) : (
          <div className={styles.rosterEmpty}>
            <p>No Allies here yet.</p>
            <Link
              className={`${styles.primaryAction} ${styles.mobileOnly}`}
              href="/home/new"
            >
              Meet your first Ally
            </Link>
          </div>
        )}

        <footer className={styles.rosterFooter}>
          <Link className={styles.accountLink} href="/account">
            <span className={styles.accountMark} aria-hidden="true">
              {initials(accountQuery.data.displayName)}
            </span>
            <span>{accountQuery.data.displayName || "Your account"}</span>
          </Link>
          <Link className={`${styles.primaryAction} ${styles.mobileRosterCta}`} href="/home/new">
            Make an Ally
          </Link>
        </footer>
      </section>

      {selectedAllyId ? (
        <section className={styles.thread} aria-label="Selected Ally conversation">
          {creatingAlly ? (
            <HomeAllyCreationPane workspaceId={workspaceId} onCreated={handleCreated} />
          ) : invalidSelection ? (
            <EmptyThread
              title="That Ally isn't in this Workspace"
              detail="Choose one of your Allies to keep talking."
              action={<Link className={styles.primaryAction} href="/home">Back to Allies</Link>}
            />
          ) : selectedAlly ? (
            <ConversationPane
              key={selectedAlly.id}
              workspaceId={workspaceId}
              ally={selectedAlly}
              sleepClock={sleepClock}
              recentActivityAt={recentActivityByAlly[selectedAlly.id]}
              onActivity={() => recordAllyActivity(selectedAlly.id)}
              workspaceRefreshError={hasBackgroundQueryError}
              onRetryWorkspace={retryWorkspaceQueries}
            />
          ) : allies.length ? (
            <EmptyThread
              title="Choose an Ally"
              detail="Every Ally has one continuous conversation waiting here."
            />
          ) : (
            <EmptyThread
              title="Meet your first Ally"
              detail="Start with someone built around what matters to you."
              action={<Link className={styles.primaryAction} href="/home/new">Meet your first Ally</Link>}
            />
          )}
        </section>
      ) : null}
    </main>
  );
}

function HomeAllyCreationPane({
  workspaceId,
  onCreated,
}: {
  workspaceId: string;
  onCreated: (ally: AllyViewModel) => void;
}) {
  return (
    <div className={styles.creationPane}>
      <OnboardingStateProvider initialStep="name">
        <AuthenticatedAllyFlowProvider workspaceId={workspaceId} onCreated={onCreated}>
          <Onboarding exitHref="/home" />
        </AuthenticatedAllyFlowProvider>
      </OnboardingStateProvider>
    </div>
  );
}

type ResolvedAllyAppearance = { shape: AllyShape; color: string };

export function resolveAllyAppearance(ally: AllyViewModel): ResolvedAllyAppearance | null {
  if (ally.appearance.catalogVersion !== WAITLIST_APPEARANCE_CATALOG_VERSION) return null;
  const [rawShape, rawColor, ...extra] = ally.appearance.key.split(":");
  if (extra.length > 0 || !ALLY_SHAPES.includes(rawShape as AllyShape)) return null;
  const color = WAITLIST_COLORS.find(
    (candidate) => candidate.slice(1) === rawColor?.toLowerCase(),
  );
  return color ? { shape: rawShape as AllyShape, color } : null;
}

function AllyIdentityAvatar({
  ally,
  size,
  thinking = false,
  sleeping = false,
}: {
  ally: AllyViewModel;
  size: number;
  thinking?: boolean;
  sleeping?: boolean;
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
      shape={avatar.shape}
      color={avatar.color}
      state={thinking || isGettingReady(ally) ? "thinking" : "idle"}
      size={size}
      label=""
      className={sleeping ? styles.sleepingAvatar : undefined}
    />
  );
}

type AllyPreview = {
  latestMessage: MessageViewModel | null;
  isPending: boolean;
  isError: boolean;
};

function previewText(message: MessageViewModel | null): string {
  if (!message?.content.trim()) return "No messages yet";
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
}: {
  ally: AllyViewModel;
  selected: boolean;
  preview?: AllyPreview;
  sleepClock: number | null;
  recentActivityAt?: number;
}) {
  const latestMessage = preview?.latestMessage ?? null;
  const sleeping = isAllySleeping(ally, latestMessage, sleepClock, recentActivityAt);
  return (
    <Link
      href={`/home/${encodeURIComponent(ally.id)}`}
      className={`${styles.allyRow} ${selected ? styles.allyRowSelected : ""}`}
      aria-current={selected ? "page" : undefined}
      data-ally-sleeping={sleeping ? "true" : "false"}
    >
      <span className={styles.allyAvatarWrap}>
        <AllyIdentityAvatar ally={ally} size={48} sleeping={sleeping} />
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
        <span className={preview?.isPending ? styles.allyPreviewPending : styles.allyPreview}>
          {preview === undefined || preview.isError
            ? allySecondaryLine(ally)
            : preview.isPending && !latestMessage
              ? "Opening conversation…"
              : previewText(latestMessage)}
        </span>
      </span>
    </Link>
  );
}

function ConversationPane({
  workspaceId,
  ally,
  sleepClock,
  recentActivityAt,
  onActivity,
  workspaceRefreshError,
  onRetryWorkspace,
}: {
  workspaceId: string;
  ally: AllyViewModel;
  sleepClock: number | null;
  recentActivityAt?: number;
  onActivity: () => void;
  workspaceRefreshError: boolean;
  onRetryWorkspace: () => void;
}) {
  const session = useSession();
  const cloudClient = session.client;
  const runCloudOperation = session.runCloudOperation;
  const queryClient = useQueryClient();
  const [olderMessages, setOlderMessages] = useState<MessageViewModel[]>([]);
  const [nextCursorOverride, setNextCursorOverride] = useState<string | null | undefined>(undefined);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderLoadError, setOlderLoadError] = useState<string | null>(null);
  const [sentMessages, setSentMessages] = useState<MessageViewModel[]>([]);
  const [draft, setDraft] = useState("");
  const draftRef = useRef("");
  const [queuedMessages, setQueuedMessages] = useState<QueuedMessage[]>([]);
  const queuedMessagesRef = useRef<QueuedMessage[]>([]);
  const [queuedMessagesLoadedFor, setQueuedMessagesLoadedFor] = useState<string | null>(null);
  const queuedDispatchRef = useRef(false);
  const [sending, setSending] = useState(false);
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
  const [pollBudgetReached, setPollBudgetReached] = useState(false);
  const [projection, setProjection] = useState<ActivityProjection>(EMPTY_ACTIVITY_PROJECTION);
  const pollingRef = useRef(false);
  const pollCountRef = useRef(0);
  const activityHistoryLoadedRef = useRef<string | null>(null);
  const observedActiveMessageRef = useRef<string | null>(null);
  const previousProvisioningStateRef = useRef(ally.provisioningState);
  const activityReplayRef = useRef<{
    conversationId: string;
    cursor: string | null;
    afterSequence: number;
    blocked: "gap" | "invalid" | null;
  } | null>(null);
  const activityReplayExpiredRestartedRef = useRef(false);
  const [activityHistoryRetry, setActivityHistoryRetry] = useState(0);
  const activityRequestRef = useRef<AbortController | null>(null);
  const activitySnapshotRequestRef = useRef<AbortController | null>(null);
  const activityHistoryRequestRef = useRef<AbortController | null>(null);
  const activityStreamRef = useRef<ActivityStreamHandle | null>(null);
  const turnGenerationRef = useRef(0);
  const responseStartedRef = useRef(false);
  const olderRequestRef = useRef<AbortController | null>(null);
  const historyRevisionRef = useRef(0);
  const mountedRef = useRef(true);
  const messageCanvasRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(true);
  const queuedMessagesStorageKey = `allies:${QUEUED_MESSAGES_STORAGE_VERSION}:queued-messages:${workspaceId}:${ally.id}`;
  const queuedMessagesReady = queuedMessagesLoadedFor === queuedMessagesStorageKey;
  const requestRuntimeIntent = useCallback(
    (targetAllyId: string, occurredAt: string, idempotencyKey: string, signal?: AbortSignal) =>
      runCloudOperation(
        (operationSignal) => cloudClient.requestRuntimeIntent(targetAllyId, occurredAt, idempotencyKey, operationSignal),
        { csrf: true, retryTransient: true, signal },
      ),
    [cloudClient, runCloudOperation],
  );
  const { observeEdit, compositionStart, compositionEnd } = useComposingRuntimeIntent(
    ally.id,
    requestRuntimeIntent,
  );

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
      const loaded = readLiveQueuedMessages(queuedMessagesStorageKey)
        .map((message) => message.state === "dispatching" ? { ...message, state: "blocked" as const } : message);
      queuedMessagesRef.current = loaded;
      persistQueuedMessages(queuedMessagesStorageKey, loaded);
      setQueuedMessages(loaded);
      setQueuedMessagesLoadedFor(queuedMessagesStorageKey);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [queuedMessagesStorageKey]);

  const commitQueuedMessages = useCallback((change: (messages: QueuedMessage[]) => QueuedMessage[]) => {
    const removedIds = readQueuedMessageTombstones(queuedMessagesStorageKey);
    const current = mergeQueuedMessages(
      queuedMessagesRef.current,
      readQueuedMessages(queuedMessagesStorageKey),
    ).filter((message) => !removedIds.has(message.id));
    const next = change(current).filter((message) => !removedIds.has(message.id));
    queuedMessagesRef.current = next;
    persistQueuedMessages(queuedMessagesStorageKey, next);
    setQueuedMessages(next);
  }, [queuedMessagesStorageKey]);

  const removeQueuedMessage = useCallback((messageId: string) => {
    persistQueuedMessageTombstone(queuedMessagesStorageKey, messageId);
    commitQueuedMessages((messages) => messages.filter((message) => message.id !== messageId));
  }, [commitQueuedMessages, queuedMessagesStorageKey]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea !== window.localStorage) return;
      const tombstonePrefix = queuedMessageTombstonePrefix(queuedMessagesStorageKey);
      if (event.key !== queuedMessagesStorageKey && !event.key?.startsWith(tombstonePrefix)) return;
      const incoming = event.key === queuedMessagesStorageKey
        ? parseQueuedMessages(event.newValue)
        : [];
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

  const conversationQuery = useQuery({
    queryKey: conversationQueryKey(workspaceId, ally.id),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    queryFn: ({ signal }) =>
      session.runCloudOperation(
        (operationSignal) =>
          session.client.getAllyConversation(workspaceId, ally.id, { limit: 50, signal: operationSignal }),
        { signal },
      ),
  });
  const conversation = conversationQuery.data;
  const latestConversationMessages = conversation?.messages ?? EMPTY_MESSAGES;
  const nextCursor = nextCursorOverride === undefined
    ? conversation?.nextCursor ?? null
    : nextCursorOverride;
  const latestPersistedUserMessage = conversation?.messages
    .filter((message) => message.sender === "user")
    .at(-1);
  const persistedTurnActive = latestPersistedUserMessage?.status === "queued"
    || latestPersistedUserMessage?.status === "in_progress";
  const turnInProgress = activeTurn || persistedTurnActive || streamConnected;
  const conversationId = conversation?.id;

  const messages = mergeMessages(olderMessages, latestConversationMessages, sentMessages);
  const firstAssistantMessageId = messages.find((message) => message.sender === "assistant")?.id;
  const activeUserMessage = turnInProgress || awaitingVisibleResponse
    ? messages.filter((message) => message.sender === "user").at(-1)
    : undefined;
  const activeProjectedTurn = activeUserMessage
    ? projection.turns.find((turn) => turn.turnOrdinal === activeUserMessage.sequence)
    : undefined;
  const responseStarted = Boolean(activeProjectedTurn?.assistantText.trim())
    || Boolean(activeUserMessage && messages.some(
      (message) => message.sender === "assistant" && message.sequence > activeUserMessage.sequence,
    ));
  const waitingForVisibleResponse = awaitingVisibleResponse && !responseStarted;
  const shouldPoll = !streamConnected
    && (activeTurn || waitingForVisibleResponse || (!pollingSettled && persistedTurnActive));
  const showThinkingState = sending
    || (turnInProgress && !responseStarted)
    || waitingForVisibleResponse;
  const gettingReady = isGettingReady(ally);
  const sleeping = !draft.trim()
    && !showThinkingState
    && !gettingReady
    && isAllySleeping(ally, messages.at(-1) ?? null, sleepClock, recentActivityAt);

  useEffect(() => {
    const messageId = latestPersistedUserMessage?.id;
    if (!persistedTurnActive || !messageId || observedActiveMessageRef.current === messageId) return;
    observedActiveMessageRef.current = messageId;
    setPollingSettled(false);
    setAwaitingVisibleResponse(true);
  }, [latestPersistedUserMessage?.id, persistedTurnActive]);

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

  const timelineSignature = useMemo(
    () => [
      messages.map((message) => `${message.id}:${message.status}`).join("|"),
      projection.turns
        .map((turn) => `${turn.messageId}:${turn.state}:${turn.assistantText.length}`)
        .join("|"),
      projection.pendingActivities
        ?.map((activity) => `${activity.id}:${activity.text.length}`)
        .join("|") ?? "",
    ].join("::"),
    [messages, projection.pendingActivities, projection.turns],
  );

  const loadOlder = async () => {
    if (!conversationId || !nextCursor || loadingOlder || !mountedRef.current) return;
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
      setNextCursorOverride(page.nextCursor);
      historyRevisionRef.current += 1;
    } catch {
      if (!controller.signal.aborted && mountedRef.current) {
        setOlderLoadError("We couldn't load earlier messages. Try again.");
      }
    } finally {
      if (olderRequestRef.current === controller) {
        olderRequestRef.current = null;
        if (mountedRef.current) setLoadingOlder(false);
      }
    }
  };

  const preserveLatestConversationWindow = useCallback((windowMessages: MessageViewModel[]) => {
    if (windowMessages.length === 0) return;
    setOlderMessages((current) => mergeMessages(windowMessages, current));
    historyRevisionRef.current += 1;
  }, []);

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

      if (hasVisibleAssistantText(snapshot)) {
        responseStartedRef.current = true;
        setAwaitingVisibleResponse(false);
      }
      setProjection((current) => projectActivitySnapshot(current, snapshot));
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
  }, [session, workspaceId]);

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
      if (hasVisibleAssistantText(snapshot)) {
        responseStartedRef.current = true;
        setAwaitingVisibleResponse(false);
      }
      setProjection((current) => projectActivitySnapshot(current, snapshot));
      setActivityError(null);
      setActivityHistoryError(null);
      setActivityReplayUnavailable(false);
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        if (!handleActivityReplayFailure(error)) {
          setActivityError("We couldn't check the latest response status.");
        }
      }
    } finally {
      if (activitySnapshotRequestRef.current === controller) {
        activitySnapshotRequestRef.current = null;
      }
    }
  }, [handleActivityReplayFailure, loadReplayWithRecovery, session, workspaceId]);

  const sendMessageContent = useCallback(async (
    content: string,
    key: string,
    clearSubmittedDraft: boolean,
  ): Promise<boolean> => {
    if (!conversation || !canChat(ally)) return false;
    const preservedOlderMessages = olderMessages;
    const preservedCursor = nextCursorOverride;
    turnGenerationRef.current += 1;
    responseStartedRef.current = false;
    activityRequestRef.current?.abort();
    followLatestRef.current = true;
    setSending(true);
    setSendError(null);
    try {
      const accepted = await session.runCloudOperation(
        (signal) => session.client.sendMessage(workspaceId, conversation.id, content, key, signal),
        { csrf: true },
      );
      onActivity();
      setSentMessages((current) => mergeMessages(current, [accepted.message]));
      if (clearSubmittedDraft && draftRef.current.trim() === content) {
        draftRef.current = "";
        setDraft("");
      }
      intentRef.current = null;
      setProjection((current) => ({
        ...current,
        state: activityStateFromMessage(accepted.message.status),
      }));
      setActivityError(null);
      pollCountRef.current = 0;
      setPollBudgetReached(false);
      setPollingSettled(false);
      const turnIsActive = accepted.message.status === "queued" || accepted.message.status === "in_progress";
      setActiveTurn(turnIsActive);
      setAwaitingVisibleResponse(turnIsActive || accepted.message.status === "completed");
      if (!turnIsActive) {
        setPollingSettled(true);
        preserveLatestConversationWindow(latestConversationMessages);
        const preservedHistoryRevision = historyRevisionRef.current;
        await conversationQuery.refetch().catch(() => undefined);
        if (mountedRef.current && historyRevisionRef.current === preservedHistoryRevision) {
          setOlderMessages((current) => mergeMessages(preservedOlderMessages, current));
          if (preservedCursor !== undefined) setNextCursorOverride(preservedCursor);
        }
        await refreshActivitySnapshot(conversation.id);
      }
      return true;
    } catch {
      setAwaitingVisibleResponse(false);
      setSendError("Your message wasn't accepted. Try the same message again.");
      return false;
    } finally {
      setSending(false);
    }
  }, [
    ally,
    conversation,
    conversationQuery,
    latestConversationMessages,
    nextCursorOverride,
    onActivity,
    olderMessages,
    preserveLatestConversationWindow,
    refreshActivitySnapshot,
    session,
    workspaceId,
  ]);

  const submit = async () => {
    if (!conversation || !queuedMessagesReady || sending || queuedDispatchRef.current || !canChat(ally)) return;
    const content = draft.trim();
    if (!content) return;
    const signature = `${conversation.id}:${content}`;
    const key = intentRef.current?.signature === signature
      && intentRef.current.draftRevision === draftRevisionRef.current
      ? intentRef.current.key
      : `message-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
    intentRef.current = { signature, key, draftRevision: draftRevisionRef.current };
    if (turnInProgress || queuedMessages.length > 0) {
      commitQueuedMessages((current) => [...current, {
        id: `queued-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`,
        content,
        intentKey: key,
        queuedAt: Math.max(Date.now(), (current.at(-1)?.queuedAt ?? 0) + 1),
        state: "queued",
      }]);
      draftRef.current = "";
      setDraft("");
      intentRef.current = null;
      return;
    }
    await sendMessageContent(content, key, true);
  };

  useEffect(() => {
    const nextMessage = queuedMessages[0];
    if (
      !nextMessage
      || nextMessage.state !== "queued"
      || !queuedMessagesReady
      || turnInProgress
      || sending
      || queuedDispatchRef.current
      || !conversation
      || !canChat(ally)
    ) return;

    queuedDispatchRef.current = true;
    commitQueuedMessages((messages) => messages.map(
      (message) => message.id === nextMessage.id ? { ...message, state: "dispatching" } : message,
    ));
    intentRef.current = {
      signature: `${conversation.id}:${nextMessage.content}`,
      key: nextMessage.intentKey,
      draftRevision: draftRevisionRef.current,
    };
    void sendMessageContent(nextMessage.content, nextMessage.intentKey, false)
      .then((accepted) => {
        if (accepted) {
          persistQueuedMessageTombstone(queuedMessagesStorageKey, nextMessage.id);
          if (mountedRef.current) {
            commitQueuedMessages((messages) => messages.filter((message) => message.id !== nextMessage.id));
          } else {
            persistQueuedMessages(
              queuedMessagesStorageKey,
              readLiveQueuedMessages(queuedMessagesStorageKey).filter((message) => message.id !== nextMessage.id),
            );
          }
          return;
        }
        const blockedMessages = readLiveQueuedMessages(queuedMessagesStorageKey).map(
          (message) => message.id === nextMessage.id ? { ...message, state: "blocked" as const } : message,
        );
        persistQueuedMessages(queuedMessagesStorageKey, blockedMessages);
        if (!mountedRef.current) return;
        commitQueuedMessages((messages) => messages.map(
          (message) => message.id === nextMessage.id ? { ...message, state: "blocked" } : message,
        ));
        setSendError("We couldn't send your queued message. Try again or remove it.");
      })
      .finally(() => {
        queuedDispatchRef.current = false;
      });
  }, [
    ally,
    commitQueuedMessages,
    conversation,
    queuedMessages,
    queuedMessagesReady,
    queuedMessagesStorageKey,
    sendMessageContent,
    sending,
    turnInProgress,
  ]);

  const retry = async (message: MessageViewModel) => {
    if (!conversation || retryingMessageId || !message.retryable) return;
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
    } catch {
      setAwaitingVisibleResponse(false);
      setRetryError("We couldn't retry that message. Try again in a moment.");
    } finally {
      setRetryingMessageId(null);
    }
  };

  const checkActivity = useCallback(async () => {
    if (
      !shouldPoll
      || !conversationId
      || pollingRef.current
      || document.visibilityState !== "visible"
      || !mountedRef.current
    ) return;
    if (pollCountRef.current >= ACTIVITY_POLL_LIMIT) {
      setPollBudgetReached(true);
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
      const snapshot = replayState?.conversationId === conversationId
        && replayState.cursor !== null
        && replayState.blocked === null
        ? await loadReplayWithRecovery(conversationId, controller.signal)
        : await session.runCloudOperation(() =>
          session.client.getActivities(workspaceId, conversationId, 200, controller.signal), {
            signal: controller.signal,
          });
      if (controller.signal.aborted || !mountedRef.current) return;
      if (!snapshot) return;
      if (hasVisibleAssistantText(snapshot)) {
        responseStartedRef.current = true;
        setAwaitingVisibleResponse(false);
      }
      setProjection((current) => projectActivitySnapshot(current, snapshot));
      setActivityError(null);
      setActivityHistoryError(null);
      setActivityReplayUnavailable(false);
      if (isActivityTerminal(snapshot.state)) {
        setActiveTurn(false);
        setAwaitingVisibleResponse(
          snapshot.state === "completed" && !responseStartedRef.current,
        );
        setPollingSettled(true);
        if (controller.signal.aborted || !mountedRef.current) return;
        preserveLatestConversationWindow(latestConversationMessages);
        await queryClient.invalidateQueries({
          queryKey: conversationQueryKey(workspaceId, ally.id),
        });
      }
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) {
        if (!handleActivityReplayFailure(error)) {
          setActivityError("We couldn't check the latest response status.");
          setActiveTurn(false);
          setAwaitingVisibleResponse(false);
          setPollingSettled(true);
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
    conversationId,
    handleActivityReplayFailure,
    latestConversationMessages,
    loadReplayWithRecovery,
    preserveLatestConversationWindow,
    queryClient,
    session,
    shouldPoll,
    workspaceId,
  ]);

  useEffect(() => {
    if (!conversationId || activityHistoryLoadedRef.current === conversationId) return;
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
        setProjection((current) => projectActivitySnapshot(current, snapshot));
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
        if (handleActivityReplayFailure(error)) return;
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
    if (!conversationId || !activeTurn) {
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
        setStreamConnected(true);
        setActivityError(null);
        activityRequestRef.current?.abort();
      },
      onEvent: (event) => {
        if (!mountedRef.current) return;
        if ("conversationId" in event && event.conversationId !== targetConversationId) {
          controller.abort();
          setStreamConnected(false);
          setActivityError("Live updates paused. Checking again…");
          return;
        }
        if (event.type === "activity") {
          if (event.activity.kind === "assistant_delta" && event.activity.text.trim()) {
            responseStartedRef.current = true;
            setAwaitingVisibleResponse(false);
          }
          setProjection((current) => projectActivitySnapshot(current, {
            conversationId: targetConversationId,
            activities: [event.activity],
            state: event.activity.state,
            lastContiguousSequence: event.activity.sequence,
            lastContiguousActivitySequence: event.activity.sequence,
            resumeCursor: event.cursor,
            nextCursor: null,
            latestSequence: event.activity.sequence,
          }));
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
          preserveLatestConversationWindow(latestConversationMessages);
          void queryClient.invalidateQueries({ queryKey: conversationQueryKey(workspaceId, ally.id) });
        }
      },
      onError: (error) => {
        if (!mountedRef.current || streamEndedNormally) return;
        setStreamConnected(false);
        if (error.status === 503) return;
        setActivityError("Live updates paused. Checking again…");
      },
    });
    activityStreamRef.current = stream;
    return () => {
      controller.abort();
      stream.close();
      if (activityStreamRef.current === stream) activityStreamRef.current = null;
      setStreamConnected(false);
    };
  }, [
    activeTurn,
    ally.id,
    conversationId,
    latestConversationMessages,
    preserveLatestConversationWindow,
    queryClient,
    workspaceId,
  ]);

  useEffect(() => {
    if (!shouldPoll) {
      activityRequestRef.current?.abort();
      return;
    }
    const interval = window.setInterval(() => void checkActivity(), ACTIVITY_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
      activityRequestRef.current?.abort();
    };
  }, [checkActivity, shouldPoll]);

  useEffect(() => {
    if (!followLatestRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      const canvas = messageCanvasRef.current;
      if (typeof canvas?.scrollTo === "function") {
        canvas.scrollTo({ top: canvas.scrollHeight, behavior: "smooth" });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [timelineSignature]);

  const unavailable = !canChat(ally);
  const unavailableNotice = provisioningNotice(ally);
  const allyAccent = resolveAllyAppearance(ally)?.color ?? "#ff5800";

  return (
    <div
      className={styles.conversation}
      style={{ "--ally-accent": allyAccent } as CSSProperties}
    >
      <header className={styles.threadHeader}>
        <Link href="/home" className={styles.backButton} aria-label="Back to Allies">
          <BackIcon />
        </Link>
        <span className={styles.threadAvatar}>
          <AllyIdentityAvatar ally={ally} size={44} sleeping={sleeping} />
        </span>
        <div className={styles.threadIdentity}>
          <h1>{ally.name}</h1>
          <p>{allySecondaryLine(ally)}</p>
        </div>
        <Link href="/account" className={`${styles.settingsButton} ${styles.mobileOnly}`} aria-label="Account settings">
          <SettingsIcon />
        </Link>
        <div className={styles.desktopThreadSettings} aria-label={`${ally.name} settings`}>
          <SettingsIcon />
          <span>{ally.name} settings</span>
        </div>
      </header>

      <div
        ref={messageCanvasRef}
        className={styles.messageCanvas}
        onScroll={(event) => {
          const canvas = event.currentTarget;
          followLatestRef.current = canvas.scrollHeight - canvas.scrollTop - canvas.clientHeight < 96;
        }}
      >
        {conversationQuery.isPending ? <p className={styles.quietState}>Opening your conversation…</p> : null}
        {conversationQuery.isError ? (
          <div className={styles.inlineError} role="alert">
            <span>We couldn&apos;t open this conversation.</span>
            <button type="button" onClick={() => void conversationQuery.refetch()}>Try again</button>
          </div>
        ) : null}
        {olderLoadError ? (
          <div className={styles.inlineError} role="alert">
            <span>{olderLoadError}</span>
            <button type="button" onClick={() => void loadOlder()}>Try again</button>
          </div>
        ) : nextCursor ? (
          <button className={styles.olderButton} type="button" onClick={() => void loadOlder()} disabled={loadingOlder}>
            {loadingOlder ? "Loading…" : "Earlier messages"}
          </button>
        ) : null}
        <div className={styles.messages}>
          {workspaceRefreshError ? <WorkspaceRefreshError onRetry={onRetryWorkspace} /> : null}
          {messages.map((message) => {
            const turn = message.sender === "user"
              ? projection.turns.find((candidate) => candidate.turnOrdinal === message.sequence)
              : undefined;
            const statusLabel = message.sender === "user" ? messageStatusLabel(message.status, turn) : null;
            const showAllyIdentity = message.sender === "assistant" && message.id === firstAssistantMessageId;
            return (
              <Fragment key={message.id}>
                <article
                  className={message.sender === "user" ? styles.userMessage : styles.allyMessage}
                >
                  {showAllyIdentity ? (
                    <div className={styles.messageIdentity}>
                      <AllyIdentityAvatar ally={ally} size={36} sleeping={sleeping} />
                      <strong>{ally.name}</strong>
                    </div>
                  ) : null}
                  <p>{message.content}</p>
                  {statusLabel ? <span>{statusLabel}</span> : null}
                  {message.sender === "user" && message.retryable && !retriedMessageIds.has(message.id) ? (
                    <button
                      type="button"
                      className={styles.retryButton}
                      onClick={() => void retry(message)}
                      disabled={retryingMessageId !== null}
                    >
                      {retryingMessageId === message.id ? "Retrying…" : "Retry"}
                    </button>
                  ) : null}
                </article>
                {turn ? <AssistantTurn turn={turn} streaming={shouldPoll || streamConnected} /> : null}
              </Fragment>
            );
          })}
          {gettingReady ? (
            <div className={styles.thinkingState} role="status" aria-live="polite">
              <AllyIdentityAvatar ally={ally} size={32} thinking />
              <ShinyText color="var(--ally-accent)" shineColor="#ffffff">Getting ready</ShinyText>
            </div>
          ) : showThinkingState ? (
            <div className={styles.thinkingState} role="status" aria-live="polite">
              <AllyIdentityAvatar ally={ally} size={32} thinking />
              <ShinyText color="var(--ally-accent)" shineColor="#ffffff">Thinking</ShinyText>
            </div>
          ) : null}
          {!shouldPoll && projection.state === "awaiting_action" ? (
            <p className={styles.turnState}>This Ally needs an action Home cannot complete yet.</p>
          ) : null}
          {!shouldPoll && (projection.state === "failed" || projection.state === "stopped") ? (
            <p className={styles.turnState}>This response {projection.state === "failed" ? "failed" : "stopped"}.</p>
          ) : null}
          {!shouldPoll && isActivityTerminal(projection.state) ? (
            projection.pendingActivities?.filter((activity) => activity.kind === "assistant_delta" && activity.text).map((activity) => (
              <article
                className={styles.allyMessage}
                data-testid={`activity-pending-${activity.sequence}`}
                key={activity.id}
              >
                <p>{activity.text}</p>
              </article>
            ))
          ) : null}
          {!shouldPoll && isActivityTerminal(projection.state) && projection.pendingActivities?.some(
            (activity) => activity.kind === "assistant_delta" && activity.text,
          ) ? (
            <p className={styles.turnState}>Some response text arrived out of order.</p>
          ) : null}
          {pollBudgetReached ? (
            <div className={styles.inlineError}>
              <span>Status checking paused after two minutes.</span>
              <button type="button" onClick={() => { pollCountRef.current = 0; setPollBudgetReached(false); setPollingSettled(false); setActiveTurn(true); }}>
                Check again
              </button>
            </div>
          ) : null}
          {activityError ? (
            <div className={styles.inlineError} role="alert">
              <span>{activityError}</span>
              <button type="button" onClick={() => { setActivityError(null); setPollingSettled(false); setActiveTurn(true); }}>
                Check again
              </button>
            </div>
          ) : null}
          {activityReplayUnavailable ? (
            <p className={styles.inlineError} role="alert">Activity history is unavailable.</p>
          ) : null}
          {activityHistoryError ? (
            <div className={styles.inlineError} role="alert">
              <span>{activityHistoryError}</span>
              <button type="button" onClick={retryActivityHistory}>Check again</button>
            </div>
          ) : null}
          {retryError ? <p className={styles.composerError} role="alert">{retryError}</p> : null}
        </div>
      </div>

      <footer className={styles.composerArea}>
        {unavailableNotice ? <p className={styles.composerNotice}>{unavailableNotice}</p> : null}
        {sendError ? <p className={styles.composerError} role="alert">{sendError}</p> : null}
        {queuedMessages.length ? (
          <ol className={styles.queuedMessages} aria-label="Queued messages">
            {queuedMessages.map((message) => (
              <li key={message.id}>
                <span title={message.content}>{message.content}</span>
                {message.state === "blocked" ? (
                  <button
                    type="button"
                    onClick={() => {
                      setSendError(null);
                      commitQueuedMessages((messages) => messages.map(
                        (item) => item.id === message.id ? { ...item, state: "queued" } : item,
                      ));
                    }}
                  >
                    Try again
                  </button>
                ) : null}
                {message.state !== "dispatching" ? (
                  <button
                    type="button"
                    aria-label="Remove queued message"
                    onClick={() => removeQueuedMessage(message.id)}
                  >
                    <TrashIcon />
                  </button>
                ) : null}
              </li>
            ))}
          </ol>
        ) : null}
        <div className={styles.composer}>
          <label className={styles.srOnly} htmlFor="ally-message">Message {ally.name}</label>
          <span className={styles.composerPlus} aria-hidden="true">+</span>
          <textarea
            id="ally-message"
            value={draft}
            onChange={(event) => {
              const beganInteracting = !draftRef.current.trim() && Boolean(event.target.value.trim());
              draftRevisionRef.current += 1;
              draftRef.current = event.target.value;
              setDraft(event.target.value);
              if (beganInteracting) onActivity();
              observeEdit(event.target.value);
            }}
            onCompositionStart={compositionStart}
            onCompositionEnd={(event) => compositionEnd(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder="Message"
            rows={1}
            maxLength={16_000}
            disabled={unavailable || conversationQuery.isError}
          />
          <button
            type="button"
            aria-label="Send message"
            onClick={() => void submit()}
            disabled={unavailable || !queuedMessagesReady || sending || !draft.trim() || !conversation}
          >
            {draft.trim() ? <SendIcon /> : <MicIcon />}
          </button>
        </div>
      </footer>
    </div>
  );
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

function EmptyThread({ title, detail, action }: { title: string; detail: string; action?: React.ReactNode }) {
  return (
    <div className={styles.emptyThread}>
      <div className={styles.emptyAlly} aria-hidden="true">
        <AllyAvatar shape="ghosty" color="#ff5800" size={92} label="" />
      </div>
      <h1>{title}</h1>
      <p>{detail}</p>
      {action ? <div className={styles.emptyAction}>{action}</div> : null}
    </div>
  );
}

function mergeMessages(...groups: MessageViewModel[][]): MessageViewModel[] {
  const byId = new Map<string, MessageViewModel>();
  for (const group of groups) for (const message of group) byId.set(message.id, message);
  return [...byId.values()].sort((left, right) => left.sequence - right.sequence || left.id.localeCompare(right.id));
}

function canChat(ally: AllyViewModel): boolean {
  return ally.provisioningState === "bound";
}

function isGettingReady(ally: AllyViewModel): boolean {
  return ally.provisioningState === "pending";
}

function allySecondaryLine(ally: AllyViewModel): string {
  if (ally.provisioningState === "bound") return ally.job;
  return provisioningLabel(ally.provisioningState);
}

function provisioningLabel(state: AllyViewModel["provisioningState"]): string {
  return {
    pending: "Getting ready",
    retryable: "Setup needs retry",
    failed: "Setup failed",
    incompatible: "Needs an update",
    repair_required: "Needs repair",
    bound: "Ready",
  }[state];
}

function provisioningNotice(ally: AllyViewModel): string | null {
  if (isGettingReady(ally) || ally.provisioningState === "bound") return null;
  if (ally.provisioningState === "retryable") return `${ally.name}'s setup can be retried outside Home.`;
  if (ally.provisioningState === "failed") return `${ally.name}'s setup failed.`;
  if (ally.provisioningState === "repair_required") return `${ally.name} needs repair before messaging.`;
  return `${ally.name} needs an update before messaging.`;
}

function AssistantTurn({ turn, streaming }: { turn: AssistantTurnProjection; streaming: boolean }) {
  const isStreaming = streaming && turn.state === "running";
  if (turn.state === "reconciliation_needed") {
    return (
      <article className={styles.allyMessage} data-testid={`activity-reply-${turn.turnOrdinal}`}>
        <p>This response needs review because some activity arrived out of order.</p>
      </article>
    );
  }
  if (turn.state === "failed" || turn.state === "stopped") {
    return (
      <article className={styles.allyMessage} data-testid={`activity-reply-${turn.turnOrdinal}`}>
        <p>{turn.state === "stopped" ? "This response was stopped." : "This response failed. Try sending your message again."}</p>
      </article>
    );
  }
  if (!turn.assistantText) return null;
  return (
    <article className={styles.allyMessage} data-testid={`activity-reply-${turn.turnOrdinal}`}>
      <Streamdown
        className={styles.streamingMarkdown}
        mode={isStreaming ? "streaming" : "static"}
        parseIncompleteMarkdown
        animated={isStreaming ? { animation: "blurIn", sep: "word", duration: 180, stagger: 24 } : false}
        isAnimating={isStreaming}
      >
        {turn.assistantText}
      </Streamdown>
    </article>
  );
}

function messageStatusLabel(
  status: MessageViewModel["status"],
  turn?: AssistantTurnProjection,
): string | null {
  if (turn) {
    return {
      queued: null,
      running: null,
      awaiting_action: "Needs action",
      completed: null,
      failed: "Failed",
      stopped: "Stopped",
      reconciliation_needed: "Needs review",
    }[turn.state];
  }
  return {
    queued: null,
    in_progress: null,
    awaiting_action: "Needs action",
    completed: null,
    failed: "Failed",
    stopped: "Stopped",
  }[status];
}

function activityStateFromMessage(status: MessageViewModel["status"]): ActivityState {
  return status === "in_progress" ? "running" : status;
}

function initials(name: string): string {
  const value = name.trim();
  if (!value) return "A";
  return value.split(/\s+/u).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

function PlusIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>;
}

function SearchIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="10.8" cy="10.8" r="5.8" /><path d="m15.2 15.2 4.3 4.3" /></svg>;
}

function SettingsIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m9.9 3.8.4-1.1h3.4l.4 1.1c.3.1.7.3 1 .5l1.1-.4 2.4 2.4-.4 1.1c.2.3.4.6.5 1l1.1.4v3.4l-1.1.4c-.1.3-.3.7-.5 1l.4 1.1-2.4 2.4-1.1-.4c-.3.2-.6.4-1 .5l-.4 1.1h-3.4l-.4-1.1c-.3-.1-.7-.3-1-.5l-1.1.4-2.4-2.4.4-1.1c-.2-.3-.4-.6-.5-1l-1.1-.4V8.8l1.1-.4c.1-.3.3-.7.5-1l-.4-1.1 2.4-2.4 1.1.4c.3-.2.6-.4 1-.5Z" /><circle cx="12" cy="10.5" r="2.4" /></svg>;
}

function BackIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6" /></svg>;
}

function SendIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m6 12 6-6 6 6M12 6v12" /></svg>;
}

function MicIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v4M9 21h6" /></svg>;
}

function parseQueuedMessages(stored: string | null): QueuedMessage[] {
  try {
    if (!stored) return [];
    const value: unknown = JSON.parse(stored);
    if (!Array.isArray(value)) return [];
    return value.flatMap((message, index): QueuedMessage[] => {
      if (!message || typeof message !== "object") return [];
      const item = message as Partial<QueuedMessage>;
      const valid = typeof item.id === "string"
        && typeof item.content === "string"
        && item.content.length > 0
        && item.content.length <= 16_000
        && typeof item.intentKey === "string";
      if (!valid) return [];
      return [{
        id: item.id!,
        content: item.content!,
        intentKey: item.intentKey!,
        queuedAt: typeof item.queuedAt === "number" && Number.isFinite(item.queuedAt) ? item.queuedAt : index,
        state: item.state === "dispatching" || item.state === "blocked" ? item.state : "queued",
      }];
    });
  } catch {
    return [];
  }
}

function readQueuedMessages(storageKey: string): QueuedMessage[] {
  try {
    return parseQueuedMessages(window.localStorage.getItem(storageKey));
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
  for (const group of groups) for (const message of group) byId.set(message.id, message);
  return [...byId.values()].sort(
    (left, right) => left.queuedAt - right.queuedAt || left.id.localeCompare(right.id),
  );
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
    return new Set(listQueuedMessageTombstones(storageKey)
      .map((tombstone) => tombstone.id));
  } catch {
    return new Set();
  }
}

function persistQueuedMessageTombstone(storageKey: string, messageId: string) {
  try {
    window.localStorage.setItem(
      `${queuedMessageTombstonePrefix(storageKey)}${encodeURIComponent(messageId)}`,
      String(Date.now()),
    );
    listQueuedMessageTombstones(storageKey)
      .sort((left, right) => right.removedAt - left.removedAt)
      .forEach((tombstone, index) => {
        if (index >= QUEUED_MESSAGE_TOMBSTONE_LIMIT) {
          window.localStorage.removeItem(tombstone.key);
        }
      });
  } catch {
    // The in-memory queue still honors the removal when browser storage is unavailable.
  }
}

function persistQueuedMessages(storageKey: string, messages: QueuedMessage[]) {
  try {
    if (messages.length) {
      window.localStorage.setItem(storageKey, JSON.stringify(messages));
    } else {
      window.localStorage.removeItem(storageKey);
    }
  } catch {
    // The queue still works for this page session when browser storage is unavailable.
  }
}

function TrashIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></svg>;
}
