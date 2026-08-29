"use client";

import type {
  ActivityState,
  AllyViewModel,
  MessageViewModel,
} from "@allies/cloud-client";
import {
  EMPTY_ACTIVITY_PROJECTION,
  isActivityTerminal,
  projectActivitySnapshot,
  type ActivityProjection,
  type AssistantTurnProjection,
} from "@allies/cloud-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import Onboarding from "../(onboarding)/_components";
import { OnboardingStateProvider } from "../(onboarding)/_store/onboarding-store";
import { AllyAvatar, ALLY_SHAPES, type AllyShape } from "../../components/ally-avatar";
import { currentAccountQueryOptions } from "../../lib/account/account-query";
import { AuthenticatedAllyFlowProvider } from "../../lib/allies/authenticated-onboarding-flow";
import { alliesQueryOptions, conversationQueryKey } from "../../lib/allies/queries";
import { alliesQueryKey } from "../../lib/allies/query-keys";
import { useSession } from "../../lib/session/session-context";
import {
  WAITLIST_APPEARANCE_CATALOG_VERSION,
  WAITLIST_COLORS,
} from "../../lib/waitlist/catalog";

import styles from "./home.module.css";

const ACTIVITY_INTERVAL_MS = 500;
const ACTIVITY_POLL_LIMIT = 240;
const DESKTOP_QUERY = "(min-width: 1024px)";
const EMPTY_MESSAGES: MessageViewModel[] = [];

function subscribeToDesktopQuery(callback: () => void) {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => undefined;
  }
  const mediaQuery = window.matchMedia(DESKTOP_QUERY);
  if (typeof mediaQuery.addEventListener === "function") {
    mediaQuery.addEventListener("change", callback);
    return () => mediaQuery.removeEventListener("change", callback);
  }
  if (typeof mediaQuery.addListener !== "function") return () => undefined;
  mediaQuery.addListener(callback);
  return () => {
    if (typeof mediaQuery.removeListener === "function") mediaQuery.removeListener(callback);
  };
}

function getDesktopQuerySnapshot() {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia(DESKTOP_QUERY).matches;
}

function useIsDesktop() {
  return useSyncExternalStore(subscribeToDesktopQuery, getDesktopQuerySnapshot, () => false);
}

export function HomeWorkspace({ selectedAllyId }: { selectedAllyId: string | null }) {
  const session = useSession();
  const queryClient = useQueryClient();
  const sessionStatus = session.state.status;
  const restoreSession = session.restore;
  const router = useRouter();
  const restoreStarted = useRef(false);
  const redirectStarted = useRef(false);
  const defaultSelectionRef = useRef<string | null>(null);
  const isDesktop = useIsDesktop();

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
  const selectedAlly = selectedAllyId
    ? allies.find((ally) => ally.id === selectedAllyId) ?? null
    : null;
  const creatingAlly = selectedAllyId === "new";

  useEffect(() => {
    if (
      !isDesktop
      || selectedAllyId
      || alliesQuery.isPending
      || alliesQuery.isFetching
      || !accountQuery.data
      || allies.length === 0
    ) return;
    const firstAlly = allies[0];
    if (!firstAlly || defaultSelectionRef.current === firstAlly.id) return;
    defaultSelectionRef.current = firstAlly.id;
    router.replace(`/home/${encodeURIComponent(firstAlly.id)}`);
  }, [allies, alliesQuery.isFetching, alliesQuery.isPending, accountQuery.data, isDesktop, router, selectedAllyId]);

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
    <main className={styles.page}>
      <section
        className={`${styles.roster} ${selectedAllyId ? styles.rosterHiddenOnMobile : ""}`}
        aria-label="Ally conversations"
      >
        <header className={styles.rosterHeader}>
          <div>
            <span className={styles.eyebrow}>Allies</span>
            <h2 className={styles.rosterTitle}>Your people</h2>
          </div>
          <Link
            className={styles.newAllyButton}
            href="/home/new"
            aria-label="Meet another Ally"
          >
            <PlusIcon />
          </Link>
        </header>

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
          <Link href="/account" className={styles.accountLink}>
            <span className={styles.accountMark} aria-hidden="true">
              {initials(accountQuery.data.displayName)}
            </span>
            <span>{accountQuery.data.displayName || "Your account"}</span>
          </Link>
        </footer>
      </section>

      <section
        className={`${styles.thread} ${!selectedAllyId ? styles.threadHiddenOnMobile : ""}`}
        aria-label="Selected Ally conversation"
      >
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

function AllyIdentityAvatar({ ally, size }: { ally: AllyViewModel; size: number }) {
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
      state={ally.provisioningState === "pending" ? "thinking" : "idle"}
      size={size}
      label=""
    />
  );
}

