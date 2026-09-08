import type {
  AssistantReplyViewModel,
  ActivityState,
  AllyViewModel,
  MessageViewModel,
  RuntimeIntentViewModel,
} from "@allies/cloud-client";
import type { ActivityProjection, AssistantTurnProjection } from "@allies/cloud-client";
import type { UIEvent } from "react";

import type {
  ActivityPresentationGroup,
  ActivityPresentationState,
} from "../../lib/allies/activity-presentation";
import type { AllyShape } from "../../components/ally-avatar";
import { conversationAccessCopy, type ConversationAccessFailure } from "./conversation-access-error";

export type ProductionRuntimeIntentStatus = RuntimeIntentViewModel["status"] | "requesting" | null;

export interface ProductionAllyFrameModel {
  name: string;
  job: string;
  shape: AllyShape;
  accent: string;
  supportedAppearance: boolean;
}

export interface ProductionConversationMessageModel {
  id: string;
  sender: MessageViewModel["sender"];
  content: string;
  sequence: number;
  createdAt: string;
  statusLabel: string | null;
  retryable: boolean;
  queued?: boolean;
}

export interface ProductionConversationTurnModel {
  assistantText: string;
  createdAt?: string;
  isTruncated?: boolean;
  messageId: string;
  state: ActivityState;
  turnOrdinal: number;
}

export interface ProductionConversationActivityGroupModel {
  key: string;
  messageId: string;
  conversationTurnOrdinal: number;
  entries: ActivityPresentationGroup["entries"];
}

export interface ProductionQueuedMessageModel {
  id: string;
  content: string;
  removable?: boolean;
  statusLabel?: string | null;
}

export interface ProductionConversationFrameModel {
  ally: ProductionAllyFrameModel;
  messages: ProductionConversationMessageModel[];
  turns: ProductionConversationTurnModel[];
  activityGroups: ProductionConversationActivityGroupModel[];
  activityState: ActivityState;
  pendingAssistantText: string[];
  timeline: {
    isLoading: boolean;
    loadError: string | null;
    accessFailure: ConversationAccessFailure | null;
    accessCopy: { title: string; detail: string } | null;
    olderMessagesAvailable: boolean;
    loadingOlder: boolean;
    olderLoadError: string | null;
    workspaceRefreshError: boolean;
    activityError: string | null;
    activityHistoryError: string | null;
    activityReplayUnavailable: boolean;
    pollBudgetReached: boolean;
    retryError: string | null;
  };
  composer: {
    draft: string;
    placeholder: string;
    disabled: boolean;
    sending: boolean;
    sendError: string | null;
    unavailableNotice: string | null;
  };
  queuedMessages: ProductionQueuedMessageModel[];
  showThinkingState: boolean;
  responseStarted: boolean;
  gettingReady: boolean;
  streaming: boolean;
  firstAssistantMessageId: string | null;
  retriedMessageIds: string[];
  retryingMessageId: string | null;
}

export interface ProductionConversationFrameInput {
  ally: AllyViewModel;
  resolvedAppearance: { shape: AllyShape; color: string };
  appearanceAvailable: boolean;
  messages: readonly MessageViewModel[];
  assistantReplies?: readonly AssistantReplyViewModel[];
  projection: ActivityProjection;
  activityPresentation: ActivityPresentationState;
  queuedMessages: readonly ProductionQueuedMessageModel[];
  queuedMessagesReady: boolean;
  activeMessageId?: string | null;
  activeMessageHasProgress?: boolean;
  draft: string;
  conversationAvailable: boolean;
  isLoading: boolean;
  loadError: string | null;
  accessFailure: ConversationAccessFailure | null;
  olderMessagesAvailable: boolean;
  loadingOlder: boolean;
  olderLoadError: string | null;
  workspaceRefreshError: boolean;
  activityError: string | null;
  activityHistoryError: string | null;
  activityReplayUnavailable: boolean;
  pollBudgetReached: boolean;
  retryError: string | null;
  sendError: string | null;
  unavailableNotice: string | null;
  sending: boolean;
  retryingMessageId: string | null;
  showThinkingState: boolean;
  responseStarted: boolean;
  gettingReady: boolean;
  streaming: boolean;
  retriedMessageIds: ReadonlySet<string>;
}

export interface ProductionConversationFrameActions {
  onDraftChange: (value: string) => void;
  onCompositionStart?: () => void;
  onCompositionEnd?: (value: string) => void;
  onSubmit: (showImmediately?: boolean) => void;
  onRetryMessage: (messageId: string) => void;
  onLoadOlder: () => void;
  onRetryConversation: () => void;
  onRetryWorkspace: () => void;
  onRemoveQueuedMessage: (id: string) => void;
  onCheckAgain: () => void;
  onRetryActivityHistory: () => void;
  onScroll: (event: UIEvent<HTMLDivElement>) => void;
}

