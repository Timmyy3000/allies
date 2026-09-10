"use client";

import type {
  AssistantReplyViewModel,
  ActivitySnapshotViewModel,
  ActivityState,
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
} from "react";

import Onboarding from "../(onboarding)/_components";
import OnboardingDrawer from "../(onboarding)/_components/onboarding-drawer";
import { hasOnboardingResumePending } from "../(onboarding)/_store/onboarding-resume";
import { OnboardingStateProvider } from "../(onboarding)/_store/onboarding-store";
import { AllyAvatar, ALLY_SHAPES, type AllyShape } from "../../components/ally-avatar";
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
import { getActivitySseEnabled, getCreationWakeEnabled, getWebEnvironment } from "../../lib/env";
import { useSession } from "../../lib/session/session-context";
import { InstallInvitation } from "../../lib/pwa/pwa-install";
import {
  WAITLIST_APPEARANCE_CATALOG_VERSION,
  WAITLIST_COLORS,
} from "../../lib/waitlist/catalog";

import {
  buildRoutineActionIdempotencyKey,
  buildRoutineActionEvidence,
  buildRoutineActionMessage,
  buildProductionConversationFrameModel,
  type ProductionQueuedMessageModel,
  type ProductionConversationFrameActions,
  type ProductionRoutineActionState,
  type RoutineActionRequest,
} from "./conversation-frame-model";
import {
  classifyConversationAccessError,
  type ConversationAccessFailure,
} from "./conversation-access-error";
import { ConversationFrame } from "./conversation-frame";
import { ConversationApprovals, type ApprovalClient } from "./conversation-approvals";
import { MobileHomeRosterExact } from "./_exact/mobile-home-roster-exact";
import { HomeReadySplash } from "./home-ready-splash";
import { useIsMobileHome } from "./use-is-mobile-home";
import styles from "./home.module.css";

const ACTIVITY_INTERVAL_MS = 500;
const DURABLE_REPLY_SNAPSHOT_INTERVAL_MS = 3_000;
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
export const ALLY_SLEEP_AFTER_MS = 10 * 60 * 1_000;
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

export function hasOnboardingExchange(
  messages: readonly MessageViewModel[],
  greeting: string,
  reply: string,
): boolean {
  return messages.some((message) => message.sender === "assistant" && message.sequence === 1 && message.content === greeting)
    && messages.some((message) => message.sender === "user" && message.sequence === 2 && message.content === reply);
}

