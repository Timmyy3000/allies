"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { isCloudError, type ApprovalDecision, type ApprovalDetail, type ApprovalSummary } from "@allies/cloud-client";
import { BottomSheet } from "./conversation-frame-primitives";
import { ActivityIcon } from "./activity-icon";
import styles from "./conversation-frame.module.css";
import toastStyles from "./recipes-button.module.css";

export interface ApprovalClient {
  getApprovals: (workspace: string, conversation: string, signal?: AbortSignal) => Promise<ApprovalSummary[]>;
  getApproval: (workspace: string, conversation: string, approval: string, signal?: AbortSignal) => Promise<ApprovalDetail>;
  decideApproval: (workspace: string, conversation: string, approval: string, decision: ApprovalDecision, key: string, signal?: AbortSignal) => Promise<ApprovalDetail>;
}

type DecisionIntent = { decision: ApprovalDecision; key: string };

export type ApprovalReadFailure = "aborted" | "transient" | "access" | "not-found" | "actionable";

export function classifyApprovalReadError(error: unknown): ApprovalReadFailure {
  if (isCloudError(error)) {
    if (error.kind === "aborted") return "aborted";
    if (error.kind === "unauthorized" || error.status === 401 || error.kind === "forbidden" || error.status === 403) return "access";
    if (error.kind === "not-found" || error.status === 404) return "not-found";
    if (error.kind === "network" || error.kind === "timeout" || error.kind === "throttled" || error.kind === "server"
      || error.status === 408 || error.status === 429 || (error.status !== undefined && error.status >= 500)) return "transient";
  }
  return "actionable";
}

interface ConversationApprovalSlots {
  forMessage: (messageId: string) => ReactNode;
  unmatched: (visibleMessageIds?: ReadonlySet<string>) => ReactNode;
}

interface ApprovalReadState {
  lastErrorAt: number;
  transientFailures: number;
  toasted: boolean;
}

interface ApprovalNotice {
  resource: string;
  message: string;
}

const ApprovalSlotsContext = createContext<ConversationApprovalSlots | null>(null);

export function ConversationApprovalSlot({ messageId, visibleMessageIds }: { messageId?: string; visibleMessageIds?: ReadonlySet<string> }) {
  const slots = useContext(ApprovalSlotsContext);
  if (!slots) return null;
  return messageId ? slots.forMessage(messageId) : slots.unmatched(visibleMessageIds);
}

export function pruneDecisionIntents(intents: Record<string, DecisionIntent>, approvals: ApprovalSummary[]) {
  const terminalIds = new Set(approvals.filter((approval) => !["pending", "decision_recorded"].includes(approval.status)).map((approval) => approval.id));
  return Object.fromEntries(Object.entries(intents).filter(([id]) => !terminalIds.has(id)));
}

function confirmedStatus(...sources: (ApprovalSummary | null | undefined)[]) {
  return sources.find((source) => source && !["pending", "decision_recorded"].includes(source.status))
    ?? sources.find((source) => source?.status === "decision_recorded")
    ?? sources.find(Boolean);
}

export function mergeApprovalSummaries(
  hydrated: readonly ApprovalSummary[],
  activity: readonly ApprovalSummary[],
  recorded: Readonly<Record<string, ApprovalSummary>>,
): ApprovalSummary[] {
  const hydratedById = new Map(hydrated.map((approval) => [approval.id, approval]));
  const activityById = new Map(activity.map((approval) => [approval.id, approval]));
  const ids = [...new Set([
    ...hydrated.map((approval) => approval.id),
    ...activity.map((approval) => approval.id),
  ])];

  return ids.flatMap((id) => {
    const persisted = hydratedById.get(id);
    const streamed = activityById.get(id);
    const local = recorded[id];
    const selected = confirmedStatus(local, streamed, persisted);
    if (!selected) return [];
    return [{
      ...persisted,
      ...streamed,
      ...local,
      ...selected,
      decidedAt: selected.decidedAt ?? local?.decidedAt ?? streamed?.decidedAt ?? persisted?.decidedAt ?? null,
      acknowledgementDeadlineAt: selected.acknowledgementDeadlineAt
        ?? local?.acknowledgementDeadlineAt
        ?? persisted?.acknowledgementDeadlineAt
        ?? streamed?.acknowledgementDeadlineAt
        ?? null,
    }];
  });
}

