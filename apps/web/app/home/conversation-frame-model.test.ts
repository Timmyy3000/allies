import type { AllyViewModel, AssistantReplyViewModel, MessageViewModel } from "@allies/cloud-client";
import { EMPTY_ACTIVITY_PROJECTION } from "@allies/cloud-client";
import { describe, expect, it } from "vitest";

import {
  EMPTY_ACTIVITY_PRESENTATION,
  mergeActivityPresentation,
} from "../../lib/allies/activity-presentation";
import {
  buildProductionConversationFrameModel,
  conversationDateDividerAt,
  formatConversationDateDivider,
  type ProductionConversationFrameInput,
} from "./conversation-frame-model";

const ally: AllyViewModel = {
  id: "ally-1",
  bindingId: "binding-1",
  operationId: "operation-1",
  name: "Sally",
  job: "Your personal assistant",
  personality: "Helpful",
  appearance: { catalogVersion: "v1", key: "ghosty:fd304f" },
  provisioningState: "bound",
  retryable: false,
};

const userMessage: MessageViewModel = {
  id: "message-1",
  sender: "user",
  content: "i want a sandwich",
  sequence: 1,
  status: "completed",
  createdAt: "2026-09-03T09:40:00Z",
};

const assistantMessage: MessageViewModel = {
  id: "message-2",
  sender: "assistant",
  content: "Okay. What kind of sandwich do you want?",
  sequence: 2,
  status: "completed",
  createdAt: "2026-09-03T09:40:02Z",
};

function makeInput(overrides: Partial<ProductionConversationFrameInput> = {}): ProductionConversationFrameInput {
  return {
    ally,
    resolvedAppearance: { shape: "ghosty", color: "#FD304F" },
    appearanceAvailable: true,
    messages: [userMessage, assistantMessage],
    projection: {
      ...EMPTY_ACTIVITY_PROJECTION,
      state: "completed",
      turns: [{
        messageId: userMessage.id,
        turnOrdinal: userMessage.sequence,
        assistantText: assistantMessage.content,
        state: "completed",
      }],
    },
    activityPresentation: EMPTY_ACTIVITY_PRESENTATION,
    queuedMessages: [],
    queuedMessagesReady: true,
    draft: "",
    conversationAvailable: true,
    isLoading: false,
    loadError: null,
    accessFailure: null,
    setupNotice: null,
    olderMessagesAvailable: false,
    loadingOlder: false,
    olderLoadError: null,
    workspaceRefreshError: false,
    activityError: null,
    activityHistoryError: null,
    activityReplayUnavailable: false,
    pollBudgetReached: false,
    retryError: null,
    sendError: null,
    unavailableNotice: null,
    sending: false,
    retryingMessageId: null,
    showThinkingState: false,
    responseStarted: false,
    gettingReady: false,
    streaming: false,
    retriedMessageIds: new Set(),
    ...overrides,
  };
}

