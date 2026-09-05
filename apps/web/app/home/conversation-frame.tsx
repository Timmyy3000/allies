"use client";

import { Streamdown } from "streamdown";
import { useState, type Ref, type UIEvent } from "react";

import type {
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
  AllyFrameAvatar,
  AssistantIdentity,
  AssistantMessage,
  ConversationCanvas,
  ConversationComposer,
  ConversationHeader,
  ConversationRail,
  ConversationShell,
  DateDivider,
  FrameError,
  QueueStack,
  ThinkingStatus,
  UserBubble,
} from "./conversation-frame-primitives";
import styles from "./conversation-frame.module.css";

export interface ConversationFrameProps {
  model: ProductionConversationFrameModel;
  actions: ProductionConversationFrameActions;
  canvasRef?: Ref<HTMLDivElement>;
  sleeping?: boolean;
  stateReady?: boolean;
}

export function ConversationFrame({ model, actions, canvasRef, sleeping = false, stateReady = true }: ConversationFrameProps) {
  const topDate = formatConversationDateDivider(model.messages[0]?.createdAt ?? "");
  const [scrolledAway, setScrolledAway] = useState(false);
  const handleScroll = (event: UIEvent<HTMLDivElement>) => {
    setScrolledAway(event.currentTarget.scrollTop > 12);
    actions.onScroll(event);
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

  return (
    <ConversationShell accent={model.ally.accent} scrolled={scrolledAway}>
      <ConversationHeader
        name={model.ally.name}
        subtitle={model.ally.job}
        homeHref="/home"
        settingsHref="/account"
        sleeping={sleeping}
        avatar={(
          <ProductionAllyAvatar
            ally={model.ally}
            size={40}
            stateReady={stateReady}
            state={model.gettingReady || model.showThinkingState ? "thinking" : sleeping ? "sleeping" : "idle"}
          />
        )}
        sleepingAvatar={(
          <ProductionAllyAvatar
            ally={model.ally}
            size={24}
            stateReady={stateReady}
            state="sleeping"
          />
        )}
      />
      {!scrolledAway && !sleeping && topDate ? (
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
          {model.timeline.setupNotice ? (
            <FrameError role="status">{model.timeline.setupNotice}</FrameError>
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

          {model.messages.map((message, index) => {
            const turn = message.sender === "user"
              ? turnForMessage(message.id, message.sequence)
              : undefined;
            const activityGroups = message.sender === "user"
              ? activitiesForMessage(message.id, turn)
              : [];
            const showAllyIdentity = message.sender === "assistant"
              && message.id === model.firstAssistantMessageId;
            const intervalDate = index > 0
              ? conversationDateDividerAt(message.createdAt, model.messages[index - 1]?.createdAt)
              : "";

            return (
              <div className={styles.frameMessageRow} key={message.id}>
                {intervalDate ? <DateDivider>{intervalDate}</DateDivider> : null}
                {message.sender === "user" ? (
                  <UserBubble
                    status={message.statusLabel}
                    retryable={message.retryable && !model.retriedMessageIds.includes(message.id)}
                    retrying={model.retryingMessageId === message.id}
                    onRetry={() => actions.onRetryMessage(message.id)}
                  >
                    {message.content}
                  </UserBubble>
                ) : (
                  <>
                    {showAllyIdentity ? (
                      <AssistantIdentity
                        name={model.ally.name}
                        avatar={(
                          <ProductionAllyAvatar ally={model.ally} size={36} />
                        )}
                      />
                    ) : null}
                    <AssistantMessage>
                      <Streamdown mode="static" parseIncompleteMarkdown>
                        {message.content}
                      </Streamdown>
                    </AssistantMessage>
                  </>
                )}

                {turn ? <TurnMessage model={model} turn={turn} /> : null}
                {activityGroups.map((group) => (
                  <ActivityGroup key={group.key} group={group} />
                ))}
              </div>
            );
          })}

          {model.gettingReady || model.showThinkingState ? (
            <ThinkingStatus
              label={model.gettingReady ? "Getting ready" : "Thinking"}
              iconOnly={!model.gettingReady && model.responseStarted}
              avatar={(
                <ProductionAllyAvatar ally={model.ally} size={32} state="thinking" />
              )}
            />
          ) : null}

          {!model.streaming && !hasTerminalTurn && model.activityState === "awaiting_action" ? (
            <AssistantMessage>This Ally needs an action Home cannot complete yet.</AssistantMessage>
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
          onSubmit={actions.onSubmit}
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
  const isStreaming = model.streaming && turn.state === "running";
  return (
    <AssistantMessage testId={`activity-reply-${turn.turnOrdinal}`}>
      {turn.assistantText ? <Streamdown
        mode={isStreaming ? "streaming" : "static"}
        parseIncompleteMarkdown
        animated={isStreaming ? { animation: "blurIn", sep: "word", duration: 180, stagger: 24 } : false}
        isAnimating={isStreaming}
      >
        {turn.assistantText}
      </Streamdown> : null}
      {statusText ? <p>{statusText}</p> : null}
      {turn.isTruncated ? <p>This response reached its length limit.</p> : null}
    </AssistantMessage>
  );
}

function ActivityGroup({ group }: { group: ProductionConversationActivityGroupModel }) {
  const [first, ...rest] = group.entries;
  if (!first) return null;
  return (
    <ActivityDisclosure
      label={first.text}
      entries={[first, ...rest].map((entry) => ({
        id: entry.id,
        text: entry.text,
        tone: entry.kind === "awaiting_action"
          ? "accent"
          : entry.state === "completed"
            ? "muted"
            : "default",
      }))}
    />
  );
}

function ProductionAllyAvatar({
  ally,
  size,
  state = "idle",
  stateReady = true,
}: {
  ally: ProductionConversationFrameModel["ally"];
  size: number;
  state?: "idle" | "thinking" | "sleeping";
  stateReady?: boolean;
}) {
  if (!ally.supportedAppearance) {
    return (
      <span
        className={styles.frameAppearanceUnavailable}
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
    <AllyFrameAvatar
      shape={ally.shape}
      accent={ally.accent}
      size={size}
      state={state}
      stateReady={stateReady}
      label={`${ally.name} avatar`}
    />
  );
}