export function formatConversationDateDivider(value: string, now = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  if (date.toDateString() === now.toDateString()) return "Today";

  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";

  const dateOptions: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (date.getFullYear() !== now.getFullYear()) dateOptions.year = "numeric";
  return date.toLocaleDateString([], dateOptions);
}

export function conversationMessageDateKey(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

export function conversationDateDividerAt(
  createdAt: string,
  previousCreatedAt?: string,
  now = new Date(),
): string {
  if (!createdAt) return "";
  if (
    previousCreatedAt
    && conversationMessageDateKey(createdAt) === conversationMessageDateKey(previousCreatedAt)
  ) {
    return "";
  }
  return formatConversationDateDivider(createdAt, now);
}

export function buildProductionConversationFrameModel(
  input: ProductionConversationFrameInput,
): ProductionConversationFrameModel {
  const accessCopy = input.accessFailure && input.accessFailure !== "recoverable"
    ? conversationAccessCopy(input.accessFailure)
    : null;
  const accessBlocked = Boolean(accessCopy);
  const turnsByMessage = new Map(
    input.projection.turns.map((turn) => [`${turn.messageId}:${turn.turnOrdinal}`, turn]),
  );
  const assistantReplies = input.assistantReplies ?? [];
  // Acceptance wakes the runtime; only actual turn progress releases its queue item.
  // Keep the durable message in the model so lifecycle/activity identity is preserved.
  const queuedIds = new Set(input.messages.filter((message) => {
    if (message.sender !== "user" || message.status !== "queued" || message.retryable) return false;
    const turn = turnsByMessage.get(`${message.id}:${message.sequence}`);
    if (turn?.messageId === message.id && turn.state !== "queued") return false;
    if (assistantReplies.some((reply) => reply.sourceMessageId === message.id)) return false;
    return !hasLegacyAssistantReply(input.messages, { messageId: message.id, turnOrdinal: message.sequence });
  }).map((message) => message.id));
  const firstAssistantMessageId = accessBlocked
    ? null
    : input.messages.find((message) => message.sender === "assistant")?.id ?? null;
  const messages = (accessBlocked ? [] : input.messages).map((message) => ({
    id: message.id,
    sender: message.sender,
    content: message.content,
    sequence: message.sequence,
    createdAt: message.createdAt,
    statusLabel: message.sender === "user"
      ? messageStatusLabel(
        message.status,
        turnsByMessage.get(`${message.id}:${message.sequence}`),
      )
      : null,
    retryable: Boolean(message.retryable),
    queued: queuedIds.has(message.id),
  }));
  const activityGroups = (accessBlocked ? [] : input.activityPresentation.orderedKeys)
    .map((key) => input.activityPresentation.groupsByKey[key])
    .filter((group): group is ActivityPresentationGroup => Boolean(group))
    .map((group) => ({
      key: group.key,
      messageId: group.messageId,
      conversationTurnOrdinal: group.conversationTurnOrdinal,
      entries: group.entries,
    }));
  const pendingAssistantText = accessBlocked
    ? []
    : (input.projection.pendingActivities ?? [])
      .filter((activity) => activity.kind === "assistant_delta" && activity.text.trim())
      .map((activity) => activity.text);
  const turns = accessBlocked
    ? []
    : mergeTurnModels(input.messages, input.projection.turns, assistantReplies);

  return {
    ally: {
      name: input.ally.name,
      job: input.ally.job,
      shape: input.resolvedAppearance.shape,
      accent: input.resolvedAppearance.color,
      supportedAppearance: input.appearanceAvailable,
    },
    messages,
    turns,
    activityGroups,
    activityState: accessBlocked ? "completed" : input.projection.state,
    pendingAssistantText,
    timeline: {
      isLoading: input.isLoading,
      loadError: input.loadError,
      accessFailure: input.accessFailure,
      accessCopy,
      olderMessagesAvailable: input.olderMessagesAvailable,
      loadingOlder: input.loadingOlder,
      olderLoadError: input.olderLoadError,
      workspaceRefreshError: input.workspaceRefreshError,
      activityError: input.activityError,
      activityHistoryError: input.activityHistoryError,
      activityReplayUnavailable: input.activityReplayUnavailable,
      pollBudgetReached: input.pollBudgetReached,
      retryError: input.retryError,
    },
    composer: {
      draft: accessBlocked ? "" : input.draft,
      placeholder: input.showThinkingState ? `Ask ${input.ally.name}` : `Reply ${input.ally.name}`,
      disabled: accessBlocked
        || !conversationCanChat(input.ally)
        || !input.conversationAvailable
        || !input.queuedMessagesReady
        || Boolean(input.loadError),
      sending: input.sending,
      sendError: input.sendError,
      unavailableNotice: input.unavailableNotice,
    },
    queuedMessages: accessBlocked ? [] : [...messages.filter((message) => message.queued && !input.queuedMessages.some((item) => item.id === message.id))
      .map(({ id, content }) => ({ id, content, removable: false })), ...input.queuedMessages.map((item) => ({
      id: item.id,
      content: item.content,
      removable: item.removable,
      statusLabel: item.statusLabel,
    }))],
    showThinkingState: accessBlocked ? false : input.showThinkingState,
    responseStarted: accessBlocked ? false : input.responseStarted,
    gettingReady: accessBlocked ? false : input.gettingReady,
    streaming: accessBlocked ? false : input.streaming,
    firstAssistantMessageId,
    retriedMessageIds: [...input.retriedMessageIds],
    retryingMessageId: input.retryingMessageId,
  };
}

function toTurnModel(turn: AssistantTurnProjection): ProductionConversationTurnModel {
  return {
    assistantText: turn.assistantText,
    messageId: turn.messageId,
    state: turn.state,
    turnOrdinal: turn.turnOrdinal,
  };
}

function mergeTurnModels(
  messages: readonly MessageViewModel[],
  projectedTurns: readonly AssistantTurnProjection[],
  assistantReplies: readonly AssistantReplyViewModel[],
): ProductionConversationTurnModel[] {
  const repliesByMessageId = new Map(
    assistantReplies
      .filter((reply) => reply.hasFullPrefix)
      .map((reply) => [reply.sourceMessageId, reply]),
  );
  const turns = projectedTurns.map((turn) => {
    const reply = repliesByMessageId.get(turn.messageId);
    const hasLegacyReply = hasLegacyAssistantReply(messages, turn);
    return {
      ...toTurnModel(turn),
      assistantText: hasLegacyReply
        ? ""
        : reply?.content ?? (turn.state === "failed" || turn.state === "stopped" ? "" : turn.assistantText),
      createdAt: reply?.createdAt,
      state: reply ? messageStatusToActivityState(reply.status) : turn.state,
      isTruncated: !hasLegacyReply && reply?.isTruncated === true,
    };
  });
  const projectedMessageIds = new Set(projectedTurns.map((turn) => turn.messageId));
  for (const reply of repliesByMessageId.values()) {
    if (projectedMessageIds.has(reply.sourceMessageId)) continue;
    const sourceMessage = messages.find(
      (message) => message.id === reply.sourceMessageId && message.sender === "user",
    );
    if (!sourceMessage || hasLegacyAssistantReply(messages, {
      messageId: reply.sourceMessageId,
      turnOrdinal: reply.conversationTurnOrdinal,
    })) continue;
    turns.push({
      assistantText: reply.content,
      createdAt: reply.createdAt,
      isTruncated: reply.isTruncated === true,
      messageId: reply.sourceMessageId,
      state: messageStatusToActivityState(reply.status),
      turnOrdinal: reply.conversationTurnOrdinal,
    });
  }
  return turns.sort(
    (left, right) => left.turnOrdinal - right.turnOrdinal || left.messageId.localeCompare(right.messageId),
  );
}

function hasLegacyAssistantReply(
  messages: readonly MessageViewModel[],
  turn: Pick<AssistantTurnProjection, "messageId" | "turnOrdinal">,
): boolean {
  const userMessage = messages.find((message) => message.id === turn.messageId && message.sender === "user");
  if (!userMessage) return false;
  const nextUserSequence = messages
    .filter((message) => message.sender === "user" && message.sequence > userMessage.sequence)
    .reduce<number | null>((nearest, message) => (
      nearest === null || message.sequence < nearest ? message.sequence : nearest
    ), null);

  return messages.some((message) => (
    message.sender === "assistant"
    && message.sequence > userMessage.sequence
    && (nextUserSequence === null || message.sequence < nextUserSequence)
  ));
}

function messageStatusToActivityState(status: MessageViewModel["status"]): ActivityState {
  return status === "in_progress" ? "running" : status;
}

function conversationCanChat(ally: AllyViewModel): boolean {
  return ally.provisioningState === "bound";
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
