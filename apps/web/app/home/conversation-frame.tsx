"use client";

import { Streamdown } from "streamdown";
import { ShinyText } from "../../components/text-animations/shiny-text";
import { useEffect, useRef, useState, type Ref, type UIEvent } from "react";
import { ConversationPresence } from "./conversation-presence";
import { ConversationApprovalSlot } from "./conversation-approvals";

import type {
  ProductionRuntimeIntentStatus,
  ProductionConversationActivityGroupModel,
  ProductionConversationFrameActions,
  ProductionConversationFrameModel,
  ProductionConversationTurnModel,
} from "./conversation-frame-model";
import {
  conversationDateDividerAt,
  formatConversationDateDivider,
} from "./conversation-frame-model";
import {
  ActivityDisclosure,
  AssistantMessage,
  ConversationCanvas,
  ConversationComposer,
  ConversationHeader,
  ConversationRail,
  ConversationShell,
  DateDivider,
  FrameError,
  QueueStack,
  UserBubble,
} from "./conversation-frame-primitives";
import styles from "./conversation-frame.module.css";

export interface ConversationFrameProps {
  model: ProductionConversationFrameModel;
  actions: ProductionConversationFrameActions;
  canvasRef?: Ref<HTMLDivElement>;
  sleeping?: boolean;
  stateReady?: boolean;
  runtimeIntentStatus?: ProductionRuntimeIntentStatus;
}

export function ConversationFrame({ model, actions, canvasRef, sleeping = false, stateReady = true, runtimeIntentStatus = null }: ConversationFrameProps) {
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
  const confirmedWork = model.showThinkingState && (model.activityState === "running" || currentTurn?.state === "running" || model.responseStarted);
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
  const wakePending = !confirmedWork && !wakeConfirmed && (invalidated || model.gettingReady || runtimeIntentStatus === "requesting" || runtimeIntentStatus === "waking");
  const wakeUnconfirmed = !confirmedWork && !wakeConfirmed && !sleeping && (runtimeIntentStatus === "failed" || runtimeIntentStatus === "rate_limited" || runtimeIntentStatus === "first_provision_required" || runtimeIntentStatus === "disabled");
  const waking = !confirmedWork && !wakeConfirmed && (runtimeIntentStatus === "requesting" || runtimeIntentStatus === "waking" || model.gettingReady || (!sleeping && (wakePending || wakeUnconfirmed)));
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
  const placementKey = `${visibleMessages.at(-1)?.id ?? "empty"}:${currentTurn?.turnOrdinal ?? ""}`;
  const topDate = formatConversationDateDivider(visibleMessages[0]?.createdAt ?? "");
  const [scrolledAway, setScrolledAway] = useState(false);
  const followVisualViewportRef = useRef(false);
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    setScrolledAway(event.currentTarget.scrollTop > 12);
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
    const canvas = () => shell.querySelector<HTMLElement>('[data-testid="conversation-frame-canvas"]');
    const textareaIsFocused = () => document.activeElement instanceof HTMLTextAreaElement
      && shell.contains(document.activeElement);
    const sync = () => {
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
    return () => {
      window.cancelAnimationFrame(frame);
      shell.removeEventListener("focusin", handleFocusIn);
      shell.removeEventListener("focusout", handleFocusOut);
      viewport.removeEventListener("resize", sync);
      viewport.removeEventListener("scroll", sync);
      shell.style.removeProperty("--chat-viewport-height");
      shell.style.removeProperty("--chat-viewport-offset");
    };
  }, []);

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

  return (
    <ConversationShell shellRef={shellRef} className={styles.frameProduction} accent={model.ally.accent} scrolled={scrolledAway || docked}>
      <ConversationHeader
        name={model.ally.name}
        subtitle={model.ally.job}
        homeHref="/home"
        settingsHref="/account"
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

          {!model.timeline.isLoading && !model.timeline.loadError && model.messages.length === 0 ? (
            <p className={styles.frameQuietState}>No messages yet</p>
          ) : null}

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

            return (
              <div className={styles.frameMessageRow} key={message.id}>
                {intervalDate ? <DateDivider>{intervalDate}</DateDivider> : null}
                {message.sender === "user" ? (
                  <UserBubble
                    createdAt={message.createdAt}
                    status={message.statusLabel}
                    retryable={message.retryable && !model.retriedMessageIds.includes(message.id)}
                    retrying={model.retryingMessageId === message.id}
                    onRetry={() => actions.onRetryMessage(message.id)}
                  >
                    {message.content}
                  </UserBubble>
                ) : (
                  <>
                    <AssistantMessage createdAt={message.createdAt}>
                      <Streamdown mode="static" parseIncompleteMarkdown tableMaxHeight="none">
                        {message.content}
                      </Streamdown>
                    </AssistantMessage>
                  </>
                )}

                {turn ? <TurnMessage model={model} turn={turn} /> : null}
                {activityGroups.filter((group) => docked || group.key !== currentGroup?.key).map((group) => (
                  <ActivityGroup key={group.key} group={group} />
                ))}
                {docked || message.id !== currentGroup?.messageId ? <ConversationApprovalSlot messageId={message.id} /> : null}
              </div>
            );
          })}

          <div className={styles.framePresenceRow} data-docked={docked}>
            <span ref={threadAnchorRef} className={styles.framePresenceThreadSlot} aria-hidden="true" />
            <div className={styles.framePresenceActivity}>
              {waking ? <span className={`${styles.framePresenceLabel} ${styles.frameThinkingLabel}`} role="status" aria-label="Waking up"><ShinyText color="var(--chat-accent)">Waking up</ShinyText></span> : !docked && currentGroup ? <ActivityGroup key={currentGroup.key} group={currentGroup} ongoing={activityIsCurrent && model.activityState !== "awaiting_action"} /> : !docked && model.showThinkingState ? (
                <span className={`${styles.framePresenceLabel} ${styles.frameThinkingLabel}`} role="status" aria-label="Thinking"><ShinyText color="var(--chat-accent)">Thinking..</ShinyText></span>
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
      </ConversationCanvas>

      {!model.timeline.accessCopy ? <ConversationPresence ally={model.ally} state={actorState} stateReady={stateReady}
        docked={docked} muted={docked || waking} placementKey={placementKey}
        layoutVersion={`${statusText}:${model.messages.reduce((sum, message) => sum + message.content.length, 0) + model.turns.reduce((sum, turn) => sum + turn.assistantText.length, 0)}`} shellRef={shellRef}
        headerRef={headerAnchorRef} threadRef={threadAnchorRef} /> : null}

      <footer className={styles.frameComposerArea}>
        {model.composer.unavailableNotice ? (
          <p className={styles.frameComposerNotice}>{model.composer.unavailableNotice}</p>
        ) : null}
        {model.composer.sendError ? <p className={styles.frameComposerError} role="alert">{model.composer.sendError}</p> : null}
        {model.queuedMessages.length > 0 ? (
          <QueueStack items={model.queuedMessages} onRemove={actions.onRemoveQueuedMessage} />
        ) : null}
        <ConversationComposer
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
    </ConversationShell>
  );
}