type QueuedMessage = {
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
  const creatingAlly = selectedAllyId === "new";
  const isMobileHome = useIsMobileHome();
  const isDesktopDashboard = !isMobileHome;
  const [createOverlayOpen, setCreateOverlayOpen] = useState(false);
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

  if (!creatingAlly && dismissedCreateRoute) {
    setDismissedCreateRoute(false);
  }

  if (creatingAlly && !createOverlayOpen && !dismissedCreateRoute) {
    setCreateOverlayOpen(true);
  }

  const openCreateOverlay = useCallback(() => {
    pendingCreatedAllyId.current = null;
    setDismissedCreateRoute(false);
    setCreateOverlayOpen(true);
  }, []);

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
    return (
      <main className={isMobileHome ? styles.exactMobileHost : styles.exactHost}>
        {isMobileHome ? <MobileHomeRosterExact allies={<></>} actions={<></>} createControl={<></>} /> : null}
        <HomeReadySplash />
      </main>
    );
  }

  const invalidSelection = Boolean(selectedAllyId && !creatingAlly && !conversationAlly);
  const showDesktopDashboard = isDesktopDashboard;
  const showThread = Boolean(selectedAllyId) || showDesktopDashboard || Boolean(activeHandoff);

  const threadBody = conversationAlly ? (
    <ConversationPane
      key={conversationAlly.id}
      userId={accountQuery.data.userId}
      workspaceId={workspaceId}
      canApprove={accountQuery.data.workspace.capabilities.includes("profile.write")}
      ally={conversationAlly}
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
          <OnboardingStateProvider initialStep="name">
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
          <button type="button" className={`${styles.exactMobileAction} ${styles.exactMobileActionCreate}`} style={{ cursor: "default" }} aria-label="Chef" disabled>
            <ChefIcon />
          </button>
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
      <div className={styles.sidebarTabs} aria-label="Sidebar views">
        <button type="button" className={styles.sidebarTab} aria-pressed="true">My allies</button>
        <button type="button" className={`${styles.sidebarTab} ${styles.sidebarTabMuted}`} disabled>Routines</button>
      </div>
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
        <button type="button" className={styles.exactMobileCreate} aria-label="Make an Ally" onClick={openCreateOverlay}>Make an ally</button>
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
      {createOverlay}
      {!selectedAllyId && !createOverlayOpen ? <InstallInvitation /> : null}
    </main>
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
  exact = false,
}: {
  ally: AllyViewModel;
  selected: boolean;
  preview?: AllyPreview;
  sleepClock: number | null;
  recentActivityAt?: number;
  exact?: boolean;
}) {
  const latestMessage = preview?.latestMessage ?? null;
  const sleeping = isAllySleeping(ally, latestMessage, sleepClock, recentActivityAt);
  return (
    <Link
      href={`/home/${encodeURIComponent(ally.id)}`}
      className={`${styles.allyRow} ${selected ? styles.allyRowSelected : ""} ${exact ? styles.exactAllyRow : ""}`}
      aria-current={selected ? "page" : undefined}
      data-ally-sleeping={sleeping ? "true" : "false"}
    >
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
  sleeping,
  stateReady,
  userId,
  workspaceId,
  canApprove,
  ally,
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
  const approvalClient = useMemo<ApprovalClient>(() => ({
    getApprovals: (workspace, conversation, signal) => session.runCloudOperation((operationSignal) => session.client.getApprovals(workspace, conversation, operationSignal), { signal }),
    getApproval: (workspace, conversation, approval, signal) => session.runCloudOperation((operationSignal) => session.client.getApproval(workspace, conversation, approval, operationSignal), { signal }),
    decideApproval: (workspace, conversation, approval, decision, key, signal) => session.runCloudOperation((operationSignal) => session.client.decideApproval(workspace, conversation, approval, decision, key, operationSignal), { signal, csrf: true, retryTransient: false }),
  }), [session]);
  const queryClient = useQueryClient();
  const [olderMessages, setOlderMessages] = useState<MessageViewModel[]>([]);
  const [nextCursorOverride, setNextCursorOverride] = useState<string | null | undefined>(undefined);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderLoadError, setOlderLoadError] = useState<string | null>(null);
  const [sentMessages, setSentMessages] = useState<MessageViewModel[]>([]);
  const [immediateMessageIds, setImmediateMessageIds] = useState<ReadonlySet<string>>(() => new Set());
  const [draft, setDraft] = useState("");
  const [selectedRoutineId, setSelectedRoutineId] = useState<string | null>(null);
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
  const [pollBudgetReached, setPollBudgetReached] = useState(false);
  const [projection, setProjection] = useState<ActivityProjection>(EMPTY_ACTIVITY_PROJECTION);
  const [activityPresentation, setActivityPresentation] = useState<ActivityPresentationState>(
    EMPTY_ACTIVITY_PRESENTATION,
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
  const requestRuntimeIntent = useCallback(
    (targetAllyId: string, occurredAt: string, idempotencyKey: string, signal?: AbortSignal) =>
      session.runCloudOperation(
        (operationSignal) => session.client.requestRuntimeIntent(targetAllyId, occurredAt, idempotencyKey, operationSignal),
        { csrf: true, retryTransient: true, signal },
      ),
    [session],
  );
  const { observeEdit, compositionStart, compositionEnd, status: runtimeIntentStatus } = useComposingRuntimeIntent(
    ally.id,
    requestRuntimeIntent,
  );

  const presentAssistantReply = useCallback((conversationId: string, reply: AssistantReplyViewModel) => {
    setAssistantReplyState((current) => mergeAssistantReplyState(current, conversationId, [reply]));
  }, []);

  const presentActivitySnapshot = useCallback((snapshot: ActivitySnapshotViewModel) => {
    if (snapshot.assistantReply) presentAssistantReply(snapshot.conversationId, snapshot.assistantReply);
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
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchInterval: (query) => query.state.error
      ? ERROR_CONVERSATION_SNAPSHOT_INTERVAL_MS
      : query.state.data?.queue && query.state.data.queue.length > 0
        ? QUEUE_SNAPSHOT_INTERVAL_MS
        : IDLE_CONVERSATION_SNAPSHOT_INTERVAL_MS,
    refetchIntervalInBackground: false,
    queryFn: ({ signal }) =>
      session.runCloudOperation(
        (operationSignal) =>
          session.client.getAllyConversation(workspaceId, ally.id, { limit: 50, signal: operationSignal }),
        { signal },
      ),
  });
  const conversation = conversationQuery.data;
  const latestConversationMessages = conversation?.messages ?? EMPTY_MESSAGES;
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
  );
  const waitingForVisibleResponse = awaitingVisibleResponse && !responseStarted;
  const shouldPoll = activeTurn || waitingForVisibleResponse || (!pollingSettled && persistedTurnActive);
  const activityPollInterval = streamConnected
    ? DURABLE_REPLY_SNAPSHOT_INTERVAL_MS
    : ACTIVITY_INTERVAL_MS;
  const showThinkingState = sending
    || turnInProgress
    || waitingForVisibleResponse
    || messages.some((message) => immediateMessageIds.has(message.id) && isLiveQueuedMessage(message));
  const gettingReady = isGettingReady(ally);

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
      const accepted = await session.runCloudOperation(
        (signal) => session.client.sendMessage(workspaceId, conversation.id, content, key, signal, Intl.DateTimeFormat().resolvedOptions().timeZone),
        { csrf: true },
      );
      if (!accepted?.message) throw { kind: "contract" };
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
      if (queuedMessageId !== undefined && isDefinitiveMessageRejection(error)) {
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
    const accepted = await sendMessageContent(buildRoutineActionMessage(request), key, false);
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

  const submit = async (showImmediately = false) => {
    if (conversationAccessFailure || !conversation || !queuedMessagesReady || !canChat(ally)) return;
    const content = draft.trim();
    if (!content) return;
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
      && blockedHead.content === content;
    if (retryingBlockedHead) {
      blockedQueuedMessageIdsRef.current.delete(blockedHead.id);
      const accepted = await sendMessageContent(content, blockedHead.intentKey, true, blockedHead.id);
      if (!accepted) blockedQueuedMessageIdsRef.current.add(blockedHead.id);
      return;
    }
    if (queuedMessagesSnapshot.length >= MAX_QUEUED_MESSAGES) {
      setQueuePersistenceError(`You can queue up to ${MAX_QUEUED_MESSAGES} messages. Send or remove one before adding another.`);
      return;
    }
    const nextMessage = {
      id: `queued-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`}`,
      content,
      intentKey: key,
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
    intentRef.current = null;
  };

  useEffect(() => {
    const removedIds = readQueuedMessageTombstones(queuedMessagesStorageKey);
    const liveMessages = mergeQueuedMessages(
      queuedMessagesRef.current,
      readQueuedMessages(queuedMessagesStorageKey),
    ).filter((message) => !removedIds.has(message.id));
    const nextMessage = liveMessages.find((message) => !blockedQueuedMessageIdsRef.current.has(message.id));
    if (
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
    if (pollCountRef.current >= ACTIVITY_POLL_LIMIT) {
      if (!pollBudgetReached) setPollBudgetReached(true);
      if (!companionSnapshot) {
        setActiveTurn(false);
        setAwaitingVisibleResponse(false);
        setPollingSettled(true);
      }
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
    const startPollingFallback = () => {
      if (fallbackStarted) return;
      fallbackStarted = true;
      pollCountRef.current = 0;
      setPollBudgetReached(false);
      setStreamConnected(false);
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
        setStreamConnected(true);
        setActivityError(null);
        activityRequestRef.current?.abort();
      },
      onEvent: (event) => {
        if (!mountedRef.current) return;
        if ("conversationId" in event && event.conversationId !== targetConversationId) {
          controller.abort();
          startPollingFallback();
          return;
        }
        if (event.type === "activity") {
          const currentActiveMessageId = activeMessageIdRef.current;
          const currentActiveMessageOrdinal = activeMessageOrdinalRef.current;
          const eventIsActive = (!currentActiveMessageId || event.activity.messageId === currentActiveMessageId)
            && (currentActiveMessageOrdinal === null
              || event.activity.conversationTurnOrdinal === currentActiveMessageOrdinal);
          if (!eventIsActive) return;
          if (event.activity.kind === "assistant_delta" && event.activity.text.trim()) {
            responseStartedRef.current = true;
            setAwaitingVisibleResponse(false);
          }
          setProjection((current) => projectConversationActivity(current, {
            conversationId: targetConversationId,
            activeMessageId: currentActiveMessageId ?? event.activity.messageId,
            activities: [event.activity],
            state: event.activity.state,
            lastContiguousSequence: event.activity.sequence,
            lastContiguousActivitySequence: event.activity.sequence,
            resumeCursor: event.cursor,
            nextCursor: null,
            latestSequence: event.activity.sequence,
          }, conversationMessagesRef.current));
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
    workspaceId,
  ]);

  useEffect(() => {
    if (!shouldPoll) {
      activityRequestRef.current?.abort();
      return;
    }
    const interval = window.setInterval(() => void checkActivity(), activityPollInterval);
    return () => {
      window.clearInterval(interval);
      activityRequestRef.current?.abort();
    };
  }, [activityPollInterval, checkActivity, shouldPoll]);

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
    const cloudMessage = conversationQueueMessages.find((message) => message.id === id);
    if (cloudMessage) {
      if (!isCloudQueueMessageRemovable(cloudMessage) || !conversation) return;
      await withQueueMessageLock(queuedMessagesStorageKey, id, async () => {
        try {
          const tombstone = await session.runCloudOperation(
            (signal) => session.client.deleteQueuedMessage(workspaceId, conversation.id, id, signal),
            { csrf: true },
          );
          if (!tombstone.deletedAt) throw { kind: "contract" };
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
  const visibleFrameMessages = baseFrameModel.messages.map((message) => immediateMessageIds.has(message.id)
    ? { ...message, queued: false } : message);
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
    messages: [...visibleFrameMessages, ...immediateFrameMessages],
    queuedMessages: baseFrameModel.queuedMessages.filter((message) => !immediateMessageIds.has(message.id)),
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
    onCloseRoutine: () => setSelectedRoutineId(null),
    onRetryRoutineDetail: () => void routineDetailQuery.refetch(),
    onRoutineAction: sendRoutineAction,
    onScroll: (event) => {
      const canvas = event.currentTarget;
      followLatestRef.current = canvas.scrollHeight - canvas.scrollTop - canvas.clientHeight < 96;
    },
  };

  const frame = <ConversationFrame stateReady={stateReady} sleeping={sleeping} runtimeIntentStatus={runtimeIntentStatus} model={frameModel} actions={frameActions} canvasRef={messageCanvasRef} />;
  return <ConversationApprovals
    client={approvalClient}
    workspaceId={workspaceId}
    conversationId={conversationId ?? ""}
    allyName={ally.name}
    accent={allyAccent}
    canApprove={canApprove}
    enabled={Boolean(conversationId && !conversationAccessFailure)}
  >
    {frame}
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

function mergeMessages(...groups: MessageViewModel[][]): MessageViewModel[] {
  return mergeConversationMessageCopies(...groups);
}

function mergeAssistantReplies(
  ...groups: readonly (readonly AssistantReplyViewModel[])[]
): AssistantReplyViewModel[] {
  const bySourceMessageId = new Map<string, AssistantReplyViewModel>();
  for (const group of groups) {
    for (const reply of group) {
      const current = bySourceMessageId.get(reply.sourceMessageId);
      if (!current || preferAssistantReply(current, reply)) {
        bySourceMessageId.set(reply.sourceMessageId, reply);
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
  if (current.hasFullPrefix !== incoming.hasFullPrefix) return incoming.hasFullPrefix;
  const currentUpdatedAt = Date.parse(current.updatedAt);
  const incomingUpdatedAt = Date.parse(incoming.updatedAt);
  if (Number.isFinite(currentUpdatedAt) && Number.isFinite(incomingUpdatedAt)
    && currentUpdatedAt !== incomingUpdatedAt) {
    return incomingUpdatedAt > currentUpdatedAt;
  }
  if (current.content.length !== incoming.content.length) return incoming.content.length > current.content.length;
  if (current.isTruncated !== incoming.isTruncated) return incoming.isTruncated === true;
  return incoming.status !== current.status && isLaterReplyStatus(incoming.status, current.status);
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
  return ally.provisioningState === "bound";
}

function isGettingReady(ally: AllyViewModel): boolean {
  return ally.provisioningState === "pending" || ally.provisioningState === "retryable";
}

function allySecondaryLine(ally: AllyViewModel): string {
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

function buildQueuedFrameMessages(
  cloudQueue: readonly MessageViewModel[],
  localQueue: readonly QueuedMessage[],
  activeMessageId: string | null,
  activeMessageHasProgress: boolean,
  activeMessageInTimeline = true,
): ProductionQueuedMessageModel[] {
  const items: ProductionQueuedMessageModel[] = [];
  for (const message of cloudQueue) {
    if (!isLiveQueuedMessage(message)) continue;
    if (message.id === activeMessageId && activeMessageInTimeline) continue;
    items.push({
      id: message.id,
      content: message.content,
      removable: isCloudQueueMessageRemovable(message),
      statusLabel: message.id === activeMessageId && !activeMessageHasProgress ? "Queued" : null,
    });
  }
  for (const message of localQueue) {
    items.push({
      id: message.id,
      content: message.content,
      removable: supportsQueueMessageLocks() && message.attemptedAt === undefined,
      statusLabel: null,
    });
  }
  return items;
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
        && item.content.length > 0
        && item.content.length <= 16_000
        && typeof item.intentKey === "string";
      if (!valid || seenIds.has(item.id as string) || seenIntentKeys.has(item.intentKey as string)) return [];
      seenIds.add(item.id as string);
      seenIntentKeys.add(item.intentKey as string);
      return [{
        id: item.id as string,
        content: item.content as string,
        intentKey: item.intentKey as string,
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