export function approvalStatusAt(approval: ApprovalSummary, now: number): ApprovalSummary["status"] {
  if (approval.status === "pending" && now >= Date.parse(approval.expiresAt)) return "expired";
  if (approval.status === "decision_recorded" && approval.acknowledgementDeadlineAt && now >= Date.parse(approval.acknowledgementDeadlineAt)) return "outcome_unknown";
  return approval.status;
}

const statusText = {
  pending: "Approval needed",
  decision_recorded: "Decision recorded · Waiting for Ally",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Approval expired",
  cancelled: "Approval cancelled",
  outcome_unknown: "Decision recorded; Ally outcome could not be confirmed",
};

export function approvalQuestion(allyName: string, action: string | undefined, pending: boolean) {
  const summary = action?.trim().replace(/[.?!]+$/, "");
  if (!summary) return pending ? `Allow ${allyName} to perform this action?` : "Approval details";
  const clause = summary.charAt(0).toLowerCase() + summary.slice(1);
  return pending ? `Allow ${allyName} to ${clause}?` : `${allyName} asked to ${clause}`;
}

const actionKindText = {
  terminal: "Terminal command",
  execute_code: "Code execution",
  plugin_tool: "Plugin tool",
} as const;

function ApprovalBadge() {
  return <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M10.75 2.45c.69-.59 1.82-.59 2.52 0l1.58 1.36c.3.26.86.47 1.26.47h1.7c1.06 0 1.93.87 1.93 1.93v1.7c0 .39.21.96.47 1.26l1.36 1.58c.59.69.59 1.82 0 2.52l-1.36 1.58c-.26.3-.47.86-.47 1.26v1.7c0 1.06-.87 1.93-1.93 1.93h-1.7c-.39 0-.96.21-1.26.47l-1.58 1.36c-.69.59-1.82.59-2.52 0l-1.58-1.36c-.3-.26-.86-.47-1.26-.47H6.18c-1.06 0-1.93-.87-1.93-1.93V16.1c0-.39-.21-.95-.46-1.25l-1.35-1.59c-.58-.69-.58-1.81 0-2.5l1.35-1.59c.25-.3.46-.86.46-1.25V6.2c0-1.06.87-1.93 1.93-1.93h1.73c.3 0 .96-.21 1.26-.47l1.58-1.35Z" fill="#f5d308" />
    <path d="M10.79 15.171a.75.75 0 0 1-.53-.22l-2.42-2.42a.754.754 0 0 1 0-1.06c.29-.29.77-.29 1.06 0l1.89 1.89 4.3-4.3c.29-.29.77-.29 1.06 0 .29.29.29.77 0 1.06l-4.83 4.83a.75.75 0 0 1-.53.22Z" fill="#fff" />
  </svg>;
}