function isTerminalActivityState(state: ProductionConversationFrameModel["activityState"]): boolean {
  return state !== "queued" && state !== "running";
}

function TurnMessage({
  model,
  turn,
}: {
  model: ProductionConversationFrameModel;
  turn: ProductionConversationTurnModel;
}) {
  const pending = turn.state === "queued" || turn.state === "running" || turn.state === "awaiting_action";
  const [presentation, setPresentation] = useState({ state: turn.state, reveal: false });
  if (presentation.state !== turn.state) {
    const wasPending = ["queued", "running", "awaiting_action"].includes(presentation.state);
    setPresentation({ state: turn.state, reveal: wasPending && turn.state === "completed" && !model.timeline.isLoading });
  }
  useEffect(() => {
    if (!presentation.reveal) return;
    const timer = setTimeout(() => setPresentation((current) => ({ ...current, reveal: false })), 2800);
    return () => clearTimeout(timer);
  }, [presentation.reveal]);
  if (pending) return null;
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
  if (!turn.assistantText && !statusText && !turn.isTruncated) return null;
  const reveal = presentation.reveal;
  return (
    <AssistantMessage createdAt={turn.createdAt} testId={`activity-reply-${turn.turnOrdinal}`}>
      {turn.assistantText ? <Streamdown
        tableMaxHeight="none"
        mode={reveal ? "streaming" : "static"}
        animated={reveal ? { animation: "blurIn", sep: "word", duration: 180, stagger: 24, maxBacklogMs: 2400 } : false}
        isAnimating={reveal}
      >
        {turn.assistantText}
      </Streamdown> : null}
      {statusText ? <p>{statusText}</p> : null}
      {turn.isTruncated ? <p>This response reached its length limit.</p> : null}
    </AssistantMessage>
  );
}

function ActivityGroup({ group, ongoing = false }: { group: ProductionConversationActivityGroupModel; ongoing?: boolean }) {
  const active = group.entries.findLast((entry) => entry.activityId && !entry.outcome && entry.kind === "activity_started");
  const [disclosure, setDisclosure] = useState({ ongoing, open: false });
  if (disclosure.ongoing !== ongoing) setDisclosure({ ongoing, open: false });
  if (!group.entries.length) return null;
  return (
    <ActivityDisclosure
      label={ongoing ? active ? activityText(active) : "Thinking…" : `${group.entries.length} ${group.entries.length === 1 ? "activity" : "activities"}`}
      ongoing={ongoing}
      open={disclosure.open}
      onToggle={(open) => setDisclosure((current) => current.open === open ? current : { ...current, open })}
      entries={group.entries.map((entry) => ({
        id: entry.id,
        text: activityText(entry),
        activityKind: entry.activityKind,
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

function activityText(entry: ProductionConversationActivityGroupModel["entries"][number]) {
  if (entry.activityKind !== "terminal") return entry.text;
  if (entry.outcome && entry.outcome !== "completed") return entry.text;
  return entry.outcome || entry.kind === "activity_completed" ? "Ran a command" : "Running a command";
}
