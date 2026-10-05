"use client";

import { Streamdown } from "streamdown";
import { RoutineUserText, routineLinkComponents } from "./routine-mention";
import { ShinyText } from "../../components/text-animations/shiny-text";
import { useEffect, useRef, useState, type Ref, type UIEvent, type ReactNode } from "react";
import { ConversationPresence } from "./conversation-presence";
import { ConversationApprovalSlot } from "./conversation-approvals";

import type {
  ProductionRuntimeIntentStatus,
  ProductionConversationActivityGroupModel,
  ProductionConversationFrameActions,
  ProductionConversationFrameModel,
  ProductionConversationTurnModel,
  QueuedAttachmentPreview,
  RoutineActionRequest,
} from "./conversation-frame-model";
import {
  completedParagraphs,
  conversationDateDividerAt,
  formatConversationDateDivider,
  routineMessageAnchor,
} from "./conversation-frame-model";
import {
  ActivityDisclosure,
  AssistantMessage,
  BottomSheet,
  ConversationCanvas,
  ConversationComposer,
  ConversationHeader,
  ConversationRail,
  ConversationShell,
  DateDivider,
  DeleteRoutineSheet,
  FrameError,
  QueueStack,
  RoutineChatDetail,
  RoutineChatProjectionCard,
  RoutineRunDetail,
  UserBubble,
} from "./conversation-frame-primitives";
import styles from "./conversation-frame.module.css";
import { playInteractionSound } from "../../lib/interaction-sounds";

const EMPTY_ROUTINE_ITEMS: NonNullable<ProductionConversationFrameModel["routineItems"]> = [];

// Safety net only: the composing intent now polls until Foundry reports ready.
export const WAKE_HINT_TIMEOUT_MS = 90_000;

export interface ConversationFrameProps {
  settingsHref?: string;
  model: ProductionConversationFrameModel;
  actions: ProductionConversationFrameActions;
  onOpenSettings?: () => void;
  canvasRef?: Ref<HTMLDivElement>;
  sleeping?: boolean;
  stateReady?: boolean;
  runtimeIntentStatus?: ProductionRuntimeIntentStatus;
  attachments?: ReactNode;
  fileRecovery?: ReactNode;
  onAttach?: (anchor: HTMLElement) => void;
  onFilesDrop?: (files: File[], origin: DOMRect) => boolean | void;
  messageAttachments?: (id: string) => ReactNode;
  publications?: (messageId: string) => ReactNode;
  onFileOpen?: (fileId: string) => void;
  onQueueAttachmentOpen?: (file: QueuedAttachmentPreview) => void;
}