export function ConversationApprovals({ client, workspaceId, conversationId, allyName, accent, canApprove, enabled = true, activityApprovals = [], liveUpdatesConnected = false, children }: {
  client: ApprovalClient;
  workspaceId: string;
  conversationId: string;
  allyName: string;
  accent: string;
  canApprove: boolean;
  enabled?: boolean;
  activityApprovals?: readonly ApprovalSummary[];
  liveUpdatesConnected?: boolean;
  children?: ReactNode;
}) {
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [intents, setIntents] = useState<Record<string, DecisionIntent>>({});
  const [recorded, setRecorded] = useState<Record<string, ApprovalSummary>>({});
  const [now, setNow] = useState(() => Date.now());
  const restoreFocusId = useRef<string | null>(null);
  const scopeKey = `${workspaceId}:${conversationId}`;
  const [accessDisabled, setAccessDisabled] = useState(false);
  const [summaryPaused, setSummaryPaused] = useState(false);
  const [notice, setNotice] = useState<ApprovalNotice | null>(null);
  const readStates = useRef<Record<string, ApprovalReadState>>({});
  useEffect(() => {
    let current = true;
    queueMicrotask(() => {
      if (!current) return;
      readStates.current = {};
      setAccessDisabled(false);
      setSummaryPaused(false);
      setNotice(null);
      setOpenedId(null);
      setIntents({});
      setRecorded({});
      restoreFocusId.current = null;
    });
    return () => { current = false; };
  }, [scopeKey]);
  useEffect(() => {
    if (enabled) return;
    let current = true;
    queueMicrotask(() => { if (current) setNotice(null); });
    return () => { current = false; };
  }, [enabled]);
  const reportReadSuccess = useCallback((resource: string) => {
    const key = `${scopeKey}:${resource}`;
    readStates.current = Object.fromEntries(
      Object.entries(readStates.current).filter(([entry]) => entry !== key),
    );
    setNotice((current) => current?.resource === key ? null : current);
  }, [scopeKey]);
  const reportReadFailure = useCallback((resource: string, error: unknown, errorAt: number) => {
    if (classifyApprovalReadError(error) === "aborted") return;
    const key = `${scopeKey}:${resource}`;
    const previous = readStates.current[key] ?? { lastErrorAt: 0, transientFailures: 0, toasted: false };
    if (errorAt <= previous.lastErrorAt) return;
    const failure = classifyApprovalReadError(error);
    const current = {
      lastErrorAt: errorAt,
      transientFailures: failure === "transient" ? previous.transientFailures + 1 : 0,
      toasted: previous.toasted,
    };
    readStates.current = { ...readStates.current, [key]: current };
    if (failure === "access") {
      setAccessDisabled(true);
      setOpenedId(null);
    } else if (resource === "summary" && failure !== "transient") {
      setSummaryPaused(true);
    }
    const shouldToast = failure !== "transient" || current.transientFailures >= 3;
    if (shouldToast && !current.toasted) {
      current.toasted = true;
      setNotice({
        resource: key,
        message: failure === "transient"
          ? "Could not check approvals after several attempts. Try again."
          : failure === "not-found"
            ? "This approval is no longer available. Try again."
            : failure === "access"
              ? "Approval access is no longer available."
              : "Could not check this approval. Try again.",
      });
    }
  }, [scopeKey]);
  const dismissNotice = useCallback(() => {
    setNotice(null);
  }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(dismissNotice, 4_000);
    return () => window.clearTimeout(timer);
  }, [dismissNotice, notice]);
  const approvalsVisible = enabled && !accessDisabled;
  const summaryEnabled = approvalsVisible && !summaryPaused;
  const summaries = useQuery({
    queryKey: ["workspaces", workspaceId, "approvals", conversationId],
    queryFn: ({ signal }) => client.getApprovals(workspaceId, conversationId, signal),
    enabled: summaryEnabled,
    refetchInterval: (query) => {
      if (query.state.error && classifyApprovalReadError(query.state.error) !== "transient") return false;
      if (liveUpdatesConnected) return false;
      const items = mergeApprovalSummaries(query.state.data ?? [], activityApprovals, recorded);
      return items.some((approval) => {
        const status = approvalStatusAt(approval, Date.now());
        return status === "pending" || status === "decision_recorded";
      }) ? 3_000 : false;
    },
    refetchIntervalInBackground: false,
    retry: false,
  });
  useEffect(() => {
    let current = true;
    queueMicrotask(() => {
      if (!current) return;
      if (summaries.isSuccess) reportReadSuccess("summary");
      else if (summaries.isError) reportReadFailure("summary", summaries.error, summaries.errorUpdatedAt);
    });
    return () => { current = false; };
  }, [reportReadFailure, reportReadSuccess, summaries.error, summaries.errorUpdatedAt, summaries.isError, summaries.isSuccess]);
  const approvals = useMemo(() => approvalsVisible
    ? mergeApprovalSummaries(summaries.data ?? [], activityApprovals, recorded)
    : [], [activityApprovals, approvalsVisible, recorded, summaries.data]);
  const hasDeadlineBearing = approvals.some((approval) => {
    const status = approvalStatusAt(approval, now);
    return (status === "pending" && Boolean(approval.expiresAt))
      || (status === "decision_recorded" && Boolean(approval.acknowledgementDeadlineAt));
  });
  useEffect(() => {
    if (!hasDeadlineBearing) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [hasDeadlineBearing]);
  const activeId = approvalsVisible ? openedId : null;
  const selected = approvals.find((approval) => approval.id === activeId);
  const close = () => {
    restoreFocusId.current = activeId;
    setOpenedId(null);
  };
  const approvalButton = (approval: ApprovalSummary) => {
    const status = approvalStatusAt(approval, now);
    return <button type="button" data-approval-id={approval.id} className={`${styles.frameActivityEntry} ${styles.approvalHistoryRow} ${status === "pending" ? styles.frameActivityAccent : styles.frameActivityMuted}`} key={approval.id} onClick={() => setOpenedId(approval.id)}>
      <ActivityIcon kind="approval" tone={status === "pending" ? "accent" : "muted"} />
      <span className={styles.approvalHistoryStatus}>{statusText[status]}</span>
    </button>;
  };
  const retrySummaries = () => {
    setSummaryPaused(false);
    void summaries.refetch();
  };
  const list = (items: ApprovalSummary[]) => items.length ? <div className={styles.approvalRegion} style={{ "--chat-accent": accent } as CSSProperties}>
    {items.map(approvalButton)}
  </div> : null;
  const slots: ConversationApprovalSlots = {
    forMessage: (messageId) => list(approvals.filter((approval) => approval.messageId === messageId)),
    // Settled approvals wait for their message to load; only open ones need the fallback slot.
    unmatched: (visibleMessageIds) => list(visibleMessageIds ? approvals.filter((approval) => !visibleMessageIds.has(approval.messageId)
      && ["pending", "decision_recorded"].includes(approvalStatusAt(approval, now))) : approvals),
  };
  useEffect(() => {
    if (activeId !== null || !restoreFocusId.current) return;
    const approvalId = restoreFocusId.current;
    const frame = window.requestAnimationFrame(() => {
      const button = document.querySelector<HTMLButtonElement>(`[data-approval-id="${approvalId}"]`);
      if (button) {
        button.focus();
      }
      restoreFocusId.current = null;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeId, approvals]);
  return <>
    <ApprovalSlotsContext value={slots}>{children ?? <ConversationApprovalSlot />}</ApprovalSlotsContext>
    {enabled && notice ? <div className={toastStyles.announcement} role="status" aria-live="polite" aria-atomic="true">
      <div className={toastStyles.toast}>
        <span>{notice.message}</span>
        {notice.resource.endsWith(":summary") && !accessDisabled ? <button type="button" onClick={retrySummaries}>Try again</button> : null}
        <button type="button" aria-label="Dismiss notification" onClick={dismissNotice}>×</button>
      </div>
    </div> : null}
    {activeId ? <ApprovalDialog key={activeId} client={client} workspaceId={workspaceId} conversationId={conversationId} approvalId={activeId} summary={selected} intent={intents[activeId]} rememberIntent={(intent) => setIntents((prior) => ({ ...pruneDecisionIntents(prior, approvals), [activeId]: intent }))} now={now} allyName={allyName} accent={accent} canApprove={canApprove} liveUpdatesConnected={liveUpdatesConnected} onReadSuccess={() => reportReadSuccess(`approval:${activeId}`)} onReadFailure={(error, errorAt) => reportReadFailure(`approval:${activeId}`, error, errorAt)} onClose={() => close()} onRecorded={(approval) => {
      setRecorded((prior) => ({ ...prior, [approval.id]: confirmedStatus(prior[approval.id], approval) ?? approval }));
      close();
      if (!liveUpdatesConnected) void summaries.refetch();
    }} /> : null}
  </>;
}

function ApprovalDialog({ client, workspaceId, conversationId, approvalId, summary, intent, rememberIntent, now, allyName, accent, canApprove, liveUpdatesConnected, onReadSuccess, onReadFailure, onClose, onRecorded }: {
  client: ApprovalClient; workspaceId: string; conversationId: string; approvalId: string;
  summary?: ApprovalSummary; now: number; allyName: string; accent: string; canApprove: boolean; onClose: () => void; onRecorded: (approval: ApprovalSummary) => void;
  liveUpdatesConnected: boolean;
  onReadSuccess: () => void; onReadFailure: (error: unknown, errorAt: number) => void;
  intent?: DecisionIntent; rememberIntent: (intent: DecisionIntent) => void;
}) {
  const detail = useQuery({
    queryKey: ["workspaces", workspaceId, "approval", conversationId, approvalId],
    queryFn: ({ signal }) => client.getApproval(workspaceId, conversationId, approvalId, signal),
    refetchInterval: (query) => {
      if (query.state.error && classifyApprovalReadError(query.state.error) !== "transient") return false;
      if (liveUpdatesConnected) return false;
      const item = query.state.data;
      if (!item) return 3_000;
      const status = approvalStatusAt(item, Date.now());
      return status === "pending" || status === "decision_recorded" ? 3_000 : false;
    },
    refetchIntervalInBackground: false,
    retry: false,
  });
  const [recorded, setRecorded] = useState<ApprovalDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [readBlocked, setReadBlocked] = useState(false);
  const handledErrorAt = useRef(0);
  const handledSuccessAt = useRef(0);
  const [choice, setChoice] = useState<ApprovalDecision | null>(intent?.decision ?? null);
  const request = useRef<DecisionIntent | null>(intent ?? null);
  const inFlight = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!detail.isError || detail.errorUpdatedAt <= handledErrorAt.current) return;
    handledErrorAt.current = detail.errorUpdatedAt;
    let current = true;
    queueMicrotask(() => {
      if (!current) return;
      if (classifyApprovalReadError(detail.error) !== "aborted") setReadBlocked(true);
      onReadFailure(detail.error, detail.errorUpdatedAt);
    });
    return () => { current = false; };
  }, [detail.error, detail.errorUpdatedAt, detail.isError, onReadFailure]);
  useEffect(() => {
    if (!detail.isSuccess || detail.dataUpdatedAt <= handledSuccessAt.current) return;
    handledSuccessAt.current = detail.dataUpdatedAt;
    setReadBlocked(false);
    onReadSuccess();
  }, [detail.dataUpdatedAt, detail.isSuccess, onReadSuccess]);
  const data = detail.data;
  const authoritative = confirmedStatus(summary, data, recorded);
  const status = authoritative ? approvalStatusAt(authoritative, now) : null;
  const reported = useRef(Boolean(authoritative && authoritative.status !== "pending"));
  useEffect(() => {
    if (!request.current || !authoritative || reported.current || !["decision_recorded", "approved", "rejected"].includes(authoritative.status)) return;
    reported.current = true;
    onRecorded(authoritative);
  }, [authoritative, onRecorded]);
  const submit = async (decision: ApprovalDecision) => {
    if (inFlight.current || !authoritative || approvalStatusAt(authoritative, Date.now()) !== "pending" || !data || detail.isError || !canApprove) return;
    if (request.current && request.current.decision !== decision) return;
    request.current ??= { decision, key: crypto.randomUUID() };
    rememberIntent(request.current);
    setChoice(decision);
    inFlight.current = true;
    setBusy(true);
    setFailed(false);
    controller.current = new AbortController();
    try {
      const result = await client.decideApproval(workspaceId, conversationId, approvalId, decision, request.current.key, controller.current.signal);
      setRecorded(result);
      if (["decision_recorded", "approved", "rejected"].includes(result.status)) {
        reported.current = true;
        onRecorded(result);
      }
    } catch {
      if (!controller.current.signal.aborted) { setFailed(true); void detail.refetch(); }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return <BottomSheet modal onClose={onClose} labelledBy="approval-title" className={styles.approvalModal} style={{ "--chat-accent": accent } as CSSProperties} headerContent={<span className={styles.approvalBadge}><ApprovalBadge /></span>}>
    <h2 id="approval-title" className={styles.frameSheetQuestion}>{approvalQuestion(allyName, data?.explanation?.action, status === "pending")}</h2>
    {!data ? <p role="status">{detail.isError ? "Could not load this approval." : "Loading approval…"}</p> : <>
      <details className={styles.approvalDetails}>
        <summary>View technical details</summary>
        <div className={styles.approvalPreview}>
          {data.actionKind ? <p className={styles.approvalTechnicalMeta}><span>Type</span><strong>{actionKindText[data.actionKind]}</strong></p> : null}
          <p className={styles.approvalTechnicalMeta}><span>Action</span><strong>{data.actionLabel}</strong></p>
          <pre>{data.actionPreview}</pre>
        </div>
      </details>
    </>}
    {detail.isError ? <>
      <p role="status">{data
        ? "Could not refresh this approval. Your last confirmed details remain visible; retry to enable decisions."
        : "Could not load this approval. Try again."}</p>
      <button type="button" onClick={() => void detail.refetch()}>Try again</button>
    </> : null}
    {status && status !== "pending" ? <p role="status">{statusText[status]}</p> : null}
    {failed && status === "pending" ? <p role="alert">The decision could not be confirmed. Retry the same choice to check safely.</p> : null}
    {data && status === "pending" ? <>
      {!canApprove ? <p>You need permission to respond to this approval.</p> : null}
      <div className={styles.frameSheetActions}>
        <button type="button" className={styles.frameNeutralAction} disabled={!canApprove || busy || detail.isError || readBlocked || choice === "approve"} onClick={() => void submit("reject")}>Reject</button>
        <button type="button" className={styles.frameAccentAction} disabled={!canApprove || busy || detail.isError || readBlocked || choice === "reject"} onClick={() => void submit("approve")}>Approve</button>
      </div>
      {busy ? <p role="status">Recording decision…</p> : null}
    </> : null}
  </BottomSheet>;
}