describe("buildProductionConversationFrameModel", () => {
  it("places grouped activity on the exact triggering user turn", () => {
    const activityPresentation = mergeActivityPresentation(EMPTY_ACTIVITY_PRESENTATION, {
      conversationId: "conversation-1",
      activities: [{
        id: "activity-1",
        messageId: userMessage.id,
        sequence: 3,
        conversationTurnOrdinal: userMessage.sequence,
        kind: "activity_started",
        text: "  Searching for citysubs  ",
        state: "running",
        createdAt: "2026-09-03T09:40:03Z",
      }],
    });
    const model = buildProductionConversationFrameModel(makeInput({ activityPresentation }));

    expect(model.messages.map((message) => message.id)).toEqual(["message-1", "message-2"]);
    expect(model.activityGroups).toMatchObject([{
      messageId: userMessage.id,
      conversationTurnOrdinal: 1,
      entries: [{ text: "Searching for citysubs" }],
    }]);
    expect(model.turns[0]?.assistantText).toBe("");
    expect(model.composer.placeholder).toBe("Reply Sally");
  });

  it("keeps projected assistant text while the durable reply is not loaded", () => {
    const model = buildProductionConversationFrameModel(makeInput({ messages: [userMessage] }));

    expect(model.turns[0]?.assistantText).toBe(assistantMessage.content);
  });

  it("uses a full-prefix durable reply as the single turn content", () => {
    const reply: AssistantReplyViewModel = {
      id: "reply-1",
      sourceMessageId: userMessage.id,
      conversationTurnOrdinal: userMessage.sequence,
      content: "The complete durable reply.",
      status: "completed",
      hasFullPrefix: true,
      isTruncated: true,
      createdAt: "2026-09-03T09:40:01Z",
      updatedAt: "2026-09-03T09:40:02Z",
    };
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [userMessage],
      assistantReplies: [reply],
      projection: {
        ...EMPTY_ACTIVITY_PROJECTION,
        state: "running",
        turns: [{
          messageId: userMessage.id,
          turnOrdinal: userMessage.sequence,
          assistantText: "The activity projection is incomplete.",
          state: "running",
        }],
      },
    }));

    expect(model.turns).toHaveLength(1);
    expect(model.turns[0]).toMatchObject({ assistantText: reply.content, state: "completed", isTruncated: true });
  });

  it("keeps the activity fallback for a rollout suffix", () => {
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [userMessage],
      assistantReplies: [{
        id: "reply-suffix",
        sourceMessageId: userMessage.id,
        conversationTurnOrdinal: userMessage.sequence,
        content: "Suffix only",
        status: "completed",
        hasFullPrefix: false,
        createdAt: "2026-09-03T09:40:01Z",
        updatedAt: "2026-09-03T09:40:02Z",
      }],
    }));

    expect(model.turns[0]?.assistantText).toBe(assistantMessage.content);
  });

  it("does not use a later turn's durable reply to suppress projected text", () => {
    const laterUserMessage: MessageViewModel = {
      ...userMessage,
      id: "message-3",
      content: "A later request",
      sequence: 3,
    };
    const laterAssistantMessage: MessageViewModel = {
      ...assistantMessage,
      id: "message-4",
      content: "A later durable reply",
      sequence: 4,
    };
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [userMessage, laterUserMessage, laterAssistantMessage],
      projection: {
        ...EMPTY_ACTIVITY_PROJECTION,
        state: "completed",
        turns: [{
          messageId: userMessage.id,
          turnOrdinal: userMessage.sequence,
          assistantText: "Projected first reply",
          state: "completed",
        }],
      },
    }));

    expect(model.turns[0]?.assistantText).toBe("Projected first reply");
  });

  it("uses the Ask placeholder while the conversation is waiting for a response", () => {
    const model = buildProductionConversationFrameModel(makeInput({ showThinkingState: true }));
    expect(model.composer.placeholder).toBe("Ask Sally");
  });

  it("fails closed for an inaccessible scope without leaking timeline or queue data", () => {
    const model = buildProductionConversationFrameModel(makeInput({
      accessFailure: "forbidden",
      draft: "Keep this unsent in memory",
      queuedMessages: [{ id: "queued-1", content: "Do not dispatch" }],
      projection: {
        ...EMPTY_ACTIVITY_PROJECTION,
        state: "running",
        pendingActivities: [{
          id: "activity-pending",
          messageId: userMessage.id,
          sequence: 2,
          conversationTurnOrdinal: userMessage.sequence,
          kind: "assistant_delta",
          text: "Do not expose this projection",
          state: "running",
          createdAt: "2026-09-03T09:40:02Z",
        }],
      },
      showThinkingState: true,
      responseStarted: true,
      gettingReady: true,
      streaming: true,
    }));

    expect(model.timeline.accessCopy).toEqual({
      title: "This conversation isn't available",
      detail: "You don't have permission to open it here.",
    });
    expect(model.messages).toEqual([]);
    expect(model.activityGroups).toEqual([]);
    expect(model.queuedMessages).toEqual([]);
    expect(model.turns).toEqual([]);
    expect(model.pendingAssistantText).toEqual([]);
    expect(model.activityState).toBe("completed");
    expect(model.showThinkingState).toBe(false);
    expect(model.responseStarted).toBe(false);
    expect(model.gettingReady).toBe(false);
    expect(model.streaming).toBe(false);
    expect(model.composer.draft).toBe("");
    expect(model.composer.disabled).toBe(true);
  });
});

describe("formatConversationDateDivider", () => {
  it("uses the message timestamp for a message from today", () => {
    const now = new Date(2026, 8, 4, 12, 0);
    const messageDate = new Date(2026, 8, 4, 9, 40);
    const expectedTime = messageDate.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

    expect(formatConversationDateDivider(messageDate.toISOString(), now)).toBe(`Today ${expectedTime}`);
  });

  it("uses the message date when it is not today", () => {
    const now = new Date(2026, 8, 4, 12, 0);
    const messageDate = new Date(2026, 7, 20, 16, 0);
    const result = formatConversationDateDivider(messageDate.toISOString(), now);
    const expectedDate = messageDate.toLocaleDateString([], { month: "short", day: "numeric" });
    const expectedTime = messageDate.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

    expect(result).toBe(`${expectedDate} ${expectedTime}`);
    expect(result).not.toContain("Today");
  });
});

describe("conversationDateDividerAt", () => {
  it("labels the first message and later messages on a new calendar day", () => {
    const now = new Date(2026, 8, 5, 12, 0);
    const morning = new Date(2026, 8, 4, 9, 40).toISOString();
    const laterSameDay = new Date(2026, 8, 4, 18, 10).toISOString();
    const nextDay = new Date(2026, 8, 5, 8, 15).toISOString();

    expect(conversationDateDividerAt(morning, undefined, now)).toBe(
      formatConversationDateDivider(morning, now),
    );
    expect(conversationDateDividerAt(laterSameDay, morning, now)).toBe("");
    expect(conversationDateDividerAt(nextDay, laterSameDay, now)).toBe(
      formatConversationDateDivider(nextDay, now),
    );
  });
});
