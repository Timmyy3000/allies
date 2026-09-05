// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ActivityProjection, MessageViewModel } from "@allies/cloud-client";
import { EMPTY_ACTIVITY_PROJECTION } from "@allies/cloud-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_ACTIVITY_PRESENTATION,
  mergeActivityPresentation,
} from "../../lib/allies/activity-presentation";
import { ConversationFrame } from "./conversation-frame";
import type {
  ProductionConversationFrameActions,
  ProductionConversationFrameModel,
} from "./conversation-frame-model";
import { formatConversationDateDivider } from "./conversation-frame-model";

const messages: MessageViewModel[] = [
  {
    id: "message-1",
    sender: "user",
    content: "First request",
    sequence: 1,
    status: "completed",
    createdAt: "2026-09-03T09:40:00Z",
  },
  {
    id: "message-2",
    sender: "user",
    content: "Second request",
    sequence: 4,
    status: "completed",
    createdAt: "2026-09-03T09:41:00Z",
  },
  {
    id: "message-3",
    sender: "assistant",
    content: "A normal production reply.",
    sequence: 5,
    status: "completed",
    createdAt: "2026-09-03T09:41:01Z",
  },
];

const projection: ActivityProjection = {
  ...EMPTY_ACTIVITY_PROJECTION,
  state: "completed",
};

const model: ProductionConversationFrameModel = {
  ally: {
    name: "Sally",
    job: "Your personal assistant",
    shape: "ghosty",
    accent: "#FD304F",
    supportedAppearance: true,
  },
  messages: messages.map((message) => ({
    id: message.id,
    sender: message.sender,
    content: message.content,
    sequence: message.sequence,
    createdAt: message.createdAt,
    statusLabel: null,
    retryable: false,
  })),
  turns: [],
  activityGroups: [{
    key: "message-1:1",
    messageId: "message-1",
    conversationTurnOrdinal: 1,
    entries: [{
      id: "activity-1",
      sequence: 2,
      messageId: "message-1",
      conversationTurnOrdinal: 1,
      kind: "activity_started",
      text: "Searching for citysubs",
      state: "running",
      createdAt: "2026-09-03T09:40:02Z",
    }],
  }],
  activityState: projection.state,
  pendingAssistantText: [],
  timeline: {
    isLoading: false,
    loadError: null,
    accessFailure: null,
    accessCopy: null,
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
  },
  composer: {
    draft: "",
    placeholder: "Reply Sally",
    disabled: false,
    sending: false,
    sendError: null,
    unavailableNotice: null,
  },
  queuedMessages: [],
  showThinkingState: false,
  responseStarted: false,
  gettingReady: false,
  streaming: false,
  firstAssistantMessageId: "message-3",
  retriedMessageIds: [],
  retryingMessageId: null,
};

