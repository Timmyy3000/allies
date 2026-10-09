import type { AllyViewModel, AssistantReplyViewModel, MessageViewModel, RoutineChatItemViewModel } from "@allies/cloud-client";
import { EMPTY_ACTIVITY_PROJECTION } from "@allies/cloud-client";
import { describe, expect, it } from "vitest";

import {
  EMPTY_ACTIVITY_PRESENTATION,
  mergeActivityPresentation,
} from "../../lib/allies/activity-presentation";
import {
  buildRoutineActionIdempotencyKey,
  buildRoutineActionEvidence,
  buildRoutineActionMessage,
  buildRoutineActionContext,
  completedParagraphs,
  routineMessageAnchor,
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
  it.each(["queued", "in_progress"] as const)("does not label an accepted %s chat bubble as queued", (status) => {
    const result = buildProductionConversationFrameModel(makeInput({
      messages: [{ ...userMessage, status }],
      projection: EMPTY_ACTIVITY_PROJECTION,
      activeMessageId: userMessage.id,
      activeMessageHasProgress: false,
    }));
    expect(result.messages[0]?.statusLabel).toBeNull();
  });
  it("restores the accepted sleeping message ahead of local drafts until its own turn starts", () => {
    const input = makeInput({
      messages: [{ ...userMessage, status: "queued" }],
      projection: { ...EMPTY_ACTIVITY_PROJECTION, state: "queued" },
      queuedMessages: [{ id: "local-next", content: "And a drink" }],
    });
    const queued = buildProductionConversationFrameModel(input);
    expect(queued.messages[0]?.queued).toBe(true);
    expect(queued.queuedMessages).toEqual([
      { id: userMessage.id, content: userMessage.content, removable: false },
      { id: "local-next", content: "And a drink" },
    ]);
    const running = buildProductionConversationFrameModel({ ...input, projection: {
      ...input.projection, state: "running", turns: [{
        messageId: userMessage.id, turnOrdinal: 1, state: "running", assistantText: "",
      }],
    } });
    expect(running.messages[0]?.queued).toBe(false);
    expect(running.queuedMessages).toEqual([{ id: "local-next", content: "And a drink" }]);
  });

  it("preserves queued attachment previews through the frame model", () => {
    const model = buildProductionConversationFrameModel(makeInput({
      projection: EMPTY_ACTIVITY_PROJECTION,
      queuedMessages: [{
        id: "local-files",
        content: "Review these",
        attachments: [
          { id: "file-1", name: "a.pdf", ready: true },
          { id: "file-2", name: "b.png", src: "blob:preview", ready: true },
        ],
      }],
    }));
    expect(model.queuedMessages).toEqual([{
      id: "local-files",
      content: "Review these",
      attachments: [
        { id: "file-1", name: "a.pdf", ready: true },
        { id: "file-2", name: "b.png", src: "blob:preview", ready: true },
      ],
    }]);
  });

  it("treats a matching claimed message as active work instead of queued copy", () => {
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [{ ...userMessage, status: "queued", queueState: "claimed" }],
      projection: EMPTY_ACTIVITY_PROJECTION,
      activeMessageId: userMessage.id,
    }));

    expect(model.messages[0]?.queued).toBe(false);
    expect(model.messages[0]?.queueState).toBe("claimed");
    expect(model.queuedMessages).toEqual([]);
  });

  it("does not release a queued message for another message's activity", () => {
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [{ ...userMessage, status: "queued" }],
      projection: { ...EMPTY_ACTIVITY_PROJECTION, state: "running", turns: [{
        messageId: "unrelated", turnOrdinal: 1, state: "running", assistantText: "",
      }] },
    }));
    expect(model.messages[0]?.queued).toBe(true);
  });

  it.each(["in_progress", "completed", "failed", "stopped"] as const)(
    "releases durable %s messages without waiting for a live event", (status) => {
      const model = buildProductionConversationFrameModel(makeInput({
        messages: [{ ...userMessage, status }], projection: EMPTY_ACTIVITY_PROJECTION,
      }));
      expect(model.messages[0]?.queued).toBe(false);
      expect(model.queuedMessages).toEqual([]);
    },
  );

  it("shows pending text only for the active message", () => {
    const pending = (messageId: string, text: string) => ({
      id: `activity-${text}`,
      messageId,
      sequence: 1,
      conversationTurnOrdinal: 1,
      kind: "assistant_delta" as const,
      text,
      state: "running" as const,
      createdAt: "2026-10-08T14:34:00Z",
    });
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [{ ...userMessage, status: "stopped" }],
      activeMessageId: userMessage.id,
      projection: {
        ...EMPTY_ACTIVITY_PROJECTION,
        state: "stopped",
        pendingActivities: [pending("earlier-turn", "Earlier text"), pending(userMessage.id, "Current text")],
      },
    }));
    expect(model.pendingAssistantText).toEqual(["Current text"]);
  });

  it("keeps a stopped turn's partial text out of the newest reply", () => {
    const stopped: MessageViewModel = { ...userMessage, status: "stopped" };
    const newer: MessageViewModel = { ...userMessage, id: "message-3", content: "Next question", sequence: 3 };
    const stoppedPartial = {
      id: "activity-stopped",
      messageId: userMessage.id,
      sequence: 2,
      conversationTurnOrdinal: userMessage.sequence,
      kind: "assistant_delta" as const,
      text: "Partial reply",
      state: "stopped" as const,
      createdAt: "2026-09-03T09:40:02Z",
    };
    const projection = { ...EMPTY_ACTIVITY_PROJECTION, state: "stopped" as const, pendingActivities: [stoppedPartial] };

    expect(buildProductionConversationFrameModel(makeInput({
      messages: [stopped],
      projection,
    })).pendingAssistantText).toEqual(["Partial reply"]);
    expect(buildProductionConversationFrameModel(makeInput({
      messages: [stopped, newer],
      projection,
    })).pendingAssistantText).toEqual([]);
  });

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
    expect(model.turns[0]).toMatchObject({ assistantText: reply.content, createdAt: reply.createdAt, state: "completed", isTruncated: true });
  });

  it("keeps the longest compatible active prefix and uses exact terminal text", () => {
    const reply: AssistantReplyViewModel = {
      id: "reply-1",
      sourceMessageId: userMessage.id,
      conversationTurnOrdinal: userMessage.sequence,
      content: "The durable",
      status: "in_progress",
      hasFullPrefix: true,
      createdAt: "2026-09-03T09:40:01Z",
      updatedAt: "2026-09-03T09:40:02Z",
    };
    const input = makeInput({
      messages: [userMessage],
      assistantReplies: [reply],
      projection: {
        ...EMPTY_ACTIVITY_PROJECTION,
        state: "running",
        turns: [{
          messageId: userMessage.id,
          turnOrdinal: userMessage.sequence,
          assistantText: "The durable answer is newer",
          state: "running",
        }],
      },
    });

    expect(buildProductionConversationFrameModel(input).turns[0]?.assistantText)
      .toBe("The durable answer is newer");
    expect(buildProductionConversationFrameModel({
      ...input,
      assistantReplies: [{ ...reply, content: "Corrected final", status: "completed" }],
    }).turns[0]?.assistantText).toBe("Corrected final");
  });

  it("lets a matching durable success clear a stale failed message and turn", () => {
    const reply: AssistantReplyViewModel = {
      id: "reply-success",
      sourceMessageId: userMessage.id,
      conversationTurnOrdinal: userMessage.sequence,
      content: "Recovered after reconnect.",
      status: "completed",
      hasFullPrefix: true,
      createdAt: "2026-09-03T09:40:01Z",
      updatedAt: "2026-09-03T09:40:02Z",
    };
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [{ ...userMessage, status: "failed" }],
      assistantReplies: [reply],
      projection: {
        ...EMPTY_ACTIVITY_PROJECTION,
        state: "failed",
        turns: [{ messageId: userMessage.id, turnOrdinal: userMessage.sequence, state: "failed", assistantText: "stale" }],
      },
    }));

    expect(model.messages[0]?.statusLabel).toBeNull();
    expect(model.turns[0]).toMatchObject({ state: "completed", assistantText: reply.content });
  });

  it("does not show a stale failure when a completed legacy reply is present", () => {
    const model = buildProductionConversationFrameModel(makeInput({
      messages: [
        { ...userMessage, status: "failed" },
        { ...assistantMessage, sequence: 2 },
      ],
      projection: {
        ...EMPTY_ACTIVITY_PROJECTION,
        state: "failed",
        turns: [{ messageId: userMessage.id, turnOrdinal: userMessage.sequence, state: "failed", assistantText: "stale" }],
      },
    }));

    expect(model.messages[0]?.statusLabel).toBeNull();
    expect(model.turns[0]?.state).toBe("completed");
    expect(model.turns[0]?.assistantText).toBe("");
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

describe("routine action requests", () => {
  const request = {
    action: "approve" as const,
    routineId: "00000000-0000-4000-8000-000000000010",
    routineRevision: 2,
    titleSnapshot: "Morning brief; review",
    runId: "00000000-0000-4000-8000-000000000012",
    approvalId: "00000000-0000-4000-8000-000000000017",
    approvalRequestId: "00000000-0000-4000-8000-000000000016",
    executionId: "00000000-0000-4000-8000-000000000013",
    attemptId: "00000000-0000-4000-8000-000000000014",
    generation: 7,
    actionAttemptId: "00000000-0000-4000-8000-000000000018",
  };

  it("keeps action keys stable and within the Cloud idempotency bound", () => {
    const key = buildRoutineActionIdempotencyKey(request);
    expect(key).toBe(buildRoutineActionIdempotencyKey({ ...request }));
    expect(key.length).toBeGreaterThanOrEqual(16);
    expect(key.length).toBeLessThanOrEqual(128);
    expect(buildRoutineActionIdempotencyKey({ ...request, action: "reject" })).not.toBe(key);
  });

  it("keeps command identities in structured context rather than visible chat", () => {
    const content = buildRoutineActionMessage(request);
    expect(content).toContain(request.titleSnapshot);
    expect(content).toContain(`](#routine/${request.routineId})`);
    expect(content).not.toContain("expected_revision");
    expect(buildRoutineActionContext(request)).toMatchObject({
      routine_id: request.routineId, expected_revision: 2,
      approval_request_id: request.approvalRequestId, action_attempt_id: request.actionAttemptId,
      confirmed: false,
    });
    expect(buildRoutineActionContext({ ...request, action: "delete", confirmed: true }).confirmed).toBe(true);
  });

  it("tracks only the submitted routine projection", () => {
    const target: RoutineChatItemViewModel = {
      id: request.routineId,
      kind: "created",
      routineId: request.routineId,
      conversationId: "00000000-0000-4000-8000-000000000003",
      titleSnapshot: request.titleSnapshot,
      routineRevision: request.routineRevision,
      scheduleGeneration: 1,
      status: "active",
      schedule: { kind: "once", localAt: "2026-09-10T09:30:00", timezone: "UTC" },
      occurredAt: "2026-09-09T08:00:00Z",
      occurrenceId: null,
      runId: null,
      executionId: null,
      attemptId: null,
      generation: null,
      resultId: null,
      resultInsertion: null,
      text: null,
      references: [],
      delayed: null,
      approvalId: null,
      approvalRequestId: null,
      approvalStatus: null,
      approvalDecision: null,
      actionDigest: null,
      actionAttemptId: null,
      approvalExpiresAt: null,
    };
    const unrelated = {
      ...target,
      id: "00000000-0000-4000-8000-000000000099",
      routineId: "00000000-0000-4000-8000-000000000099",
    };
    const messages = ["07:00", "09:00", "10:00"].map((time, index) => ({
      id: `message-${index}`, sender: "user" as const, content: "Next message", sequence: index + 1,
      createdAt: `2026-09-09T${time}:00Z`, statusLabel: null, retryable: false,
    }));
    expect(routineMessageAnchor(target, messages)).toBe("message-0");
    const anchored = { ...target, sourceMessageId: "message-1" };
    expect(routineMessageAnchor(anchored, messages)).toBe("message-1");
    expect(routineMessageAnchor(anchored, messages.slice(2))).toBe("message-1");
    expect(routineMessageAnchor({ ...anchored, kind: "result", occurredAt: "2026-09-09T09:30:00Z" }, messages)).toBe("message-1");
    const action = { ...request, action: "pause" as const };
    expect(buildRoutineActionEvidence(action, [target, unrelated])).toBe(
      buildRoutineActionEvidence(action, [target, { ...unrelated, status: "paused" }]),
    );
    expect(buildRoutineActionEvidence(action, [{ ...target, routineRevision: 3 }, unrelated])).not.toBe(
      buildRoutineActionEvidence(action, [target, unrelated]),
    );

    const running: RoutineChatItemViewModel = {
      ...target,
      id: request.runId!,
      kind: "running",
      status: "approval_waiting",
      occurrenceId: "00000000-0000-4000-8000-000000000011",
      runId: request.runId,
      approvalRequestId: request.approvalRequestId,
      approvalStatus: "pending",
    };
    const approvalAction = { ...request, action: "approve" as const };
    expect(buildRoutineActionEvidence(approvalAction, [running])).not.toBe(
      buildRoutineActionEvidence(approvalAction, [{ ...running, approvalRequestId: "00000000-0000-4000-8000-000000000019" }]),
    );
  });
});

describe("formatConversationDateDivider", () => {
  it("uses Today without repeating the message time", () => {
    const now = new Date(2026, 8, 4, 12, 0);
    const messageDate = new Date(2026, 8, 4, 9, 40);

    expect(formatConversationDateDivider(messageDate.toISOString(), now)).toBe("Today");
  });

  it("uses Yesterday across a month and year boundary", () => {
    const now = new Date(2027, 0, 1, 12, 0);
    const messageDate = new Date(2026, 11, 31, 23, 59);

    expect(formatConversationDateDivider(messageDate.toISOString(), now)).toBe("Yesterday");
  });

  it("uses the message date when it is older than yesterday", () => {
    const now = new Date(2026, 8, 4, 12, 0);
    const messageDate = new Date(2026, 7, 20, 16, 0);
    const result = formatConversationDateDivider(messageDate.toISOString(), now);
    const expectedDate = messageDate.toLocaleDateString([], { month: "short", day: "numeric" });

    expect(result).toBe(expectedDate);
    expect(result).not.toContain("Today");
  });

  it("includes the year for an older message from a different year and rejects invalid input", () => {
    const now = new Date(2026, 8, 4, 12, 0);
    const messageDate = new Date(2025, 8, 4, 16, 0);
    const expectedDate = messageDate.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });

    expect(formatConversationDateDivider(messageDate.toISOString(), now)).toBe(expectedDate);
    expect(formatConversationDateDivider("not-a-date", now)).toBe("");
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

describe("completedParagraphs", () => {
  it("returns empty text when no paragraph boundary arrived yet", () => {
    expect(completedParagraphs("")).toBe("");
    expect(completedParagraphs("A single growing paragraph")).toBe("");
    expect(completedParagraphs("- item one\n- item two")).toBe("");
  });

  it("reveals only complete paragraphs and keeps the partial tail back", () => {
    expect(completedParagraphs("First paragraph.\n\nSecond partial")).toBe("First paragraph.");
    expect(completedParagraphs("First.\n\nSecond.\n\nThird partial")).toBe("First.\n\nSecond.");
    expect(completedParagraphs("Only paragraph.\n\n")).toBe("Only paragraph.");
    expect(completedParagraphs("First.\r\n\r\nSecond partial")).toBe("First.");
  });
});
