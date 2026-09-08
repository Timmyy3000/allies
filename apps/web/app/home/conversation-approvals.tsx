"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ApprovalDecision, ApprovalDetail, ApprovalSummary } from "@allies/cloud-client";
import { BottomSheet } from "./conversation-frame-primitives";
import styles from "./conversation-frame.module.css";

export interface ApprovalClient {
  getApprovals: (workspace: string, conversation: string, signal?: AbortSignal) => Promise<ApprovalSummary[]>;
  getApproval: (workspace: string, conversation: string, approval: string, signal?: AbortSignal) => Promise<ApprovalDetail>;
  decideApproval: (workspace: string, conversation: string, approval: string, decision: ApprovalDecision, key: string, signal?: AbortSignal) => Promise<ApprovalDetail>;
}

type DecisionIntent = { decision: ApprovalDecision; key: string };

export function pruneDecisionIntents(intents: Record<string, DecisionIntent>, approvals: ApprovalSummary[]) {
  const terminalIds = new Set(approvals.filter((approval) => !["pending", "decision_recorded"].includes(approval.status)).map((approval) => approval.id));
  return Object.fromEntries(Object.entries(intents).filter(([id]) => !terminalIds.has(id)));
}

function confirmedStatus(...sources: (ApprovalSummary | null | undefined)[]) {
  return sources.find((source) => source && !["pending", "decision_recorded"].includes(source.status))
    ?? sources.find((source) => source?.status === "decision_recorded")
    ?? sources.find(Boolean);
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

export function ConversationApprovals({ client, workspaceId, conversationId, allyName, accent, canApprove }: {
  client: ApprovalClient;
  workspaceId: string;
  conversationId: string;
  allyName: string;
  accent: string;
  canApprove: boolean;
}) {
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const [intents, setIntents] = useState<Record<string, DecisionIntent>>({});
  const [now, setNow] = useState(() => Date.now());
  const summaries = useQuery({
    queryKey: ["workspaces", workspaceId, "approvals", conversationId],
    queryFn: ({ signal }) => client.getApprovals(workspaceId, conversationId, signal),
    refetchInterval: 3_000,
    retry: false,
  });
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const pending = summaries.data?.find((approval) => approvalStatusAt(approval, now) === "pending" && !dismissed.has(approval.id));
  useEffect(() => {
    if (openedId !== null || !pending) return;
    const timer = window.setTimeout(() => setOpenedId(pending.id), 0);
    return () => window.clearTimeout(timer);
  }, [openedId, pending]);
  const activeId = openedId ?? pending?.id ?? null;
  const selected = summaries.data?.find((approval) => approval.id === activeId);
  const current = summaries.data?.filter((approval) => ["pending", "decision_recorded"].includes(approvalStatusAt(approval, now))) ?? [];
  const previous = summaries.data?.filter((approval) => !["pending", "decision_recorded"].includes(approvalStatusAt(approval, now))) ?? [];
  const close = () => {
    if (activeId) setDismissed((prior) => new Set(prior).add(activeId));
    setOpenedId(null);
  };
  return <div className={styles.approvalRegion} style={{ "--chat-accent": accent } as CSSProperties}>
    {summaries.isError ? <button type="button" onClick={() => void summaries.refetch()}>Could not check approvals. Try again</button> : null}
    {current.map((approval) => <button type="button" className={styles.approvalReopen} key={approval.id} onClick={() => setOpenedId(approval.id)}>
      {statusText[approvalStatusAt(approval, now)]}
    </button>)}
    {previous.length ? <details><summary>Previous approvals</summary>{previous.map((approval) => <button type="button" className={styles.approvalReopen} key={approval.id} onClick={() => setOpenedId(approval.id)}>{statusText[approvalStatusAt(approval, now)]}</button>)}</details> : null}
    {activeId ? <ApprovalDialog key={activeId} client={client} workspaceId={workspaceId} conversationId={conversationId} approvalId={activeId} summary={selected} intent={intents[activeId]} rememberIntent={(intent) => setIntents((prior) => ({ ...pruneDecisionIntents(prior, summaries.data ?? []), [activeId]: intent }))} now={now} allyName={allyName} canApprove={canApprove} onClose={close} onRecorded={() => { setOpenedId(activeId); void summaries.refetch(); }} /> : null}
  </div>;
}

function ApprovalDialog({ client, workspaceId, conversationId, approvalId, summary, intent, rememberIntent, now, allyName, canApprove, onClose, onRecorded }: {
  client: ApprovalClient; workspaceId: string; conversationId: string; approvalId: string;
  summary?: ApprovalSummary; now: number; allyName: string; canApprove: boolean; onClose: () => void; onRecorded: () => void;
  intent?: DecisionIntent; rememberIntent: (intent: DecisionIntent) => void;
}) {
  const detail = useQuery({
    queryKey: ["workspaces", workspaceId, "approval", conversationId, approvalId],
    queryFn: ({ signal }) => client.getApproval(workspaceId, conversationId, approvalId, signal),
    refetchInterval: 3_000,
    retry: false,
  });
  const [recorded, setRecorded] = useState<ApprovalDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [choice, setChoice] = useState<ApprovalDecision | null>(intent?.decision ?? null);
  const request = useRef<DecisionIntent | null>(intent ?? null);
  const inFlight = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const data = detail.data;
  const authoritative = confirmedStatus(summary, data, recorded);
  const status = authoritative ? approvalStatusAt(authoritative, now) : null;
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
      onRecorded();
    } catch {
      if (!controller.current.signal.aborted) { setFailed(true); void detail.refetch(); }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  return <BottomSheet modal onClose={onClose} labelledBy="approval-title" className={styles.approvalModal}>
    <h2 id="approval-title" className={styles.frameSheetQuestion}>Allow {allyName} to perform this action?</h2>
    {!data ? <p role="status">{detail.isError ? "Could not load this approval." : "Loading approval…"}</p> : <div className={styles.approvalPreview}>
      <strong>{data.actionLabel}</strong>
      <pre>{data.actionPreview}</pre>
    </div>}
    {!data && detail.isError ? <button type="button" onClick={() => void detail.refetch()}>Try again</button> : null}
    {status && status !== "pending" ? <p role="status">{statusText[status]}</p> : null}
    {failed && status === "pending" ? <p role="alert">The decision could not be confirmed. Retry the same choice to check safely.</p> : null}
    {data && status === "pending" ? <>
      {!canApprove ? <p>You need permission to respond to this approval.</p> : null}
      <div className={styles.frameSheetActions}>
        <button type="button" className={styles.frameNeutralAction} disabled={!canApprove || busy || detail.isError || choice === "approve"} onClick={() => void submit("reject")}>Reject</button>
        <button type="button" className={styles.frameAccentAction} disabled={!canApprove || busy || detail.isError || choice === "reject"} onClick={() => void submit("approve")}>Approve</button>
      </div>
      {busy ? <p role="status">Recording decision…</p> : null}
    </> : null}
  </BottomSheet>;
}