export function ConversationFrame({ model, actions, onOpenSettings, canvasRef, settingsHref = "/account", sleeping = false, stateReady = true, runtimeIntentStatus = null, attachments, fileRecovery, onAttach, onFilesDrop, messageAttachments, publications, onFileOpen, onQueueAttachmentOpen }: ConversationFrameProps) {
  useEffect(() => {
    // Markdown dialogs portal outside the conversation's accent scope.
    const previous = document.body.style.getPropertyValue("--active-chat-accent");
    document.body.style.setProperty("--active-chat-accent", model.ally.accent);
    return () => {
      if (previous) document.body.style.setProperty("--active-chat-accent", previous);
      else document.body.style.removeProperty("--active-chat-accent");
    };
  }, [model.ally.accent]);
  const shellRef = useRef<HTMLDivElement>(null);
  const headerAnchorRef = useRef<HTMLSpanElement>(null);
  const threadAnchorRef = useRef<HTMLSpanElement>(null);
  const latestUser = model.messages.findLast((message) => message.sender === "user" && !message.queued);
  const currentTurn = model.turns.findLast((turn) => turn.messageId === latestUser?.id);
  const claimedWork = model.showThinkingState && latestUser?.queueState === "claimed";
  const confirmedWork = model.showThinkingState && (claimedWork || model.activityState === "running" || currentTurn?.state === "running" || model.responseStarted);
  const latestReply = model.messages.findLast((message) => message.sender === "assistant" && latestUser && message.sequence > latestUser.sequence);
  const completedReplyKey = currentTurn?.state === "completed"
    ? `${currentTurn.messageId}:${currentTurn.turnOrdinal}`
    : latestReply?.id ?? null;
  const [wakeEvidence, setWakeEvidence] = useState({ intent: runtimeIntentStatus, completedReplyKey, confirmed: false, invalidated: false });
  // Polling can deliver the completed reply without ever rendering a running turn.
  const receivedReply = completedReplyKey !== null && completedReplyKey !== wakeEvidence.completedReplyKey;
  const invalidated = sleeping || (!confirmedWork && !receivedReply && wakeEvidence.invalidated && wakeEvidence.intent === runtimeIntentStatus);
  const wakeConfirmed = !sleeping && (confirmedWork || receivedReply || (!invalidated && (runtimeIntentStatus === "ready" || runtimeIntentStatus === "already_ready"))
    || (!invalidated && wakeEvidence.confirmed));
  if (wakeEvidence.intent !== runtimeIntentStatus || wakeEvidence.completedReplyKey !== completedReplyKey || wakeEvidence.confirmed !== wakeConfirmed || wakeEvidence.invalidated !== invalidated) {
    setWakeEvidence({ intent: runtimeIntentStatus, completedReplyKey, confirmed: wakeConfirmed, invalidated });
  }
  const [staleIntent, setStaleIntent] = useState<ProductionRuntimeIntentStatus>(null);
  useEffect(() => {
    if (sleeping || model.gettingReady || (runtimeIntentStatus !== "requesting" && runtimeIntentStatus !== "waking" && runtimeIntentStatus !== "failed" && runtimeIntentStatus !== "rate_limited" && runtimeIntentStatus !== "first_provision_required" && runtimeIntentStatus !== "disabled")) return;
    const timer = window.setTimeout(() => setStaleIntent(runtimeIntentStatus), WAKE_HINT_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [runtimeIntentStatus, sleeping, model.gettingReady]);
  const hintExpired = staleIntent !== null && staleIntent === runtimeIntentStatus && !sleeping && !model.gettingReady && !confirmedWork && !receivedReply;
  const wakeConfirmedWithHint = wakeConfirmed || (!invalidated && hintExpired);
  const wakePending = !confirmedWork && !wakeConfirmedWithHint && (invalidated || model.gettingReady || runtimeIntentStatus === "requesting" || runtimeIntentStatus === "waking");
  const wakeUnconfirmed = !confirmedWork && !wakeConfirmedWithHint && !sleeping && (runtimeIntentStatus === "failed" || runtimeIntentStatus === "rate_limited" || runtimeIntentStatus === "first_provision_required" || runtimeIntentStatus === "disabled");
  const waking = !confirmedWork && !wakeConfirmedWithHint && (runtimeIntentStatus === "requesting" || runtimeIntentStatus === "waking" || model.gettingReady || (!sleeping && (wakePending || wakeUnconfirmed)));
  const docked = sleeping && !waking;
  const actorState = docked ? "sleeping" : confirmedWork ? "thinking" : "idle";
  const statusText = sleeping ? `${model.ally.name} is asleep` : `${model.ally.name} is waking up`;
  const activityIsCurrent = model.showThinkingState && (
    currentTurn
      ? currentTurn.state === "queued" || currentTurn.state === "running" || currentTurn.state === "awaiting_action"
      : model.activityState === "queued" || model.activityState === "running" || model.activityState === "awaiting_action"
  );
  const currentGroup = activityIsCurrent
    ? model.activityGroups.findLast((group) => group.messageId === latestUser?.id
      && (!currentTurn || group.conversationTurnOrdinal === currentTurn.turnOrdinal))
    : undefined;
  const visibleMessages = model.messages.filter((message) => !message.queued);
  const routineItems = model.routineItems ?? EMPTY_ROUTINE_ITEMS;
  const routineStates = useRef(new Map<string, { kind: string; approvalStatus: string | null }>());
  useEffect(() => {
    const next = new Map<string, { kind: string; approvalStatus: string | null }>();
    for (const item of routineItems) {
      const key = `${item.routineId}:${item.runId ?? item.id}`;
      const previous = routineStates.current.get(key);
      if (previous?.kind === "running" && item.kind === "result"
        && ["succeeded", "changed", "unchanged"].includes(item.status)
        && document.visibilityState === "visible") {
        playInteractionSound("success", { emphasis: "subtle" });
      } else if (previous?.kind === "running" && item.kind === "running"
        && previous.approvalStatus !== "pending" && item.approvalStatus === "pending"
        && document.visibilityState === "visible") {
        playInteractionSound("attention", { emphasis: "subtle" });
      }
      next.set(key, { kind: item.kind, approvalStatus: item.approvalStatus });
    }
    routineStates.current = next;
  }, [routineItems]);
  const [selectedRun, setSelectedRun] = useState<(typeof routineItems)[number] | null>(null);
  const [expandedDoc, setExpandedDoc] = useState<{ createdAt: string; text: string } | null>(null);
  const runDetail = selectedRun ? routineItems.find((item) => selectedRun.runId && item.kind === "result" && item.runId === selectedRun.runId && item.routineId === selectedRun.routineId && item.conversationId === selectedRun.conversationId)
    ?? routineItems.find((item) => item.id === selectedRun.id && item.kind === selectedRun.kind) : null;
  const triggeredAt = runDetail?.runId ? routineItems.find((item) => item.kind === "running" && item.runId === runDetail.runId && item.routineId === runDetail.routineId && item.conversationId === runDetail.conversationId)?.occurredAt : null;
  const routinesByMessage = new Map<string | null, typeof routineItems>();
  for (const item of routineItems) {
    const anchor = routineMessageAnchor(item, visibleMessages);
    const group = routinesByMessage.get(anchor) ?? [];
    group.push(item);
    routinesByMessage.set(anchor, group);
  }
  const [deleteFailed, setDeleteFailed] = useState(false);
  const [deletingRoutineId, setDeletingRoutineId] = useState<string | null>(null);
  const deleteButtonRef = useRef<HTMLButtonElement>(null);
  const routineSelectionRef = useRef(model.routineDetail?.routineId);
  useEffect(() => { routineSelectionRef.current = model.routineDetail?.routineId; }, [model.routineDetail?.routineId]);
  const renderRoutine = (item: (typeof routineItems)[number]) => (
    <RoutineProjection key={`${item.kind}:${item.id}`} item={item} actionState={model.routineAction}
      onOpen={() => { if (item.kind === "created") { setSelectedRun(null); actions.onOpenRoutine?.(item.routineId); } else { actions.onCloseRoutine?.(); setSelectedRun(item); } }} onAction={actions.onRoutineAction} />
  );
  const placementKey = `${visibleMessages.at(-1)?.id ?? "empty"}:${currentTurn?.turnOrdinal ?? ""}`;
  const topDate = formatConversationDateDivider(visibleMessages[0]?.createdAt ?? "");
  const [scrolledAway, setScrolledAway] = useState(false);
  const [showJumpLatest, setShowJumpLatest] = useState(false);
  const followVisualViewportRef = useRef(false);
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    const canvas = event.currentTarget;
    setScrolledAway(canvas.scrollTop > 12);
    setShowJumpLatest(canvas.scrollHeight - canvas.scrollTop - canvas.clientHeight > 96);
    if (document.activeElement instanceof HTMLTextAreaElement && shellRef.current?.contains(document.activeElement)) {
      followVisualViewportRef.current = event.currentTarget.scrollHeight
        - event.currentTarget.scrollTop
        - event.currentTarget.clientHeight < 96;
    }
    actions.onScroll(event);
  };

  useEffect(() => {
    const shell = shellRef.current;
    const viewport = window.visualViewport;
    if (!shell || !viewport) return;
    let frame = 0;
    let restingHeight = viewport.height;
    let restingWidth = window.innerWidth;
    const canvas = () => shell.querySelector<HTMLElement>('[data-testid="conversation-frame-canvas"]');
    const textareaIsFocused = () => document.activeElement instanceof HTMLTextAreaElement
      && shell.contains(document.activeElement);
    const sync = () => {
      const focused = textareaIsFocused();
      const unzoomed = Math.abs(viewport.scale - 1) < 0.05;
      if (Math.abs(window.innerWidth - restingWidth) > 80) {
        restingWidth = window.innerWidth;
        restingHeight = focused ? 0 : viewport.height;
      }
      if (!focused && unzoomed) restingHeight = Math.max(restingHeight, viewport.height);
      // iOS can shrink innerHeight and visualViewport.height together when typing.
      shell.toggleAttribute("data-keyboard-open", focused && unzoomed
        && Math.max(restingHeight, window.innerHeight) - viewport.height > 100);
      if (!textareaIsFocused()) {
        shell.style.removeProperty("--chat-viewport-height");
        shell.style.removeProperty("--chat-viewport-offset");
        return;
      }
      shell.style.setProperty("--chat-viewport-height", `${Math.round(viewport.height)}px`);
      shell.style.setProperty("--chat-viewport-offset", `${Math.round(viewport.offsetTop)}px`);
      window.cancelAnimationFrame(frame);
      if (followVisualViewportRef.current) {
        frame = window.requestAnimationFrame(() => {
          const messageCanvas = canvas();
          messageCanvas?.scrollTo({ top: messageCanvas.scrollHeight });
        });
      }
    };
    const handleFocusIn = (event: FocusEvent) => {
      if (!(event.target instanceof HTMLTextAreaElement)) return;
      const messageCanvas = canvas();
      followVisualViewportRef.current = Boolean(messageCanvas && messageCanvas.scrollHeight
        - messageCanvas.scrollTop
        - messageCanvas.clientHeight < 96);
      sync();
    };
    const handleFocusOut = () => window.requestAnimationFrame(sync);
    shell.addEventListener("focusin", handleFocusIn);
    shell.addEventListener("focusout", handleFocusOut);
    viewport.addEventListener("resize", sync);
    viewport.addEventListener("scroll", sync);
    window.addEventListener("resize", sync);
    sync();
    return () => {
      window.cancelAnimationFrame(frame);
      shell.removeEventListener("focusin", handleFocusIn);
      shell.removeEventListener("focusout", handleFocusOut);
      viewport.removeEventListener("resize", sync);
      viewport.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
      shell.removeAttribute("data-keyboard-open");
      shell.style.removeProperty("--chat-viewport-height");
      shell.style.removeProperty("--chat-viewport-offset");
    };
  }, []);

  const jumpToLatest = () => {
    const shell = shellRef.current;
    const canvas = shell?.querySelector<HTMLElement>('[data-testid="conversation-frame-canvas"]');
    if (!canvas) return;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    canvas.scrollTo({ top: canvas.scrollHeight, behavior: reducedMotion ? "auto" : "smooth" });
  };

  const hasTerminalTurn = model.turns.some((turn) => (
    turn.state === "failed"
    || turn.state === "stopped"
    || turn.state === "reconciliation_needed"
  ));
  const turnForMessage = (messageId: string, sequence: number) => model.turns.find(
    (turn) => turn.messageId === messageId && turn.turnOrdinal === sequence,
  );
  const activitiesForMessage = (messageId: string, turn?: ProductionConversationTurnModel) =>
    model.activityGroups.filter((group) => (
      group.messageId === messageId
      && (!turn || group.conversationTurnOrdinal === turn.turnOrdinal)
    ));
  const routineDetailState = model.routineDetail;
  const routineDetail = routineDetailState?.detail;

  return (
    <ConversationShell shellRef={shellRef} className={styles.frameProduction} accent={model.ally.accent} scrolled={scrolledAway || docked}>
      <ConversationHeader
        name={model.ally.name}
        subtitle={model.ally.job}
        homeHref="/home"
        settingsHref={settingsHref}
        onSettings={onOpenSettings}
        sleeping={docked}
        avatar={null}
        statusContent={docked ? (
          <div className={styles.frameSleepingStatus} data-testid="ally-sleeping-status" role="status">
            <span ref={headerAnchorRef} className={styles.framePresenceHeaderSlot} aria-hidden="true" />
            <span key={statusText} className={styles.framePresenceLabel}>{statusText}</span>
          </div>
        ) : null}
      />
      {!scrolledAway && !docked && topDate ? (
        <DateDivider sticky>{topDate}</DateDivider>
      ) : null}

      <ConversationCanvas canvasRef={canvasRef} onScroll={handleScroll}>
        <ConversationRail>
          {model.timeline.accessCopy ? (
            <FrameError>
              <strong>{model.timeline.accessCopy.title}</strong>{" "}
              {model.timeline.accessCopy.detail}
            </FrameError>
          ) : (
            <>
          {model.timeline.isLoading ? (
            <p className={styles.frameQuietState}>Opening your conversation…</p>
          ) : null}
          {model.timeline.loadError ? (
            <FrameError action="Try again" onAction={actions.onRetryConversation}>
              {model.timeline.loadError}
            </FrameError>
          ) : null}
          {model.timeline.olderLoadError ? (
            <FrameError action="Try again" onAction={actions.onLoadOlder}>
              {model.timeline.olderLoadError}
            </FrameError>
          ) : model.timeline.olderMessagesAvailable ? (
            <button
              className={styles.frameOlderButton}
              type="button"
              onClick={actions.onLoadOlder}
              disabled={model.timeline.loadingOlder}
            >
              {model.timeline.loadingOlder ? "Loading…" : "Earlier messages"}
            </button>
          ) : null}

          {model.timeline.workspaceRefreshError ? (
            <FrameError action="Try again" onAction={actions.onRetryWorkspace}>
              We couldn&apos;t refresh your Allies. Your current workspace is still shown.
            </FrameError>
          ) : null}

          {!model.timeline.isLoading && !model.timeline.loadError && model.messages.length === 0 && routineItems.length === 0 ? (
            <p className={styles.frameQuietState}>No messages yet</p>
          ) : null}

          {routinesByMessage.get(null)?.map(renderRoutine)}
          {visibleMessages.map((message, index) => {
            const turn = message.sender === "user"
              ? turnForMessage(message.id, message.sequence)
              : undefined;
            const activityGroups = message.sender === "user"
              ? activitiesForMessage(message.id, turn)
              : [];
            const intervalDate = index > 0
              ? conversationDateDividerAt(message.createdAt, visibleMessages[index - 1]?.createdAt)
              : "";
            const messagePublications = publications?.(message.id);

            return (
              <div className={styles.frameMessageRow} key={message.id} data-message-id={message.id} data-sequence={message.sequence}>
                {intervalDate ? <DateDivider>{intervalDate}</DateDivider> : null}
                {message.sender === "user" ? (
                  <UserBubble
                    createdAt={message.createdAt}
                    status={message.statusLabel}
                    retryable={message.retryable && !model.retriedMessageIds.includes(message.id)}
                    retrying={model.retryingMessageId === message.id}
                    onRetry={() => actions.onRetryMessage(message.id)}
                  >
                    {messageAttachments?.(message.id)}
                    <RoutineUserText text={message.content} onOpen={actions.onOpenRoutine} />
                  </UserBubble>
                ) : (
                  <>
                    <AssistantMessage createdAt={message.createdAt}>
                      <Streamdown mode="static" parseIncompleteMarkdown tableMaxHeight="none" components={routineLinkComponents(actions.onOpenRoutine, onFileOpen)}>
                        {message.content}
                      </Streamdown>
                    </AssistantMessage>
                    {isLongDocument(message.content) ? (
                      <button
                        type="button"
                        className={styles.frameExpandDoc}
                        onClick={() => setExpandedDoc({ createdAt: message.createdAt, text: message.content })}
                        aria-label="Expand full message"
                      >
                        Expand
                      </button>
                    ) : null}
                  </>
                )}

                {turn ? <TurnMessage
                  model={model}
                  turn={turn}
                  muteReadySound={routineItems.some((item) => item.kind === "result" && item.sourceMessageId === turn.messageId && ["succeeded", "changed", "unchanged"].includes(item.status))}
                  announceOnMount={message.id === latestUser?.id && model.responseStarted}
                  onOpenRoutine={actions.onOpenRoutine}
                  onOpenFile={onFileOpen}
                /> : null}
                {messagePublications ? <div className={styles.frameMessagePublications}>{messagePublications}</div> : null}
                {activityGroups.filter((group) => docked || group.key !== currentGroup?.key).map((group) => (
                  <ActivityGroup key={group.key} group={group} />
                ))}
                {docked || message.id !== currentGroup?.messageId ? <ConversationApprovalSlot messageId={message.id} /> : null}
                {routinesByMessage.get(message.id)?.map(renderRoutine)}
              </div>
            );
          })}

          <div className={styles.framePresenceRow} data-docked={docked}>
            <span ref={threadAnchorRef} className={styles.framePresenceThreadSlot} aria-hidden="true" />
            <div className={styles.framePresenceActivity}>
              {waking ? <span className={`${styles.framePresenceLabel} ${styles.frameThinkingLabel}`} role="status" aria-label="Waking up"><ShinyText color="var(--chat-accent)">Waking up</ShinyText></span> : !docked && currentGroup ? <ActivityGroup key={currentGroup.key} group={currentGroup} ongoing={activityIsCurrent && model.activityState !== "awaiting_action"} responseInProgress={activityIsCurrent} replying={model.responseStarted} /> : !docked && model.showThinkingState ? (
                <span className={`${styles.framePresenceLabel} ${styles.frameThinkingLabel}`} role="status" aria-label={model.responseStarted ? "Replying" : "Thinking"}><ShinyText color="var(--chat-accent)">{model.responseStarted ? "Replying.." : "Thinking.."}</ShinyText></span>
              ) : null}
              {!docked && currentGroup ? <ConversationApprovalSlot messageId={currentGroup.messageId} /> : null}
            </div>
          </div>

          {!model.streaming && !hasTerminalTurn && model.activityState === "awaiting_action" ? (
            <AssistantMessage>This Ally is waiting for an action.</AssistantMessage>
          ) : null}
          {!model.streaming && !hasTerminalTurn && (model.activityState === "failed" || model.activityState === "stopped") ? (
            <AssistantMessage>
              {model.activityState === "failed"
                ? "This response failed. Try sending your message again."
                : "This response was stopped."}
            </AssistantMessage>
          ) : null}
          {!model.streaming && isTerminalActivityState(model.activityState) && model.pendingAssistantText.length > 0 ? (
            <>
              {model.pendingAssistantText.map((text, index) => (
                <AssistantMessage key={`${text}-${index}`} testId={`activity-pending-${index}`}>
                  {text}
                </AssistantMessage>
              ))}
              <FrameError role="status">Some response text arrived out of order.</FrameError>
            </>
          ) : null}

          <ConversationApprovalSlot visibleMessageIds={new Set(visibleMessages.map((message) => message.id))} />
          {model.timeline.pollBudgetReached ? (
            <FrameError action="Check again" onAction={actions.onCheckAgain}>
              Status checking is paused.
            </FrameError>
          ) : null}
          {model.timeline.activityError ? (
            <FrameError action="Check again" onAction={actions.onCheckAgain}>
              {model.timeline.activityError}
            </FrameError>
          ) : null}
          {model.timeline.activityReplayUnavailable ? (
            <FrameError action="Check again" onAction={actions.onRetryActivityHistory}>
              Activity history is unavailable.
            </FrameError>
          ) : null}
          {model.timeline.activityHistoryError ? (
            <FrameError action="Check again" onAction={actions.onRetryActivityHistory}>
              {model.timeline.activityHistoryError}
            </FrameError>
          ) : null}
              {model.timeline.retryError ? <FrameError>{model.timeline.retryError}</FrameError> : null}
            </>
          )}
        </ConversationRail>
        {showJumpLatest ? (
          <div className={styles.frameJumpLatestWrap} aria-live="polite">
            <button type="button" className={styles.frameJumpLatest} onClick={jumpToLatest}>
              Jump to latest ↓
            </button>
          </div>
        ) : null}
      </ConversationCanvas>

      {!model.timeline.accessCopy ? <ConversationPresence ally={model.ally} state={actorState} stateReady={stateReady}
        docked={docked} muted={docked || waking} placementKey={placementKey}
        layoutVersion={`${statusText}:${model.messages.reduce((sum, message) => sum + message.content.length, 0) + model.turns.reduce((sum, turn) => sum + turn.assistantText.length, 0)}`} shellRef={shellRef}
        headerRef={headerAnchorRef} threadRef={threadAnchorRef} /> : null}

      <footer className={styles.frameComposerArea}>
        {fileRecovery}
        {model.composer.unavailableNotice ? (
          <p className={styles.frameComposerNotice}>{model.composer.unavailableNotice}</p>
        ) : null}
        {model.composer.sendError ? <p className={styles.frameComposerError} role="alert">{model.composer.sendError}</p> : null}
        {model.queuedMessages.length > 0 ? (
          <QueueStack items={model.queuedMessages} onRemove={actions.onRemoveQueuedMessage} onAttachmentOpen={onQueueAttachmentOpen} />
        ) : null}
        <ConversationComposer
          attachments={attachments}
          onAttach={onAttach}
          onFilesDrop={onFilesDrop}
          dropScope={model.ally.name}
          allyName={model.ally.name}
          value={model.composer.draft}
          placeholder={model.composer.placeholder}
          disabled={model.composer.disabled}
          sending={model.composer.sending}
          onChange={actions.onDraftChange}
          onSubmit={() => actions.onSubmit(!docked && !waking && !model.showThinkingState && model.queuedMessages.length === 0)}
          onCompositionStart={actions.onCompositionStart}
          onCompositionEnd={actions.onCompositionEnd}
        />
      </footer>

      {expandedDoc ? (
        <BottomSheet title="Full message" modal onClose={() => setExpandedDoc(null)} className={styles.frameDocPreviewOverlay}>
          <p className={styles.frameDocPreviewMeta}>{formatConversationDateDivider(expandedDoc.createdAt)}</p>
          <div className={styles.frameDocPreviewBody}>
            <Streamdown mode="static" parseIncompleteMarkdown tableMaxHeight="none">
              {expandedDoc.text}
            </Streamdown>
          </div>
        </BottomSheet>
      ) : null}

      {runDetail ? (
        <BottomSheet title="Routine run details" modal onClose={() => setSelectedRun(null)} className={styles.frameRoutineDetailOverlay}>
          <RoutineRunDetail title={runDetail.titleSnapshot} status={routineProjectionStatus(runDetail)}
            schedule={formatRoutineSchedule(runDetail.schedule)}
            triggeredAt={formatRoutineDate(triggeredAt ?? null, runDetail.schedule.timezone)}
            reportedAt={runDetail.kind === "result" ? formatRoutineDate(runDetail.occurredAt, runDetail.schedule.timezone) : null}
            failed={runDetail.status === "failed"}
            text={runDetail.resultInsertion === "inserted" ? runDetail.text : null} />
        </BottomSheet>
      ) : routineDetailState?.routineId ? (
        <BottomSheet title={deletingRoutineId === routineDetailState.routineId ? "Delete routine" : "Routine details"} modal closeDisabled={model.routineAction?.status === "sending"} onClose={() => { setDeletingRoutineId(null); actions.onCloseRoutine?.(); }} className={`${styles.frameRoutineDetailOverlay} ${deletingRoutineId === routineDetailState.routineId ? styles.frameRoutineDeleteOverlay : ""}`}>
          {routineDetail && deletingRoutineId === routineDetail.routineId ? (
            <DeleteRoutineSheet embedded failed={deleteFailed} title={routineDetail.title} disabled={model.routineAction?.status === "sending"}
              onCancel={() => { setDeletingRoutineId(null); window.requestAnimationFrame(() => deleteButtonRef.current?.focus()); }}
              onDelete={() => {
                if (!actions.onRoutineAction) return;
                setDeleteFailed(false);
                void actions.onRoutineAction({ action: "delete", routineId: routineDetail.routineId,
                  routineRevision: routineDetail.revision, titleSnapshot: routineDetail.title, confirmed: true,
                }).then((accepted) => {
                  if (routineSelectionRef.current !== routineDetail.routineId) return;
                  if (accepted) { setDeletingRoutineId(null); actions.onCloseRoutine?.(); }
                  else setDeleteFailed(true);
                }).catch(() => { if (routineSelectionRef.current === routineDetail.routineId) setDeleteFailed(true); });
              }} />
          ) : routineDetail ? (
            <RoutineChatDetail
              title={routineDetail.title}
              schedule={formatRoutineSchedule(routineDetail.schedule)}
              scheduleState={formatRoutineScheduleState(routineDetail.scheduleState)}
              deleteButtonRef={deleteButtonRef}
              nextRunAt={formatRoutineDate(routineDetail.nextRunAt, routineDetail.schedule.timezone)}
              executionPrompt={routineDetail.executionPrompt}
              canPauseResume={routineDetail.schedule.kind === "recurring"
                && (routineDetail.scheduleState === "active" || routineDetail.scheduleState === "paused")}
              canDelete={routineDetail.scheduleState !== "deleted"}
              pauseResumeLabel={routineDetail.scheduleState === "active"
                ? "Pause"
                : routineDetail.scheduleState === "paused" ? "Resume" : null}
              actionPending={model.routineAction?.routineId === routineDetailState.routineId && model.routineAction.status === "sending"}
              actionSent={model.routineAction?.routineId === routineDetailState.routineId && model.routineAction.status === "sent"}
              onPauseResume={() => {
                if (!actions.onRoutineAction) return;
                const action = routineDetail.scheduleState === "active" ? "pause" : "resume";
                if (action !== "pause" && action !== "resume") return;
                void actions.onRoutineAction({
                  action,
                  routineId: routineDetail.routineId,
                  routineRevision: routineDetail.revision,
                  titleSnapshot: routineDetail.title,
                });
              }}
              onDelete={() => {
                setDeleteFailed(false);
                setDeletingRoutineId(routineDetail.routineId);
              }}
            />
          ) : null}
          {routineDetailState.loading ? <p className={styles.frameQuietState} role="status">Loading routine details…</p> : null}
          {routineDetailState.error ? (
            <FrameError action="Try again" onAction={actions.onRetryRoutineDetail}>
              {routineDetailState.error}
            </FrameError>
          ) : null}
        </BottomSheet>
      ) : null}
    </ConversationShell>
  );
}

function RoutineProjection({
  item,
  actionState,
  onOpen,
  onAction,
}: {
  item: NonNullable<ProductionConversationFrameModel["routineItems"]>[number];
  actionState?: ProductionConversationFrameModel["routineAction"];
  onOpen: () => void;
  onAction?: (request: RoutineActionRequest) => Promise<boolean>;
}) {
  const actionLocked = Boolean(actionState
    && actionState.routineId === item.routineId
    && (actionState.action === "pause"
      || actionState.action === "resume"
      || actionState.action === "delete"
      ? item.kind === "created"
      : item.kind === "running"
        && (actionState.runId === null || actionState.runId === undefined || actionState.runId === item.runId)
        && (actionState.approvalRequestId === null || actionState.approvalRequestId === undefined || actionState.approvalRequestId === item.approvalRequestId)));
  const request = (action: RoutineActionRequest["action"]): RoutineActionRequest => ({
    action,
    routineId: item.routineId,
    routineRevision: item.routineRevision,
    titleSnapshot: item.titleSnapshot,
    runId: item.runId,
    approvalRequestId: item.approvalRequestId,
    approvalId: item.approvalId,
    executionId: item.executionId,
    attemptId: item.attemptId,
    generation: item.generation,
    actionAttemptId: item.actionAttemptId,
  });
  const dispatch = (action: RoutineActionRequest["action"]) => {
    if (!onAction || actionLocked) return;
    void onAction(request(action));
  };
  const approvalPending = item.kind === "running"
    && item.approvalRequestId !== null
    && item.approvalStatus === "pending";

  if (item.kind === "created") {
    return <RoutineChatProjectionCard name={item.titleSnapshot}
      schedule={formatRoutineSchedule(item.schedule, false)} status="" onOpen={onOpen} />;
  }
  const runStatus = item.kind === "result" && (item.status === "changed" || item.status === "unchanged" || item.status === "succeeded")
    ? "Succeeded" : item.status === "failed" ? "Failed" : routineProjectionStatus(item);
  return (
    <section className={styles.frameRoutineRun} aria-label="Routine run">
      <div className={styles.frameRoutineEvent}>
        <button type="button" className={styles.frameRoutineRunLink} onClick={onOpen} aria-label={`${item.titleSnapshot} · ${runStatus}`}>
          <svg aria-hidden="true" viewBox="0 0 24 24"><use href="/ally/icons/chat-routine.svg#icon" /></svg>
          <span className={styles.frameRoutineRunName} title={item.titleSnapshot}>{item.titleSnapshot}</span>
          <span className={styles.frameRoutineRunStatus} data-outcome={runStatus === "Succeeded" ? "success" : runStatus === "Failed" ? "failure" : undefined}>· {runStatus}</span>
        </button>
      </div>
      {item.kind === "running" && item.approvalStatus === "pending" ? (
        <p className={styles.frameRoutineProjectionDetail} role="status">
          Approval requested{item.approvalExpiresAt ? ` · expires ${formatRoutineDate(item.approvalExpiresAt)}` : ""}
        </p>
      ) : null}
      {item.kind === "result" && item.resultInsertion === "pending" ? (
        <p className={styles.frameRoutineProjectionDetail} role="status">Pending insertion — waiting to appear in chat.</p>
      ) : null}
      {item.kind === "result" && item.resultInsertion === "inserted" && item.text ? (
        <div>
          <AssistantMessage createdAt={item.occurredAt}>
            <Streamdown mode="static" parseIncompleteMarkdown tableMaxHeight="none">{item.text}</Streamdown>
          </AssistantMessage>
        </div>
      ) : null}
      {item.kind === "result" && item.resultInsertion === "inserted" && item.references.length > 0 ? (
        <ul className={styles.frameRoutineReferenceList} aria-label="Routine references">
          {item.references.map((reference) => (
            <li key={`${reference.url}:${reference.label}`}><a href={reference.url} target="_blank" rel="noreferrer">{reference.label}</a></li>
          ))}
        </ul>
      ) : null}
      {approvalPending && onAction ? (
        <div className={styles.frameRoutineProjectionActions}>
          <button type="button" className={styles.frameNeutralAction} onClick={() => dispatch("reject")} disabled={actionLocked}>Reject</button>
          <button type="button" className={styles.frameAccentAction} onClick={() => dispatch("approve")} disabled={actionLocked}>Approve</button>
          <button type="button" className={styles.frameNeutralAction} onClick={() => dispatch("cancel")} disabled={actionLocked}>Cancel</button>
        </div>
      ) : null}
      {actionLocked ? <p className={styles.frameRoutineActionNotice} role="status">{actionState?.status === "sending" ? "Sending request…" : "Request sent to Ally."}</p> : null}
    </section>
  );
}

function routineProjectionStatus(item: NonNullable<ProductionConversationFrameModel["routineItems"]>[number]): string {
  if (item.kind === "created") return "";
  if (item.kind === "running") {
    if (item.approvalStatus && item.approvalStatus !== "pending") {
      return `Approval ${formatRoutineToken(item.approvalStatus)}`;
    }
    return {
      queued: "Run queued",
      working: "Routine is running",
      approval_waiting: "Waiting for approval",
      succeeded: "Run completed",
      failed: "Run failed",
      cancelled: "Run cancelled",
      expired: "Approval expired",
    }[item.status] ?? formatRoutineToken(item.status);
  }
  if (item.status === "changed") return "Completed · changed";
  if (item.status === "unchanged") return "Completed · no changes";
  if (item.status === "failed") return "Run failed";
  return formatRoutineToken(item.status);
}

export function formatRoutineSchedule(schedule: NonNullable<ProductionConversationFrameModel["routineItems"]>[number]["schedule"], includeTimezone = true): string {
  const timezone = includeTimezone ? ` · ${schedule.timezone}` : "";
  if (schedule.kind === "once") {
    const date = new Date(`${schedule.localAt}Z`);
    return `${date.toLocaleString([], { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" })}${timezone}`;
  }
  const localTime = schedule.localTime?.slice(0, 5) ?? "the scheduled time";
  if (schedule.frequency === "daily") return `${localTime} every day${timezone}`;
  if (schedule.frequency === "weekly") {
    const days = (schedule.daysOfWeek ?? []).map((day) => ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day] ?? "").filter(Boolean).join(", ");
    return `${localTime} every ${days}${timezone}`;
  }
  return `Monthly · day ${schedule.dayOfMonth ?? "—"} at ${localTime}${timezone}`;
}