const actions: ProductionConversationFrameActions = {
  onDraftChange: vi.fn(),
  onSubmit: vi.fn(),
  onRetryMessage: vi.fn(),
  onLoadOlder: vi.fn(),
  onRetryConversation: vi.fn(),
  onRetryWorkspace: vi.fn(),
  onRemoveQueuedMessage: vi.fn(),
  onCheckAgain: vi.fn(),
  onRetryActivityHistory: vi.fn(),
  onScroll: vi.fn(),
};

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: false,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ConversationFrame", () => {
  it("shows the awaiting-action explanation when the projected turn has no text", () => {
    render(
      <ConversationFrame
        model={{
          ...model,
          activityState: "awaiting_action",
          turns: [{
            assistantText: "",
            messageId: "message-2",
            state: "awaiting_action",
            turnOrdinal: 4,
          }],
        }}
        actions={actions}
      />,
    );

    expect(screen.getByText("This Ally needs an action Home cannot complete yet.")).toBeTruthy();
  });

  it("renders production activity after its exact triggering user turn", () => {
    const { container } = render(<ConversationFrame model={model} actions={actions} />);
    const items = [...container.querySelectorAll("article, details")].map((item) => item.textContent);
    const firstRequest = items.findIndex((text) => text?.includes("First request"));
    const activity = items.findIndex((text) => text?.includes("Searching for citysubs"));
    const secondRequest = items.findIndex((text) => text?.includes("Second request"));

    expect(firstRequest).toBeGreaterThanOrEqual(0);
    expect(activity).toBeGreaterThan(firstRequest);
    expect(secondRequest).toBeGreaterThan(activity);
    expect(screen.getByText(formatConversationDateDivider(messages[0].createdAt), { exact: false })).toBeTruthy();
  });

  it("does not attach a projected turn when its message identity is stale", () => {
    render(
      <ConversationFrame
        model={{
          ...model,
          turns: [{
            assistantText: "Stale projected response",
            messageId: "message-not-loaded",
            state: "completed",
            turnOrdinal: 1,
          }],
        }}
        actions={actions}
      />,
    );

    expect(screen.queryByText("Stale projected response")).toBeNull();
  });

  it("keeps production rendering free of fixture-only rich actions", () => {
    render(<ConversationFrame model={model} actions={actions} />);

    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Report" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.getByPlaceholderText("Reply Sally")).toBeTruthy();
  });

  it("renders the access message instead of stale conversation projection", () => {
    render(
      <ConversationFrame
        model={{
          ...model,
          timeline: {
            ...model.timeline,
            accessFailure: "forbidden",
            accessCopy: {
              title: "This conversation isn't available",
              detail: "You don't have permission to open it here.",
            },
          },
          pendingAssistantText: ["Private projected text"],
          showThinkingState: true,
          responseStarted: true,
          gettingReady: true,
          streaming: true,
        }}
        actions={actions}
      />,
    );

    expect(screen.getByRole("alert").textContent).toContain("This conversation isn't available");
    expect(screen.getByRole("alert").textContent).toContain("You don't have permission to open it here.");
    expect(screen.queryByText("First request")).toBeNull();
    expect(screen.queryByText("A normal production reply.")).toBeNull();
    expect(screen.queryByText("Private projected text")).toBeNull();
    expect(screen.queryByText("No messages yet")).toBeNull();
    expect(screen.queryByText("Thinking", { exact: true })).toBeNull();
  });

  it("keeps only the ally icon below a response while it is streaming", () => {
    render(
      <ConversationFrame
        model={{
          ...model,
          messages: model.messages.slice(0, 2),
          turns: [{
            assistantText: "A response is being generated.",
            messageId: "message-2",
            state: "running",
            turnOrdinal: 4,
          }],
          activityState: "running",
          showThinkingState: true,
          responseStarted: true,
          streaming: true,
          firstAssistantMessageId: null,
        }}
        actions={actions}
      />,
    );

    expect(screen.queryByText("Thinking", { exact: true })).toBeNull();
    const status = screen.getByRole("status", { name: "Responding" });
    const response = screen.getByTestId("activity-reply-4");
    expect(status.querySelector("[data-ally-avatar][data-ally-state='thinking']")).toBeTruthy();
    expect(response.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each(["completed", "failed", "stopped"] as const)("retains a truncated %s reply with an explicit notice", (state) => {
    render(<ConversationFrame model={{
      ...model,
      messages: model.messages.slice(0, 2),
      turns: [{
        assistantText: "Retained reply prefix.",
        isTruncated: true,
        messageId: "message-2",
        state,
        turnOrdinal: 4,
      }],
    }} actions={actions} />);
    const reply = screen.getByTestId("activity-reply-4");
    expect(reply.textContent).toContain("Retained reply prefix.");
    expect(reply.textContent).toContain("This response reached its length limit.");
    expect(reply.textContent).not.toContain("Try sending your message again");
  });

  it("does not expose raw activity kinds or missing groups", () => {
    const presentation = mergeActivityPresentation(EMPTY_ACTIVITY_PRESENTATION, {
      conversationId: "conversation-1",
      activities: [{
        id: "ignored",
        messageId: "not-loaded",
        sequence: 1,
        conversationTurnOrdinal: 99,
        kind: "assistant_delta",
        text: "internal event",
        state: "running",
        createdAt: "2026-09-03T09:40:00Z",
      }],
    });
    expect(presentation.retainedEntryCount).toBe(0);
  });

  it("shows a date stamp at the top and again when the calendar day changes", () => {
    const laterDay = {
      ...model.messages[2],
      id: "message-4",
      createdAt: "2026-09-04T11:15:00Z",
      content: "A message from the next day.",
    };

    render(
      <ConversationFrame
        model={{
          ...model,
          messages: [...model.messages, laterDay],
        }}
        actions={actions}
      />,
    );

    expect(screen.getAllByText(formatConversationDateDivider(messages[0].createdAt)).length).toBeGreaterThan(0);
    expect(screen.getByText(formatConversationDateDivider(laterDay.createdAt))).toBeTruthy();
    expect(screen.getByText("A message from the next day.")).toBeTruthy();
  });

  it("uses the filled send icon once the composer has text", () => {
    render(
      <ConversationFrame
        model={{
          ...model,
          composer: {
            ...model.composer,
            draft: "When the text field increases in height, we reduce the corner radius and keep the button aligned at the button, it doesn’t go anywhere, scroll is allowed",
          },
        }}
        actions={actions}
      />,
    );

    const send = screen.getByRole("button", { name: "Send message" });
    expect(send.querySelector("img")?.getAttribute("src")).toBe("/home/chat/send.svg");
    expect(screen.getByTestId("conversation-composer").getAttribute("data-expanded")).toBe("true");
  });

  it("shows the header blur only after the thread has scrolled", () => {
    render(<ConversationFrame model={model} actions={actions} />);

    expect(screen.queryByTestId("conversation-frame-scroll-blur")).toBeNull();
    fireEvent.scroll(screen.getByTestId("conversation-frame-canvas"), { target: { scrollTop: 24 } });
    expect(screen.getByTestId("conversation-frame-scroll-blur")).toBeTruthy();
    fireEvent.scroll(screen.getByTestId("conversation-frame-canvas"), { target: { scrollTop: 0 } });
    expect(screen.queryByTestId("conversation-frame-scroll-blur")).toBeNull();
  });

  it("shows sleep only when the workspace reports it, regardless of elapsed time", () => {
    vi.useFakeTimers();
    try {
      const view = render(<ConversationFrame model={model} actions={actions} />);
      act(() => vi.advanceTimersByTime(10_000));
      expect(screen.queryByTestId("ally-sleeping-status")).toBeNull();
      view.rerender(<ConversationFrame model={model} actions={actions} sleeping />);
      expect(screen.getByTestId("ally-sleeping-status").textContent).toContain("Sally is asleep");
      view.rerender(<ConversationFrame model={model} actions={actions} sleeping={false} />);
      expect(screen.queryByTestId("ally-sleeping-status")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