function AllyConversationRow({ ally, selected }: { ally: AllyViewModel; selected: boolean }) {
  return (
    <Link
      href={`/home/${encodeURIComponent(ally.id)}`}
      className={`${styles.allyRow} ${selected ? styles.allyRowSelected : ""}`}
      aria-current={selected ? "page" : undefined}
    >
      <AllyIdentityAvatar ally={ally} size={52} />
      <span className={styles.allyCopy}>
        <strong>{ally.name}</strong>
        <span>{allySecondaryLine(ally)}</span>
      </span>
    </Link>
  );
}

function ConversationPane({
  workspaceId,
  ally,
  workspaceRefreshError,
  onRetryWorkspace,
}: {
  workspaceId: string;
  ally: AllyViewModel;
  workspaceRefreshError: boolean;
  onRetryWorkspace: () => void;
}) {
  const session = useSession();
  const queryClient = useQueryClient();
  const [olderMessages, setOlderMessages] = useState<MessageViewModel[]>([]);
  const [nextCursorOverride, setNextCursorOverride] = useState<string | null | undefined>(undefined);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderLoadError, setOlderLoadError] = useState<string | null>(null);
  const [sentMessages, setSentMessages] = useState<MessageViewModel[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activityHistoryError, setActivityHistoryError] = useState<string | null>(null);
  const intentRef = useRef<{ signature: string; key: string; draftRevision: number } | null>(null);
  const draftRevisionRef = useRef(0);
  const [activeTurn, setActiveTurn] = useState(false);
  const [pollingSettled, setPollingSettled] = useState(false);
  const [pollBudgetReached, setPollBudgetReached] = useState(false);
  const [projection, setProjection] = useState<ActivityProjection>(EMPTY_ACTIVITY_PROJECTION);
  const pollingRef = useRef(false);
  const pollCountRef = useRef(0);
  const activityHistoryLoadedRef = useRef<string | null>(null);
  const [activityHistoryRetry, setActivityHistoryRetry] = useState(0);
  const activityRequestRef = useRef<AbortController | null>(null);
  const activitySnapshotRequestRef = useRef<AbortController | null>(null);
  const turnGenerationRef = useRef(0);
  const olderRequestRef = useRef<AbortController | null>(null);
  const historyRevisionRef = useRef(0);
  const mountedRef = useRef(true);
  const messageCanvasRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activityRequestRef.current?.abort();
      activitySnapshotRequestRef.current?.abort();
      olderRequestRef.current?.abort();
    };
  }, []);

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
  const shouldPoll = activeTurn || (!pollingSettled && persistedTurnActive);
  const conversationId = conversation?.id;

  const messages = useMemo(
    () => mergeMessages(olderMessages, latestConversationMessages, sentMessages),
    [latestConversationMessages, olderMessages, sentMessages],
  );
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

  const refreshActivitySnapshot = useCallback(async (targetConversationId: string) => {
    if (!mountedRef.current) return;
    activitySnapshotRequestRef.current?.abort();
    const controller = new AbortController();
    activitySnapshotRequestRef.current = controller;
    try {
      const snapshot = await session.runCloudOperation((signal) =>
        session.client.getActivities(workspaceId, targetConversationId, 200, signal), {
          signal: controller.signal,
        });
      if (controller.signal.aborted || !mountedRef.current) return;
      setProjection((current) => projectActivitySnapshot(current, snapshot));
      setActivityError(null);
      setActivityHistoryError(null);
    } catch {
      if (!controller.signal.aborted && mountedRef.current) {
        setActivityError("We couldn't check the latest response status.");
      }
    } finally {
      if (activitySnapshotRequestRef.current === controller) {
        activitySnapshotRequestRef.current = null;
      }
    }
  }, [session, workspaceId]);

  const submit = async () => {
    if (!conversation || sending || !canChat(ally)) return;
    const content = draft.trim();
    if (!content) return;
    const signature = `${conversation.id}:${content}`;
    const key = intentRef.current?.signature === signature
      && intentRef.current.draftRevision === draftRevisionRef.current
      ? intentRef.current.key
      : `message-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`;
    const preservedOlderMessages = olderMessages;
    const preservedCursor = nextCursorOverride;
    turnGenerationRef.current += 1;
    intentRef.current = { signature, key, draftRevision: draftRevisionRef.current };
    activityRequestRef.current?.abort();
    activitySnapshotRequestRef.current?.abort();
    followLatestRef.current = true;
    setSending(true);
    setSendError(null);
    try {
      const accepted = await session.runCloudOperation(
        (signal) => session.client.sendMessage(workspaceId, conversation.id, content, key, signal),
        { csrf: true },
      );
      setSentMessages((current) => mergeMessages(current, [accepted.message]));
      setDraft((current) => (current === content ? "" : current));
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
    } catch {
      setSendError("Your message wasn't accepted. Try the same message again.");
    } finally {
      setSending(false);
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
      setPollingSettled(true);
      return;
    }
    activityRequestRef.current?.abort();
    const controller = new AbortController();
    activityRequestRef.current = controller;
    pollingRef.current = true;
    pollCountRef.current += 1;
    try {
      const snapshot = await session.runCloudOperation((signal) =>
        session.client.getActivities(workspaceId, conversationId, 200, signal), {
          signal: controller.signal,
        });
      if (controller.signal.aborted || !mountedRef.current) return;
      setProjection((current) => projectActivitySnapshot(current, snapshot));
      setActivityError(null);
      if (isActivityTerminal(snapshot.state)) {
        setActiveTurn(false);
        setPollingSettled(true);
        if (controller.signal.aborted || !mountedRef.current) return;
        preserveLatestConversationWindow(latestConversationMessages);
        await queryClient.invalidateQueries({
          queryKey: conversationQueryKey(workspaceId, ally.id),
        });
      }
    } catch {
      if (!controller.signal.aborted && mountedRef.current) {
        setActivityError("We couldn't check the latest response status.");
        setActiveTurn(false);
        setPollingSettled(true);
      }
    } finally {
      if (activityRequestRef.current === controller) {
        activityRequestRef.current = null;
        pollingRef.current = false;
      }
    }
  }, [ally.id, conversationId, latestConversationMessages, preserveLatestConversationWindow, queryClient, session, shouldPoll, workspaceId]);

  useEffect(() => {
    if (!conversationId || activityHistoryLoadedRef.current === conversationId) return;
    activityHistoryLoadedRef.current = conversationId;
    const generationAtStart = turnGenerationRef.current;
    const controller = new AbortController();
    setActivityHistoryError(null);
    void session.runCloudOperation((signal) =>
      session.client.getActivities(workspaceId, conversationId, 200, signal), {
        signal: controller.signal,
      })
      .then((snapshot) => {
        if (controller.signal.aborted || !mountedRef.current) return;
        setProjection((current) => projectActivitySnapshot(current, snapshot));
        setActivityHistoryError(null);
        setActivityError(null);
        if (isActivityTerminal(snapshot.state) && turnGenerationRef.current === generationAtStart) {
          setActiveTurn(false);
          setPollingSettled(true);
        }
      })
      .catch(() => {
        if (controller.signal.aborted || !mountedRef.current) return;
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
    };
  }, [activityHistoryRetry, conversationId, session, workspaceId]);

  const retryActivityHistory = () => {
    activityHistoryLoadedRef.current = null;
    setActivityHistoryError(null);
    setActivityHistoryRetry((current) => current + 1);
  };

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

  return (
    <div className={styles.conversation}>
      <header className={styles.threadHeader}>
        <Link href="/home" className={`${styles.backButton} ${styles.mobileOnly}`} aria-label="Back to Allies">
          <BackIcon />
        </Link>
        <AllyIdentityAvatar ally={ally} size={44} />
        <div className={styles.threadIdentity}>
          <h1>{ally.name}</h1>
          <p>{allySecondaryLine(ally)}</p>
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
            return (
              <Fragment key={message.id}>
                <article
                  className={message.sender === "user" ? styles.userMessage : styles.allyMessage}
                >
                  <p>{message.content}</p>
                  {statusLabel ? <span>{statusLabel}</span> : null}
                </article>
                {turn ? <AssistantTurn turn={turn} /> : null}
              </Fragment>
            );
          })}
          {shouldPoll ? <p className={styles.turnState} aria-live="polite">{ally.name} is working…</p> : null}
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
          {activityHistoryError ? (
            <div className={styles.inlineError} role="alert">
              <span>{activityHistoryError}</span>
              <button type="button" onClick={retryActivityHistory}>Check again</button>
            </div>
          ) : null}
        </div>
      </div>

      <footer className={styles.composerArea}>
        {unavailable ? <p className={styles.composerNotice}>{provisioningNotice(ally)}</p> : null}
        {sendError ? <p className={styles.composerError} role="alert">{sendError}</p> : null}
        <div className={styles.composer}>
          <label className={styles.srOnly} htmlFor="ally-message">Message {ally.name}</label>
          <textarea
            id="ally-message"
            value={draft}
            onChange={(event) => {
              draftRevisionRef.current += 1;
              setDraft(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.nativeEvent.isComposing) return;
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder={`Message ${ally.name}`}
            rows={1}
            maxLength={16_000}
            disabled={unavailable || conversationQuery.isError}
          />
          <button
            type="button"
            aria-label="Send message"
            onClick={() => void submit()}
            disabled={unavailable || sending || !draft.trim() || !conversation}
          >
            <SendIcon />
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

function allySecondaryLine(ally: AllyViewModel): string {
  if (ally.provisioningState === "bound") return ally.job;
  return provisioningLabel(ally.provisioningState);
}

function provisioningLabel(state: AllyViewModel["provisioningState"]): string {
  return {
    pending: "Getting ready",
    retryable: "Setup can be retried",
    failed: "Setup failed",
    incompatible: "Needs an update",
    repair_required: "Needs repair",
    bound: "Ready",
  }[state];
}

function provisioningNotice(ally: AllyViewModel): string {
  if (ally.provisioningState === "pending") return `${ally.name} is still getting ready.`;
  if (ally.provisioningState === "retryable") return `${ally.name}'s setup can be retried outside Home.`;
  if (ally.provisioningState === "failed") return `${ally.name}'s setup failed.`;
  if (ally.provisioningState === "repair_required") return `${ally.name} needs repair before messaging.`;
  return `${ally.name} needs an update before messaging.`;
}

function AssistantTurn({ turn }: { turn: AssistantTurnProjection }) {
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
      <p>{turn.assistantText}</p>
    </article>
  );
}

function messageStatusLabel(
  status: MessageViewModel["status"],
  turn?: AssistantTurnProjection,
): string | null {
  if (turn) {
    return {
      queued: "Queued",
      running: "Working",
      awaiting_action: "Needs action",
      completed: null,
      failed: "Failed",
      stopped: "Stopped",
      reconciliation_needed: "Needs review",
    }[turn.state];
  }
  return {
    queued: "Queued",
    in_progress: "Working",
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

function BackIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6" /></svg>;
}

function SendIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m6 12 6-6 6 6M12 6v12" /></svg>;
}