function formatRoutineDate(value: string | null, timeZone?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "short", timeZone });
}

function formatRoutineScheduleState(value: string): string {
  return formatRoutineToken(value);
}

function formatRoutineToken(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function isTerminalActivityState(state: ProductionConversationFrameModel["activityState"]): boolean {
  return state !== "queued" && state !== "running";
}

function responseOutcomeAnnouncement(state: ProductionConversationTurnModel["state"]): string | null {
  if (state === "completed") return "Response complete";
  if (state === "failed") return "Response failed";
  if (state === "stopped") return "Response stopped";
  return null;
}

function TurnMessage({
  model,
  turn,
  muteReadySound,
  announceOnMount,
  onOpenRoutine,
  onOpenFile,
}: {
  model: ProductionConversationFrameModel;
  turn: ProductionConversationTurnModel;
  muteReadySound: boolean;
  announceOnMount: boolean;
  onOpenRoutine?: (id: string) => void;
  onOpenFile?: (id: string) => void;
}) {
  const pending = turn.state === "queued" || turn.state === "running" || turn.state === "awaiting_action";
  const [presentation, setPresentation] = useState({
    state: turn.state,
    reveal: false,
    announcement: announceOnMount && !model.timeline.isLoading
      ? responseOutcomeAnnouncement(turn.state)
      : null,
  });
  if (presentation.state !== turn.state) {
    const wasPending = ["queued", "running", "awaiting_action"].includes(presentation.state);
    const previousOutcome = responseOutcomeAnnouncement(presentation.state);
    const nextOutcome = responseOutcomeAnnouncement(turn.state);
    const announcement = !model.timeline.isLoading
      && nextOutcome
      && (wasPending || (previousOutcome !== null && previousOutcome !== nextOutcome))
      ? nextOutcome
      : null;
    setPresentation({ state: turn.state, reveal: announcement === "Response complete", announcement });
  }
  useEffect(() => {
    if (!presentation.announcement) return;
    if (presentation.announcement === "Response complete" && !muteReadySound && document.visibilityState === "visible") {
      playInteractionSound("ready", { emphasis: "subtle" });
    }
    const timer = setTimeout(() => setPresentation((current) => ({ ...current, reveal: false, announcement: null })), 2800);
    return () => clearTimeout(timer);
  }, [muteReadySound, presentation.announcement]);
  const pendingText = model.responsePresentationMode === "paragraph" && pending
    ? completedParagraphs(turn.assistantText)
    : turn.assistantText;
  const live = pending
    && (model.responsePresentationMode === "stream" || model.responsePresentationMode === "paragraph")
    && Boolean(pendingText);
  if (pending && !live) return null;
  if (turn.state === "reconciliation_needed") {
    return (
      <AssistantMessage testId={`activity-reply-${turn.turnOrdinal}`}>
        This response needs review because some activity arrived out of order.
      </AssistantMessage>
    );
  }
  const statusText = turn.state === "failed"
    ? "This response failed."
    : turn.state === "stopped" ? "This response was stopped." : null;
  if (!pendingText && !statusText && !turn.isTruncated) return null;
  const reveal = presentation.reveal || live;
  return (
    <AssistantMessage createdAt={turn.createdAt} testId={`activity-reply-${turn.turnOrdinal}`}>
      {pending || presentation.announcement ? (
        <span
          className={styles.frameSrOnly}
          role="status"
          aria-live="polite"
          aria-atomic="true"
          aria-label={pending ? "Response in progress" : presentation.announcement ?? undefined}
        />
      ) : null}
      {pendingText ? <Streamdown
        components={routineLinkComponents(onOpenRoutine, onOpenFile)}
        tableMaxHeight="none"
        mode={reveal ? "streaming" : "static"}
        animated={reveal ? { animation: "blurIn", sep: "word", duration: 180, stagger: 24, maxBacklogMs: 2400 } : false}
        isAnimating={reveal}
      >
        {pendingText}
      </Streamdown> : null}
      {statusText ? <p>{statusText}</p> : null}
      {turn.isTruncated ? <p>This response reached its length limit.</p> : null}
    </AssistantMessage>
  );
}

function ActivityGroup({ group, ongoing = false, responseInProgress = false, replying = false }: { group: ProductionConversationActivityGroupModel; ongoing?: boolean; responseInProgress?: boolean; replying?: boolean }) {
  const active = group.entries.findLast((entry) => entry.activityId && !entry.outcome && entry.kind === "activity_started");
  const current = active ?? group.entries.at(-1);
  const [disclosure, setDisclosure] = useState({ responseInProgress, open: responseInProgress });
  if (disclosure.responseInProgress !== responseInProgress) {
    setDisclosure({ responseInProgress, open: responseInProgress });
  }
  if (!group.entries.length) return null;
  return (
    <ActivityDisclosure
      label={ongoing ? replying ? "Replying…" : current ? activityText(current, true) : "Thinking…" : `${group.entries.length} ${group.entries.length === 1 ? "activity" : "activities"}`}
      ongoing={ongoing}
      open={disclosure.open}
      onToggle={(open) => setDisclosure((current) => current.open === open ? current : { ...current, open })}
      entries={group.entries.map((entry) => ({
        id: entry.id,
        text: activityText(entry),
        activityKind: entry.approval ? "approval" : entry.activityKind,
        durationMs: entry.durationMs,
        tone: entry.kind === "awaiting_action"
          ? "accent"
          : entry.outcome || !ongoing
            ? "muted"
            : "default",
      }))}
    />
  );
}

export function isLongDocument(text: string): boolean {
  return text.length >= 2000 || text.split("\n").length >= 20;
}

function activityText(entry: ProductionConversationActivityGroupModel["entries"][number], ongoing = false) {
  if (ongoing && entry.ongoingText) return entry.ongoingText;
  if (entry.activityKind !== "terminal") return entry.text;
  if (entry.outcome && entry.outcome !== "completed") return entry.text;
  return entry.outcome || entry.kind === "activity_completed" ? "Ran a command" : "Running a command";
}
