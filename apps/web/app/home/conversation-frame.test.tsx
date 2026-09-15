// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { ActivityProjection, ApprovalSummary, MessageViewModel, RoutineChatItemViewModel, RoutineDiscoveryDetail } from "@allies/cloud-client";
import { EMPTY_ACTIVITY_PROJECTION } from "@allies/cloud-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_ACTIVITY_PRESENTATION,
  mergeActivityPresentation,
} from "../../lib/allies/activity-presentation";
import { ConversationFrame } from "./conversation-frame";
import { ConversationApprovals, type ApprovalClient } from "./conversation-approvals";
import { AssistantMessage, UserBubble } from "./conversation-frame-primitives";
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
    createdAt: "2026-09-03T09:40:37Z",
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
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
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
  it("moves only the started queue head into the transcript and keeps local removal available", async () => {
    const queuedModel = {
      ...model,
      messages: [{ ...model.messages[0], queued: true }],
      activityGroups: [],
      queuedMessages: [
        { id: "message-1", content: "First request", removable: false },
        { id: "local-next", content: "Next request" },
      ],
    };
    const view = render(<ConversationFrame model={queuedModel} actions={actions} sleeping />);
    expect(screen.getByText("First request").closest("ol")?.getAttribute("aria-label")).toBe("Queued messages");
    expect(screen.queryByRole("button", { name: "Remove queued message: First request" })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove queued message: Next request" })).toBeTruthy();
    view.rerender(<ConversationFrame model={{
      ...queuedModel,
      messages: [{ ...model.messages[0], queued: false }],
      queuedMessages: [queuedModel.queuedMessages[1]],
    }} actions={actions} runtimeIntentStatus="ready" />);
    expect(screen.getByText("First request", { selector: "article p" })).toBeTruthy();
    expect(screen.getByText("Next request").closest("ol")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText("First request")).toHaveLength(1));
  });

  it("remeasures the avatar when the centred status label changes width", () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const slot = this.className.includes("framePresenceHeaderSlot");
      const x = slot ? (this.parentElement?.textContent?.includes("waking up") ? 60 : 100) : 0;
      return { x, y: 0, left: x, top: 0, right: x + 24, bottom: 24, width: 24, height: 24, toJSON: () => ({}) };
    });
    const view = render(<ConversationFrame model={model} actions={actions} sleeping />);
    const actor = screen.getByTestId("conversation-ally");
    expect(actor.style.transform).toContain("translate(100px, 0px)");
    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus="waking" />);
    expect(actor.style.transform).toContain("translate(0px, 0px)");
  });

  it("reflows the thread avatar directly into its reserved slot when a greeting appears", () => {
    const animate = vi.fn(() => ({ cancel: vi.fn() }));
    Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: animate });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const isThreadSlot = this.className.includes("framePresenceThreadSlot");
      const messageCount = this.closest("[data-testid='conversation-frame-rail']")?.querySelectorAll('[class*="frameMessageRow"]').length ?? 0;
      const y = isThreadSlot ? 100 + messageCount * 40 : 0;
      return { x: 20, y, left: 20, top: y, right: 56, bottom: y + 36, width: 36, height: 36, toJSON: () => ({}) };
    });
    const beforeGreeting = { ...model, messages: model.messages.filter((message) => message.sender === "user") };
    const view = render(<ConversationFrame model={beforeGreeting} actions={actions} runtimeIntentStatus="ready" />);

    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus="ready" />);

    expect(animate).not.toHaveBeenCalled();
    expect(screen.getByTestId("conversation-ally").style.transform).toContain("translate(0px, 220px)");
  });

  it("keeps one avatar mounted through sleeping, waking, readiness and thinking", () => {
    const view = render(<ConversationFrame model={model} actions={actions} sleeping />);
    const actor = screen.getByTestId("conversation-ally");
    const frame = actor.querySelector("iframe")!;
    expect(actor.getAttribute("data-location")).toBe("header");
    expect(actor.querySelector('[data-muted="true"]')).toBeTruthy();

    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus="waking" />);
    act(() => window.dispatchEvent(new MessageEvent("message", {
      source: frame.contentWindow, data: { type: "ally-state", state: "idle" },
    })));
    expect(actor.getAttribute("data-location")).toBe("thread");
    expect(screen.getByText("Waking up")).toBeTruthy();
    expect(actor.querySelector('[data-muted="true"]')).toBeTruthy();
    expect(actor.getAttribute("data-state")).toBe("idle");

    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus="ready" />);
    expect(actor.getAttribute("data-location")).toBe("thread");
    expect(actor.getAttribute("data-state")).toBe("idle");
    expect(actor.querySelector('[data-muted="false"]')).toBeTruthy();
    expect(actor.querySelector("iframe")).toBe(frame);

    view.rerender(<ConversationFrame model={{ ...model, showThinkingState: true, activityState: "queued" }} actions={actions} runtimeIntentStatus="ready" />);
    expect(actor.getAttribute("data-state")).toBe("idle");
    view.rerender(<ConversationFrame model={{ ...model, showThinkingState: true, activityState: "running" }} actions={actions} runtimeIntentStatus="waking" />);
    expect(actor.getAttribute("data-state")).toBe("thinking");
    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus="waking" />);
    expect(actor.getAttribute("data-location")).toBe("thread");
    expect(actor.getAttribute("data-state")).toBe("idle");
    expect(actor.querySelector("iframe")).toBe(frame);
    expect(screen.getByTestId("conversation-frame-shell").querySelectorAll("[data-ally-avatar]")).toHaveLength(1);
  });

  it("keeps an awake ally ready during a new composing intent check", () => {
    const view = render(<ConversationFrame model={{ ...model, showThinkingState: true, activityState: "running" }} actions={actions} />);
    view.rerender(<ConversationFrame model={model} actions={actions} />);
    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus="requesting" />);
    expect(screen.queryByRole("status", { name: "Waking up" })).toBeNull();
    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus="already_ready" />);
    expect(screen.queryByRole("status", { name: "Waking up" })).toBeNull();
  });

  it("shows thinking while an awake ally's message is being accepted", () => {
    render(<ConversationFrame model={{ ...model, activityGroups: [], showThinkingState: true, activityState: "queued" }} actions={actions} runtimeIntentStatus="ready" />);
    expect(screen.getByRole("status", { name: "Thinking" })).toBeTruthy();
  });

  it.each(["turn", "message"])("clears stale waking when polling delivers a completed %s without running events", (source) => {
    const waiting = { ...model, messages: model.messages.filter((message) => message.sender === "user"), activityGroups: [], showThinkingState: true, activityState: "queued" as const };
    const view = render(<ConversationFrame model={waiting} actions={actions} runtimeIntentStatus="waking" />);
    expect(screen.getByText("Waking up")).toBeTruthy();
    const completed = {
      ...waiting, showThinkingState: false, activityState: "completed" as const,
      messages: source === "message" ? model.messages : waiting.messages,
      turns: source === "turn" ? [{ messageId: "message-2", turnOrdinal: 4, state: "completed" as const, assistantText: "Here is your reply." }] : [],
    };
    view.rerender(<ConversationFrame model={completed} actions={actions} runtimeIntentStatus="waking" />);
    expect(screen.queryByText("Waking up")).toBeNull();
    expect(screen.getByTestId("conversation-ally").querySelector('[data-muted="false"]')).toBeTruthy();
    view.rerender(<ConversationFrame model={completed} actions={actions} runtimeIntentStatus="waking" />);
    expect(screen.queryByText("Waking up")).toBeNull();
    view.rerender(<ConversationFrame model={completed} actions={actions} sleeping />);
    view.rerender(<ConversationFrame model={completed} actions={actions} runtimeIntentStatus="waking" />);
    expect(screen.getByText("Waking up")).toBeTruthy();
  });

  it.each([null, "ready", "already_ready"] as const)("invalidates prior wake evidence after sleep with retained intent %s", (status) => {
    const view = render(<ConversationFrame model={{ ...model, showThinkingState: true, activityState: "running" }} actions={actions} runtimeIntentStatus={status} />);
    const actor = screen.getByTestId("conversation-ally");
    expect(actor.getAttribute("data-location")).toBe("thread");
    view.rerender(<ConversationFrame model={model} actions={actions} sleeping runtimeIntentStatus={status} />);
    expect(screen.getByText("Sally is asleep")).toBeTruthy();
    view.rerender(<ConversationFrame model={model} actions={actions} runtimeIntentStatus={status} />);
    expect(screen.getByText("Waking up")).toBeTruthy();
    expect(actor.getAttribute("data-location")).toBe("thread");
    expect(actor.querySelector('[data-muted="true"]')).toBeTruthy();
    view.rerender(<ConversationFrame model={{ ...model, showThinkingState: true, activityState: "running" }} actions={actions} runtimeIntentStatus={status} />);
    expect(actor.getAttribute("data-location")).toBe("thread");
    expect(actor.querySelector('[data-muted="false"]')).toBeTruthy();
  });

  it.each(["failed", "disabled", "rate_limited", "first_provision_required"] as const)("keeps speculative wake result %s neutral without claiming readiness or blocking send", (status) => {
    render(<ConversationFrame model={model} actions={actions} runtimeIntentStatus={status} />);
    expect(screen.getByTestId("conversation-ally").getAttribute("data-location")).toBe("thread");
    expect(screen.getByText("Waking up")).toBeTruthy();
    expect(screen.queryByText(/couldn’t wake/)).toBeNull();
    expect(screen.getByRole("textbox").hasAttribute("disabled")).toBe(false);
  });

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

    expect(screen.getByText("This Ally is waiting for an action.")).toBeTruthy();
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

  it("moves each approval once through the real fallback, presence, and historical insertion sites", async () => {
    const approvals: ApprovalSummary[] = messages.slice(0, 2).map((message, index) => ({
      id: `approval-${index + 1}`,
      messageId: message.id,
      status: "decision_recorded",
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
      decidedAt: new Date().toISOString(),
      acknowledgementDeadlineAt: new Date(Date.now() + 30_000).toISOString(),
    }));
    const client: ApprovalClient = {
      getApprovals: vi.fn().mockResolvedValue(approvals),
      getApproval: vi.fn().mockImplementation(async (_workspace, _conversation, id) => ({ ...approvals.find((item) => item.id === id)!, actionLabel: "Action", actionPreview: "Preview" })),
      decideApproval: vi.fn(),
    };
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const tree = (frameModel: ProductionConversationFrameModel, sleeping = false) => <QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Sally" accent="#fd304f" canApprove><ConversationFrame model={frameModel} actions={actions} sleeping={sleeping} /></ConversationApprovals></QueryClientProvider>;
    const view = render(tree(model));
    await screen.findAllByRole("button", { name: "Decision recorded · Waiting for Ally" });
    const first = () => view.container.querySelector<HTMLElement>(`[data-approval-id="${approvals[0].id}"]`)!;
    const second = () => view.container.querySelector<HTMLElement>(`[data-approval-id="${approvals[1].id}"]`)!;
    expect(view.container.querySelectorAll(`[data-approval-id="${approvals[0].id}"]`)).toHaveLength(1);
    expect(first().closest('[class*="frameMessageRow"]')).not.toBeNull();
    expect(second().closest('[class*="frameMessageRow"]')).not.toBeNull();

    view.rerender(tree({ ...model, messages: [model.messages[0]], showThinkingState: true, activityState: "running", activityGroups: [{ ...model.activityGroups[0], entries: [{ ...model.activityGroups[0].entries[0], activityId: "call-1", activityAttemptId: "attempt-1" }] }] }));
    expect(first().closest('[class*="framePresenceActivity"]')).not.toBeNull();
    expect(view.container.querySelectorAll(`[data-approval-id="${approvals[0].id}"]`)).toHaveLength(1);

    view.rerender(tree({ ...model, messages: [model.messages[0]], showThinkingState: true, activityState: "running", activityGroups: [{ ...model.activityGroups[0], entries: [{ ...model.activityGroups[0].entries[0], activityId: "call-1", activityAttemptId: "attempt-1" }] }] }, true));
    expect(first().closest('[class*="frameMessageRow"]')).not.toBeNull();
    expect(first().closest('[class*="framePresenceActivity"]')).toBeNull();
    expect(view.container.querySelectorAll(`[data-approval-id="${approvals[0].id}"]`)).toHaveLength(1);

    view.rerender(tree({ ...model, messages: [model.messages[1]], activityGroups: [] }));
    expect(first().closest('[class*="frameMessageRow"]')).toBeNull();
    expect(first().closest('[class*="framePresenceActivity"]')).toBeNull();
    expect(second().closest('[class*="frameMessageRow"]')).not.toBeNull();
    expect(view.container.querySelectorAll(`[data-approval-id]`)).toHaveLength(2);
  });

  it("renders exact local timestamps as siblings and reveals them on click and focus", () => {
    vi.useFakeTimers();
      const view = render(<ConversationFrame model={model} actions={actions} />);
      const user = screen.getByText("First request", { selector: "article p" }).closest("article")!;
      const legacyAssistant = [...view.container.querySelectorAll("article")]
        .find((article) => article.textContent?.includes("A normal production reply."))!;
      const timestampFor = (article: HTMLElement) => {
        const timestamp = article.nextElementSibling;
        expect(timestamp?.tagName).toBe("TIME");
        expect(article.contains(timestamp)).toBe(false);
        expect(timestamp?.parentElement).toBe(article.parentElement);
        return timestamp as HTMLTimeElement;
      };
      const timestamp = timestampFor(user);
      const legacyTimestamp = timestampFor(legacyAssistant);
      const expectedLabel = new Intl.DateTimeFormat([], { timeStyle: "short" }).format(new Date(messages[0].createdAt));

      expect(timestamp.textContent).toBe(expectedLabel);
      expect(timestamp.textContent).not.toBe(new Intl.DateTimeFormat([], { timeStyle: "medium" }).format(new Date(messages[0].createdAt)));
      expect(timestamp.getAttribute("dateTime")).toBe(messages[0].createdAt);
      expect(legacyTimestamp.getAttribute("dateTime")).toBe(messages[2].createdAt);
      expect(timestamp.getAttribute("data-visible")).toBe("false");
      fireEvent.click(user);
      expect(timestamp.getAttribute("data-visible")).toBe("true");
      act(() => vi.advanceTimersByTime(3_000));
      expect(timestamp.getAttribute("data-visible")).toBe("false");
      fireEvent.focus(user);
      expect(timestamp.getAttribute("data-visible")).toBe("true");
      act(() => vi.advanceTimersByTime(2_000));
      fireEvent.keyDown(user, { key: "Enter" });
      act(() => vi.advanceTimersByTime(1_000));
      expect(timestamp.getAttribute("data-visible")).toBe("true");
      fireEvent.keyDown(user, { key: " " });
      act(() => vi.advanceTimersByTime(3_000));
      expect(timestamp.getAttribute("data-visible")).toBe("false");

      view.rerender(<ConversationFrame model={{
        ...model,
        messages: [model.messages[0]],
        turns: [{
          assistantText: "A durable reply.",
          createdAt: messages[2].createdAt,
          messageId: model.messages[0].id,
          state: "completed",
          turnOrdinal: 1,
        }],
        activityGroups: [],
      }} actions={actions} />);
      const durableAssistant = screen.getByTestId("activity-reply-1");
      expect(timestampFor(durableAssistant).getAttribute("dateTime")).toBe(messages[2].createdAt);
  });

  it("omits the timestamp and reveal tab stop for invalid or missing dates", () => {
    render(
      <>
        <UserBubble createdAt="not-a-date">Invalid timestamp</UserBubble>
        <AssistantMessage>Missing timestamp</AssistantMessage>
      </>,
    );

    const invalid = screen.getByText("Invalid timestamp", { selector: "article p" }).closest("article")!;
    const missing = screen.getByText("Missing timestamp").closest("article")!;
    expect(invalid.nextElementSibling?.tagName).not.toBe("TIME");
    expect(missing.nextElementSibling).toBeNull();
    expect(invalid.getAttribute("tabindex")).toBeNull();
    expect(missing.getAttribute("tabindex")).toBeNull();
  });

  it("scrolls an expanded Activity disclosure into the nearest visible position", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    render(<ConversationFrame model={model} actions={actions} />);
    fireEvent.click(screen.getByText("1 activity"));
    await vi.waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: "nearest", behavior: "smooth" }));
  });

  it("keeps completed legacy history collapsed and static", () => {
    const completedActivity = {
      ...model,
      activityGroups: [{
        ...model.activityGroups[0],
        entries: [
          model.activityGroups[0].entries[0],
          {
            ...model.activityGroups[0].entries[0],
            id: "activity-2",
            sequence: 3,
            kind: "activity_completed" as const,
            text: "Search completed",
            state: "completed" as const,
          },
        ],
      }],
      activityState: "completed" as const,
      showThinkingState: false,
    };

    render(<ConversationFrame model={completedActivity} actions={actions} />);

    const request = screen.getByText("First request", { selector: "article p" });
    const disclosure = request.closest("article")?.parentElement?.querySelector("details");
    expect(disclosure?.querySelector("summary")?.textContent).toContain("2 activities");
    expect(disclosure?.open).toBe(false);
    expect(disclosure?.querySelector(".shiny-text")).toBeNull();
    expect(disclosure?.textContent).toContain("Searching for citysubs");
  });

  it("shimmers only the active header and collapses its history when the turn finishes", () => {
    const entry = { ...model.activityGroups[0].entries[0], activityId: "call-a", activityAttemptId: "attempt-a", activityKind: "web_search" };
    const active: ProductionConversationFrameModel = {
      ...model, messages: [model.messages[0]], showThinkingState: true, activityState: "running",
      activityGroups: [{ ...model.activityGroups[0], entries: [entry] }],
    };
    const view = render(<ConversationFrame model={active} actions={actions} />);
    const details = view.container.querySelector("details")!;
    expect(details.querySelectorAll(".shiny-text")).toHaveLength(1);
    expect(details.querySelector("summary .shiny-text")?.textContent).toBe(entry.text);
    expect(details.querySelector('[class*="frameActivityEntries"] .shiny-text')).toBeNull();
    act(() => { details.open = true; fireEvent(details, new Event("toggle")); });
    expect(details.open).toBe(true);
    view.rerender(<ConversationFrame model={{ ...active, showThinkingState: false, activityState: "completed" }} actions={actions} />);
    const history = view.container.querySelector("details")!;
    expect(history.open).toBe(false);
    expect(history.querySelector(".shiny-text")).toBeNull();
    act(() => { history.open = true; fireEvent(history, new Event("toggle")); });
    expect(history.open).toBe(true);
  });

  it("resets the presence disclosure when the current activity group changes", () => {
    const entry = { ...model.activityGroups[0].entries[0], activityId: "call-a", activityAttemptId: "attempt-a", activityKind: "web_search" };
    const active: ProductionConversationFrameModel = {
      ...model,
      messages: [model.messages[0]],
      showThinkingState: true,
      activityState: "running",
      activityGroups: [{ ...model.activityGroups[0], entries: [entry] }],
    };
    const view = render(<ConversationFrame model={active} actions={actions} />);
    const details = view.container.querySelector("details")!;

    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);

    view.rerender(<ConversationFrame model={{
      ...active,
      activityGroups: [{
        ...active.activityGroups[0],
        key: "message-1:2",
        conversationTurnOrdinal: 2,
        entries: [{ ...entry, id: "activity-2", conversationTurnOrdinal: 2, text: "Reading a webpage" }],
      }],
    }} actions={actions} />);

    expect(view.container.querySelector("details")?.open).toBe(false);
  });

  it("uses the readable activity accent for active icons and muted color for terminal rows", () => {
    const activeEntry = { ...model.activityGroups[0].entries[0], activityId: "call-a", activityAttemptId: "attempt-a", activityKind: "web_search" };
    const terminalEntry = { ...activeEntry, id: "activity-2", kind: "activity_completed" as const, outcome: "failed" as const, text: "Could not finish searching" };
    const active: ProductionConversationFrameModel = {
      ...model,
      messages: [model.messages[0]],
      showThinkingState: true,
      activityState: "running",
      activityGroups: [{ ...model.activityGroups[0], entries: [activeEntry, terminalEntry] }],
    };

    const view = render(<ConversationFrame model={active} actions={actions} />);
    const icons = [...view.container.querySelectorAll('[class*="frameActivityEntries"] svg')];

    expect(icons).toHaveLength(2);
    expect([...icons[0].querySelectorAll("path")].every((path) => path.getAttribute("fill") === "var(--chat-activity-accent, var(--chat-accent))")).toBe(true);
    expect([...icons[1].querySelectorAll("path")].every((path) => path.getAttribute("fill") === "var(--text-secondary)")).toBe(true);
  });

  it("uses command copy only for terminal activity", () => {
    const entry = { ...model.activityGroups[0].entries[0], activityId: "call-a", activityAttemptId: "attempt-a" };
    const view = render(<ConversationFrame model={{
      ...model,
      messages: [model.messages[0]],
      showThinkingState: true,
      activityState: "running",
      activityGroups: [{ ...model.activityGroups[0], entries: [{ ...entry, activityKind: "terminal", text: "Doing an activity" }] }],
    }} actions={actions} />);

    expect(view.getAllByText("Running a command")).toHaveLength(2);
    view.rerender(<ConversationFrame model={{
      ...model,
      activityGroups: [{ ...model.activityGroups[0], entries: [{ ...entry, kind: "activity_completed", outcome: "completed", activityKind: "terminal", text: "Finished an activity" }] }],
    }} actions={actions} />);
    expect(view.getByText("Ran a command")).toBeTruthy();
    expect(view.queryByText("Finished an activity")).toBeNull();
    for (const [outcome, text] of [["failed", "Command failed"], ["stopped", "Command stopped"], ["unavailable", "Command unavailable"]] as const) {
      view.rerender(<ConversationFrame model={{
        ...model,
        activityGroups: [{ ...model.activityGroups[0], entries: [{ ...entry, kind: "activity_completed", outcome, activityKind: "terminal", text }] }],
      }} actions={actions} />);
      expect(view.getByText(text)).toBeTruthy();
      expect(view.queryByText("Ran a command")).toBeNull();
    }
    view.rerender(<ConversationFrame model={{
      ...model,
      showThinkingState: true,
      activityState: "running",
      activityGroups: [{ ...model.activityGroups[0], entries: [{ ...entry, activityKind: "unknown", text: "Doing an activity" }] }],
    }} actions={actions} />);
    expect(view.getByText("Doing an activity")).toBeTruthy();
    view.rerender(<ConversationFrame model={{
      ...model,
      activityGroups: [{ ...model.activityGroups[0], entries: [{ ...entry, kind: "activity_completed", outcome: "completed", activityKind: "unknown", text: "Finished an activity" }] }],
    }} actions={actions} />);
    expect(view.getByText("Finished an activity")).toBeTruthy();
  });

  it("keeps the active status live region mounted while its label changes", () => {
    const entry = { ...model.activityGroups[0].entries[0], activityId: "call-a", activityAttemptId: "attempt-a", activityKind: "web_search" };
    const active: ProductionConversationFrameModel = {
      ...model,
      messages: [model.messages[0]],
      showThinkingState: true,
      activityState: "running",
      activityGroups: [{ ...model.activityGroups[0], entries: [entry] }],
    };
    const view = render(<ConversationFrame model={active} actions={actions} />);
    const liveRegion = view.container.querySelector('summary > span[role="status"]');

    view.rerender(<ConversationFrame model={{ ...active, activityGroups: [{ ...active.activityGroups[0], entries: [{ ...entry, text: "Reading a webpage" }] }] }} actions={actions} />);

    expect(liveRegion).not.toBeNull();
    expect(view.container.querySelector('summary > span[role="status"]')).toBe(liveRegion);
  });

  it("falls back safely for prototype-named activity kinds", () => {
    const entry = { ...model.activityGroups[0].entries[0], activityKind: "constructor" };
    expect(() => render(<ConversationFrame model={{ ...model, activityGroups: [{ ...model.activityGroups[0], entries: [entry] }] }} actions={actions} />)).not.toThrow();
  });

  it("fits the focused conversation to the visual viewport and follows the latest message", () => {
    const viewport = new EventTarget() as VisualViewport;
    const requestFrame = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    Object.defineProperty(viewport, "height", { configurable: true, value: 480 });
    Object.defineProperty(viewport, "offsetTop", { configurable: true, value: 24 });
    Object.defineProperty(window, "visualViewport", { configurable: true, value: viewport });
    const view = render(<ConversationFrame model={model} actions={actions} />);
    const shell = screen.getByTestId("conversation-frame-shell");
    const canvas = screen.getByTestId("conversation-frame-canvas");
    const scrollTo = vi.fn();
    Object.defineProperties(canvas, {
      clientHeight: { configurable: true, value: 400 },
      scrollHeight: { configurable: true, value: 600 },
      scrollTop: { configurable: true, value: 180, writable: true },
      scrollTo: { configurable: true, value: scrollTo },
    });

    act(() => screen.getByRole("textbox").focus());
    act(() => viewport.dispatchEvent(new Event("resize")));

    expect(shell.style.getPropertyValue("--chat-viewport-height")).toBe("480px");
    expect(shell.style.getPropertyValue("--chat-viewport-offset")).toBe("24px");
    expect(scrollTo).toHaveBeenCalledWith({ top: 600 });
    scrollTo.mockClear();
    canvas.scrollTop = 0;
    fireEvent.scroll(canvas);
    act(() => viewport.dispatchEvent(new Event("resize")));
    expect(scrollTo).not.toHaveBeenCalled();
    act(() => screen.getByRole("textbox").blur());
    expect(shell.style.getPropertyValue("--chat-viewport-height")).toBe("");
    expect(shell.style.getPropertyValue("--chat-viewport-offset")).toBe("");
    view.unmount();
    expect(shell.style.getPropertyValue("--chat-viewport-height")).toBe("");
    expect(shell.style.getPropertyValue("--chat-viewport-offset")).toBe("");
    requestFrame.mockRestore();
    Object.defineProperty(window, "visualViewport", { configurable: true, value: undefined });
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

  it.each(["idle", "sleeping", "waking", "busy"] as const)("requests immediate bubble presentation only for an awake idle Ally (%s)", (state) => {
    const onSubmit = vi.fn();
    render(<ConversationFrame model={{ ...model,
      showThinkingState: state === "busy",
      composer: { ...model.composer, draft: "Hello", disabled: false },
    }} actions={{ ...actions, onSubmit }} sleeping={state === "sleeping"}
      runtimeIntentStatus={state === "waking" ? "waking" : "ready"} />);
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(onSubmit).toHaveBeenCalledWith(state === "idle");
  });

  it("buffers partial answer text while keeping the thinking avatar and activities live", () => {
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

    const status = screen.getByRole("status", { name: "Thinking" });
    expect(status.textContent).toBe("Thinking..");
    expect(screen.queryByTestId("activity-reply-4")).toBeNull();
    expect(screen.queryByText("A response is being generated.")).toBeNull();
    expect(screen.getAllByText("Searching for citysubs").length).toBeGreaterThan(0);
    expect(screen.getByTestId("conversation-ally").getAttribute("data-state")).toBe("thinking");
    expect(screen.getByTestId("conversation-frame-shell").querySelectorAll("[data-ally-avatar]")).toHaveLength(1);
    expect(status).toBeTruthy();
  });

  it("reveals a newly completed answer once and renders reopened history immediately", () => {
    vi.useFakeTimers();
    try {
      const running = { ...model, messages: model.messages.slice(0, 2), turns: [{
        assistantText: "Partial", messageId: "message-2", state: "running" as const, turnOrdinal: 4,
      }] };
      const complete = { ...running, turns: [{ ...running.turns[0], state: "completed" as const, assistantText: "The full answer is here." }] };
      const view = render(<ConversationFrame model={running} actions={actions} />);
      expect(screen.queryByText("Partial")).toBeNull();
      view.rerender(<ConversationFrame model={complete} actions={actions} />);
      const reply = screen.getByTestId("activity-reply-4");
      expect(reply.textContent).toBe("The full answer is here.");
      expect(reply.querySelector('[data-sd-animate]')).toBeTruthy();
      act(() => vi.advanceTimersByTime(2800));
      expect(reply.querySelector('[data-sd-animate]')).toBeNull();
      view.unmount();
      render(<ConversationFrame model={complete} actions={actions} />);
      expect(screen.getByTestId("activity-reply-4").textContent).toBe("The full answer is here.");
      expect(screen.getByTestId("activity-reply-4").querySelector('[data-sd-animate]')).toBeNull();
    } finally { vi.useRealTimers(); }
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

  it("keeps the desktop fade and enables the mobile fade when the thread scrolls", () => {
    render(<ConversationFrame model={model} actions={actions} />);

    expect(screen.getByTestId("conversation-frame-scroll-blur").className).toContain("frameDesktopFade");
    fireEvent.scroll(screen.getByTestId("conversation-frame-canvas"), { target: { scrollTop: 24 } });
    expect(screen.getByTestId("conversation-frame-scroll-blur").className).not.toContain("frameDesktopFade");
    fireEvent.scroll(screen.getByTestId("conversation-frame-canvas"), { target: { scrollTop: 0 } });
    expect(screen.getByTestId("conversation-frame-scroll-blur").className).toContain("frameDesktopFade");
  });

  it("shows sleep only when the workspace reports it, regardless of elapsed time", () => {
    vi.useFakeTimers();
    try {
      const view = render(<ConversationFrame model={model} actions={actions} />);
      act(() => vi.advanceTimersByTime(10_000));
      expect(screen.queryByTestId("ally-sleeping-status")).toBeNull();
      view.rerender(<ConversationFrame model={model} actions={actions} sleeping />);
      expect(screen.getByTestId("ally-sleeping-status").textContent).toContain("Sally is asleep");
      expect(screen.getByTestId("conversation-frame-scroll-blur").className).not.toContain("frameDesktopFade");
      view.rerender(<ConversationFrame model={model} actions={actions} sleeping={false} runtimeIntentStatus="ready" />);
      expect(screen.queryByTestId("ally-sleeping-status")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renders routine projections with truthful insertion state and attributed approval actions", async () => {
    const routineId = "00000000-0000-4000-8000-000000000010";
    const runId = "00000000-0000-4000-8000-000000000012";
    const approvalRequestId = "00000000-0000-4000-8000-000000000016";
    const approvalItem: RoutineChatItemViewModel = {
      id: runId,
      kind: "running",
      routineId,
      conversationId: "conversation-1",
      titleSnapshot: "Morning brief",
      routineRevision: 2,
      scheduleGeneration: 1,
      status: "approval_waiting",
      schedule: { kind: "recurring", frequency: "daily", localTime: "09:30:00", timezone: "UTC" },
      occurredAt: "2026-09-09T09:30:01Z",
      occurrenceId: "00000000-0000-4000-8000-000000000011",
      runId,
      executionId: null,
      attemptId: null,
      generation: null,
      resultId: null,
      resultInsertion: null,
      text: null,
      references: [],
      delayed: false,
      approvalId: "00000000-0000-4000-8000-000000000017",
      approvalRequestId,
      approvalStatus: "pending",
      approvalDecision: null,
      actionDigest: null,
      actionAttemptId: "00000000-0000-4000-8000-000000000018",
      approvalExpiresAt: "2026-09-09T09:35:01Z",
    };
    const resultItem: RoutineChatItemViewModel = {
      ...approvalItem,
      id: "00000000-0000-4000-8000-000000000015",
      kind: "result",
      status: "changed",
      occurredAt: "2026-09-09T09:31:00Z",
      executionId: "00000000-0000-4000-8000-000000000013",
      attemptId: "00000000-0000-4000-8000-000000000014",
      generation: 1,
      resultId: "00000000-0000-4000-8000-000000000015",
      resultInsertion: "pending",
      text: "The brief is ready.",
      references: [{ label: "Source", url: "https://example.com/source" }],
      approvalId: null,
      approvalRequestId: null,
      approvalStatus: null,
      actionAttemptId: null,
      approvalExpiresAt: null,
    };
    const onRoutineAction = vi.fn(async () => true);
    const onOpenRoutine = vi.fn();
    render(<ConversationFrame model={{ ...model, routineItems: [approvalItem, resultItem] }} actions={{
      ...actions,
      onRoutineAction,
      onOpenRoutine,
    }} />);

    expect(screen.queryByRole("region", { name: "Routine updates" })).toBeNull();
    expect(screen.getByText("· Waiting for approval")).toBeTruthy();
    expect(screen.getByText("Pending insertion — waiting to appear in chat.")).toBeTruthy();
    expect(screen.queryByText("Added to chat.")).toBeNull();
    expect(screen.queryByText("The brief is ready.")).toBeNull();
    expect(screen.queryByRole("link", { name: "Source" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onRoutineAction).toHaveBeenCalledWith(expect.objectContaining({
      action: "approve",
      routineId,
      routineRevision: 2,
      titleSnapshot: "Morning brief",
      runId,
      approvalRequestId,
      actionAttemptId: "00000000-0000-4000-8000-000000000018",
    }));
    fireEvent.click(screen.getAllByRole("button", { name: /Morning brief/ })[0]!);
    expect(onOpenRoutine).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog").textContent).toContain("Run status");

    cleanup();
    render(<ConversationFrame model={{ ...model, routineItems: [approvalItem, { ...resultItem, status: "failed", resultInsertion: "inserted", text: "Routine failed before completion." }] }} actions={{ ...actions, onOpenRoutine }} />);
    expect(screen.getByText("Routine failed before completion.").closest("article")).toBeTruthy();
    const failureLink = screen.getByRole("button", { name: "Morning brief · Failed" });
    expect(failureLink.closest("article")).toBeNull();
    expect(failureLink.parentElement?.querySelector("time")).toBeNull();
    fireEvent.click(failureLink);
    expect(onOpenRoutine).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog").textContent).toContain("Run failed");
    expect(screen.getByRole("dialog").textContent).toContain("Triggered");
    expect(screen.getAllByText("Routine failed before completion.")).toHaveLength(2);
    cleanup();
    render(<ConversationFrame model={{ ...model, routineItems: [{ ...resultItem, resultInsertion: "inserted", text: "**The brief is ready.**" }] }} actions={{ ...actions, onOpenRoutine }} />);
    const successLink = screen.getByRole("button", { name: "Morning brief · Succeeded" });
    const resultMessage = screen.getByText("The brief is ready.");
    expect(resultMessage.closest("article")).toBeTruthy();
    expect(successLink.compareDocumentPosition(resultMessage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Source" })).toBeTruthy();
    fireEvent.click(successLink);
    expect(screen.getByRole("dialog").textContent).toContain("Completed · changed");
    cleanup();
    const detail: RoutineDiscoveryDetail = {
      routineId,
      responsibleAllyId: "ally-1",
      title: "Morning brief",
      schedule: approvalItem.schedule,
      revision: 2,
      scheduleGeneration: 1,
      scheduleState: "active",
      nextRunAt: "2026-09-10T09:30:00Z",
      createdAt: "2026-09-09T08:00:00Z",
      updatedAt: "2026-09-09T08:00:00Z",
      workspaceId: "workspace-1",
      ownerUserId: "owner-1",
      bindingId: "binding-1",
      mainConversationId: "conversation-1",
      executionPrompt: "Check the latest brief and report any changes.",
    };
    const onDetailAction = vi.fn(async () => true);
    render(<ConversationFrame model={{
      ...model,
      routineItems: [approvalItem],
      routineDetail: { routineId, detail, loading: false, error: null },
    }} actions={{ ...actions, onRoutineAction: onDetailAction }} />);
    expect(screen.getByText("Full prompt")).toBeTruthy();
    fireEvent.click(screen.getByText("Full prompt"));
    expect(screen.getByText(detail.executionPrompt)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(onDetailAction).toHaveBeenCalledWith({
      action: "pause",
      routineId,
      routineRevision: detail.revision,
      titleSnapshot: detail.title,
    });
    onDetailAction.mockClear();
    onDetailAction.mockResolvedValueOnce(false).mockRejectedValueOnce(new Error("Network error"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDetailAction).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(onDetailAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDetailAction).toHaveBeenCalledWith({ action: "delete", routineId,
      routineRevision: detail.revision, titleSnapshot: detail.title, confirmed: true });
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByRole("alert")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(within(screen.getByRole("dialog")).getByRole("alert")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());

    cleanup();
    render(<ConversationFrame model={{
      ...model,
      routineItems: [approvalItem],
      routineDetail: { routineId, detail: { ...detail, scheduleState: "deleted" }, loading: false, error: null },
    }} actions={actions} />);
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("opens routine details as a modal and restores focus to its card", async () => {
    const routineId = "00000000-0000-4000-8000-000000000010";
    const item: RoutineChatItemViewModel = {
      id: routineId,
      kind: "created",
      routineId,
      conversationId: "conversation-1",
      titleSnapshot: "Morning brief",
      routineRevision: 2,
      scheduleGeneration: 1,
      status: "active",
      schedule: { kind: "recurring", frequency: "daily", localTime: "09:30:00", timezone: "UTC" },
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
    const detail: RoutineDiscoveryDetail = {
      routineId,
      responsibleAllyId: "ally-1",
      title: "Morning brief",
      schedule: item.schedule,
      revision: 2,
      scheduleGeneration: 1,
      scheduleState: "active",
      nextRunAt: "2026-09-10T09:30:00Z",
      createdAt: "2026-09-09T08:00:00Z",
      updatedAt: "2026-09-09T08:00:00Z",
      workspaceId: "workspace-1",
      ownerUserId: "owner-1",
      bindingId: "binding-1",
      mainConversationId: "conversation-1",
      executionPrompt: "Check the latest brief and report any changes.",
    };
    let finishLoading = () => {};
    function Harness() {
      const [open, setOpen] = useState(false);
      const [loadedDetail, setLoadedDetail] = useState<RoutineDiscoveryDetail | null>(null);
      const openRoutine = () => {
        setLoadedDetail(null);
        setOpen(true);
        finishLoading = () => setLoadedDetail(detail);
      };
      return (
        <ConversationFrame
          model={{
            ...model,
            routineItems: [item],
            routineDetail: { routineId: open ? routineId : null, detail: open ? loadedDetail : null, loading: open && !loadedDetail, error: null },
          }}
          actions={{ ...actions, onOpenRoutine: openRoutine, onCloseRoutine: () => setOpen(false) }}
        />
      );
    }
    render(<Harness />);
    const card = screen.getByRole("button", { name: /Morning brief/ });
    card.focus();
    fireEvent.click(card);
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(screen.getByText("Loading routine details…")).toBeTruthy();
    act(() => finishLoading());
    await waitFor(() => expect(screen.getByText("Full prompt")).toBeTruthy());
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(document.activeElement).toBe(card));
  });
});
