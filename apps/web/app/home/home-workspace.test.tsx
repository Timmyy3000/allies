// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AllyViewModel } from "@allies/cloud-client";
import type { RuntimeIntentRequester } from "../../lib/allies/runtime-intent";

import {
  ActivityReplayBoundError,
  ALLY_SLEEP_AFTER_MS,
  activityReplayFailure,
  HomeWorkspace,
  isAllySleeping,
} from "./home-workspace";

const replace = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
const useSessionMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push }) }));
vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: React.PropsWithChildren<React.AnchorHTMLAttributes<HTMLAnchorElement>>) => <a {...props}>{children}</a>,
}));
vi.mock("next/image", () => ({
  default: ({
    priority,
    unoptimized,
    ...props
  }: React.ImgHTMLAttributes<HTMLImageElement> & { priority?: boolean; unoptimized?: boolean }) => {
    void priority;
    void unoptimized;
    return createElement("img", { ...props, alt: props.alt ?? "" });
  },
}));
vi.mock("../../lib/session/session-context", () => ({ useSession: useSessionMock }));
vi.mock("../../components/ally-avatar", () => ({
  ALLY_SHAPES: ["boxy", "ghosty", "rocky", "rolly"],
  AllyAvatar: ({ label, className }: { label?: string; className?: string }) => (
    <span data-testid="ally-avatar" aria-label={label} className={className} />
  ),
}));
vi.mock("../(onboarding)/_components", () => ({ default: () => <div>Shape your Ally</div> }));
vi.mock("../(onboarding)/_store/onboarding-store", () => ({ OnboardingStateProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../../lib/allies/authenticated-onboarding-flow", () => ({ AuthenticatedAllyFlowProvider: ({ children }: { children: React.ReactNode }) => children }));

const account = {
  userId: "user",
  displayName: "Timi Person",
  avatarUrl: null,
  session: { id: "session", expiresAt: "2026-08-20T16:00:00Z" },
  workspace: { id: "workspace", name: "Personal", role: "owner", capabilities: [] },
};
const ally: AllyViewModel = {
  id: "00000000-0000-4000-8000-000000000002",
  bindingId: "00000000-0000-4000-8000-000000000003",
  operationId: "00000000-0000-4000-8000-000000000004",
  name: "Mira",
  job: "Study partner",
  personality: "Calm",
  appearance: { catalogVersion: "v1", key: "ghosty:fd304f" },
  provisioningState: "bound" as const,
  retryable: false,
};

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
});

function renderHome(
  allies: AllyViewModel[],
  selectedAllyId: string | null = null,
  clientOverrides: Record<string, unknown> = {},
) {
  const client = {
    getCurrentAccount: vi.fn(async () => account),
    listAllies: vi.fn(async () => allies),
    getAllyConversation: vi.fn(async () => ({
      id: "00000000-0000-4000-8000-000000000005",
      allyId: ally.id,
      messages: [{
        id: "00000000-0000-4000-8000-000000000006",
        sender: "assistant" as const,
        content: "What should we work on first?",
        sequence: 1,
        status: "completed" as const,
        createdAt: "2026-08-20T16:00:00Z",
      }],
      nextCursor: null,
    })),
    getActivities: vi.fn(async () => ({
      conversationId: "00000000-0000-4000-8000-000000000005",
      activities: [],
      state: "completed" as const,
      lastContiguousSequence: 0,
    })),
    requestRuntimeIntent: vi.fn(async () => ({ status: "waking" as const })),
    ...clientOverrides,
  };
  useSessionMock.mockReturnValue({
    state: { status: "signed-in" },
    client,
    restore: vi.fn(),
    runCloudOperation: vi.fn(async (
      operation: (signal?: AbortSignal) => Promise<unknown>,
      options?: { signal?: AbortSignal },
    ) => operation(options?.signal)),
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <HomeWorkspace selectedAllyId={selectedAllyId} />
    </QueryClientProvider>,
  );
  return Object.assign(client, { queryClient });
}

async function clickSendMessage() {
  const button = screen.getByRole("button", { name: "Send message" }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
}

describe("HomeWorkspace", () => {
  it.each([
    [{ kind: "activity-cursor-gap" }, "gap"],
    [{ kind: "activity-cursor-expired" }, "expired"],
    [{ kind: "activity-cursor-invalid" }, "invalid"],
    [new ActivityReplayBoundError(), "bounds"],
  ] as const)("classifies replay recovery failure %s", (error, expected) => {
    expect(activityReplayFailure(error)).toBe(expected);
  });

  it("treats a bound Ally as sleeping after ten minutes without activity", () => {
    const latestMessage = {
      id: "00000000-0000-4000-8000-000000000006",
      sender: "assistant" as const,
      content: "What should we work on first?",
      sequence: 1,
      status: "completed" as const,
      createdAt: "2026-08-20T16:00:00Z",
    };
    const lastActivityAt = Date.parse(latestMessage.createdAt);

    expect(isAllySleeping(ally, latestMessage, lastActivityAt + ALLY_SLEEP_AFTER_MS - 1)).toBe(false);
    expect(isAllySleeping(ally, latestMessage, lastActivityAt + ALLY_SLEEP_AFTER_MS)).toBe(true);
    expect(isAllySleeping({ ...ally, provisioningState: "pending" }, latestMessage, lastActivityAt + ALLY_SLEEP_AFTER_MS)).toBe(false);
  });

  it("desaturates an inactive Ally and quiets its presence dot", async () => {
    renderHome([ally]);

    const row = await screen.findByRole("link", { name: /Mira/ });
    await waitFor(() => expect(row.getAttribute("data-ally-sleeping")).toBe("true"));
    expect(row.querySelector('[data-testid="ally-avatar"]')?.className).toContain("sleepingAvatar");
    expect(row.querySelector('[aria-hidden="true"]')?.className).toContain("presenceDotQuiet");
  });

  it("keeps an empty account honest and offers the first-Ally flow", async () => {
    renderHome([]);
    expect(await screen.findByText("No Allies here yet.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Mira" })).toBeNull();
    expect(screen.getByRole("link", { name: "Make an Ally" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Meet your first Ally" }).getAttribute("href")).toBe("/home/new");
  });

  it("hosts Ally creation inside the Home thread", async () => {
    renderHome([], "new");
    expect(await screen.findByText("Shape your Ally")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders a compact real Ally row and its persisted conversation", async () => {
    const client = renderHome([ally], ally.id);
    expect(await screen.findByRole("heading", { name: "Mira" })).toBeTruthy();
    expect(screen.getAllByText("Study partner")).toHaveLength(1);
    expect(await screen.findAllByText("What should we work on first?")).toHaveLength(2);
    await waitFor(() => expect(client.getAllyConversation).toHaveBeenCalled());
    expect(screen.queryByText(/unread/i)).toBeNull();
  });

  it("wakes once on the first meaningful edit without gating send", async () => {
    const requestRuntimeIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "waking" as const }));
    const sendMessage = vi.fn(async () => ({
      conversationId: "00000000-0000-4000-8000-000000000005",
      message: {
        id: "00000000-0000-4000-8000-000000000007",
        sender: "user" as const,
        content: "Hello",
        sequence: 2,
        status: "queued" as const,
        createdAt: "2026-08-20T16:01:00Z",
      },
      execution: null,
      replayed: false,
    }));
    renderHome([ally], ally.id, { requestRuntimeIntent, sendMessage });
    const input = await screen.findByRole("textbox");
    const row = screen.getByRole("link", { name: /Mira/ });
    await waitFor(() => expect(row.getAttribute("data-ally-sleeping")).toBe("true"));

    fireEvent.change(input, { target: { value: "  " } });
    expect(requestRuntimeIntent).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.change(input, { target: { value: "Hello, again" } });

    expect(row.getAttribute("data-ally-sleeping")).toBe("false");
    expect(requestRuntimeIntent).toHaveBeenCalledOnce();
    expect(requestRuntimeIntent.mock.calls[0]?.[0]).toBe(ally.id);
    expect(requestRuntimeIntent.mock.calls[0]).toHaveLength(4);
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
  });

  it("defers the first runtime intent until IME composition ends", async () => {
    const requestRuntimeIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "waking" as const }));
    renderHome([ally], ally.id, { requestRuntimeIntent });
    const input = await screen.findByRole("textbox");

    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "日" } });
    expect(requestRuntimeIntent).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input, { target: { value: "日本語" } });

    expect(requestRuntimeIntent).toHaveBeenCalledOnce();
  });

  it("keeps automatic provisioning retries explicit and actionable", async () => {
    const retryingAlly = { ...ally, provisioningState: "retryable" as const, retryable: true };
    renderHome([retryingAlly], retryingAlly.id);

    expect((await screen.findAllByText("Setup needs retry")).length).toBeGreaterThan(0);
    expect(screen.getByText("Mira's setup can be retried outside Home.")).toBeTruthy();
  });

  it("starts watching the retained initial turn when provisioning completes", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const greeting = {
      id: "00000000-0000-4000-8000-000000000006",
      sender: "assistant" as const,
      content: "What should we work on first?",
      sequence: 1,
      status: "completed" as const,
      createdAt: "2026-08-20T16:00:00Z",
    };
    const initialQuestion = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "Initial question",
      sequence: 2,
      status: "completed" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    let provisioned = false;
    let resolveResponse: ((snapshot: unknown) => void) | undefined;
    const getActivities = vi.fn()
      .mockResolvedValueOnce({
        conversationId,
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      })
      .mockImplementation(() => new Promise((resolve) => { resolveResponse = resolve; }));
    const getAllyConversation = vi.fn(async (
      _workspaceId: string,
      _allyId: string,
      options: { limit?: number },
    ) => ({
      id: conversationId,
      allyId: ally.id,
      messages: options.limit === 50
        ? [greeting, { ...initialQuestion, status: provisioned ? "queued" as const : "completed" as const }]
        : [initialQuestion],
      nextCursor: null,
    }));
    const pendingAlly = { ...ally, provisioningState: "pending" as const };
    const client = renderHome([pendingAlly], ally.id, {
      getAllyConversation,
      getActivities,
    });

    expect(await screen.findByText("Initial question", { selector: "article p" })).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    expect(screen.queryByText("Thinking")).toBeNull();
    const conversationReadsBeforeProvisioning = getAllyConversation.mock.calls
      .filter((call) => call[2]?.limit === 50).length;
    provisioned = true;
    await act(async () => {
      client.queryClient.setQueryData(["workspaces", "workspace", "allies"], [ally]);
    });

    expect(await screen.findByText("Thinking")).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(2), { timeout: 2_000 });
    await waitFor(() => expect(
      getAllyConversation.mock.calls.filter((call) => call[2]?.limit === 50).length,
    ).toBeGreaterThan(conversationReadsBeforeProvisioning));
    expect(screen.getByText("Thinking")).toBeTruthy();
    await act(async () => resolveResponse?.({
      conversationId,
      activities: [{
        id: "00000000-0000-4000-8000-000000000009",
        messageId: "00000000-0000-4000-8000-000000000007",
        sequence: 1,
        conversationTurnOrdinal: 2,
        kind: "assistant_delta",
        text: "The initial response arrived.",
        state: "running",
        createdAt: "2026-08-20T16:01:01Z",
      }],
      state: "running",
      lastContiguousSequence: 1,
    }));
    expect((await screen.findByTestId("activity-reply-2")).textContent).toBe("The initial response arrived.");
  });

  it("keeps the Ally roster on /home on desktop", async () => {
    const newest = { ...ally, id: "00000000-0000-4000-8000-000000000009", name: "Nova" };
    renderHome([newest, ally]);

    expect(await screen.findByRole("link", { name: /Nova/ })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps the Ally list as the mobile Home entry", async () => {
    renderHome([ally]);

    expect(await screen.findByRole("link", { name: /Mira/ })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("uses the roster-only layout on /home", async () => {
    renderHome([ally]);

    expect((await screen.findByRole("link", { name: "Timi Person" })).getAttribute("href")).toBe("/account");
    expect(screen.getByRole("link", { name: "Make an Ally" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Selected Ally conversation" })).toBeNull();
  });

  it("keeps the conversation back control pointed at /home", async () => {
    renderHome([ally], ally.id);

    expect((await screen.findByRole("link", { name: "Back to Allies" })).getAttribute("href")).toBe("/home");
  });

  it("keeps the older cursor and offers an inline retry after a page failure", async () => {
    const getConversation = vi.fn()
      .mockRejectedValueOnce(new Error("temporary history failure"))
      .mockResolvedValueOnce({
        id: "00000000-0000-4000-8000-000000000005",
        allyId: ally.id,
        messages: [{
          id: "00000000-0000-4000-8000-000000000010",
          sender: "assistant" as const,
          content: "An older answer",
          sequence: 0,
          status: "completed" as const,
          createdAt: "2026-08-20T15:00:00Z",
        }],
        nextCursor: null,
      });
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: "00000000-0000-4000-8000-000000000005",
        allyId: ally.id,
        messages: [],
        nextCursor: "cursor-1",
      })),
      getConversation,
    });

    fireEvent.click(await screen.findByRole("button", { name: "Earlier messages" }));
    expect(await screen.findByText("We couldn't load earlier messages. Try again.")).toBeTruthy();
    const retry = screen.getByRole("button", { name: "Try again" });
    expect(getConversation.mock.calls[0]?.[2]).toMatchObject({ cursor: "cursor-1" });

    fireEvent.click(retry);
    await waitFor(() => expect(getConversation).toHaveBeenCalledTimes(2));
    expect(getConversation.mock.calls[1]?.[2]).toMatchObject({ cursor: "cursor-1" });
    expect(await screen.findByText("An older answer")).toBeTruthy();
  });

  it("shows an explicit placeholder when an Ally appearance is unsupported", async () => {
    const unsupported = {
      ...ally,
      appearance: { catalogVersion: "v9", key: "ghosty:fd304f" },
    };
    renderHome([unsupported], unsupported.id);

    expect((await screen.findAllByTestId("ally-appearance-unavailable"))).toHaveLength(2);
  });

  it("reuses an exact failed send key but rotates it after any draft edit", async () => {
    const sendMessage = vi.fn()
      .mockRejectedValueOnce(new Error("temporary send failure"))
      .mockRejectedValueOnce(new Error("temporary send failure"))
      .mockResolvedValueOnce({
        conversationId: "00000000-0000-4000-8000-000000000005",
        message: {
          id: "00000000-0000-4000-8000-000000000007",
          sender: "user" as const,
          content: "Hello again",
          sequence: 2,
          status: "queued" as const,
          createdAt: "2026-08-20T16:01:00Z",
        },
        execution: null,
        replayed: false,
      });
    renderHome([ally], ally.id, { sendMessage });

    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "Hello again" } });
    await clickSendMessage();
    await screen.findByRole("alert");
    const firstKey = sendMessage.mock.calls[0]?.[3];

    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[3]).toBe(firstKey);

    fireEvent.change(input, { target: { value: "Hello again!" } });
    fireEvent.change(input, { target: { value: "Hello again" } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(3));
    expect(sendMessage.mock.calls[2]?.[3]).not.toBe(firstKey);
  });

  it("clears the submitted draft after a successful send, including trailing whitespace", async () => {
    const sendMessage = vi.fn(async () => ({
      conversationId: "00000000-0000-4000-8000-000000000005",
      message: {
        id: "00000000-0000-4000-8000-000000000007",
        sender: "user" as const,
        content: "Hello again",
        sequence: 2,
        status: "queued" as const,
        createdAt: "2026-08-20T16:01:00Z",
      },
      execution: null,
      replayed: false,
    }));
    renderHome([ally], ally.id, { sendMessage });

    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "Hello again   " } });
    await clickSendMessage();

    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    await waitFor(() => expect((input as HTMLTextAreaElement).value).toBe(""));
  });

  it("holds later messages in the frontend queue until the active turn finishes", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    let finishActiveTurn: ((snapshot: unknown) => void) | undefined;
    let activeMessageStatus: "queued" | "completed" = "queued";
    const getActivities = vi.fn(() => new Promise((resolve) => {
      finishActiveTurn = resolve;
    }));
    const sendMessage = vi.fn(async () => ({
      conversationId,
      message: {
        ...activeMessage,
        id: "00000000-0000-4000-8000-000000000008",
        content: "Second question",
        sequence: 3,
      },
      execution: null,
      replayed: false,
    }));
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [{ ...activeMessage, status: activeMessageStatus }],
        nextCursor: null,
      })),
      getActivities,
      sendMessage,
    });

    expect(await screen.findByText("First question", { selector: "article p" })).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Second question" } });
    await clickSendMessage();

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    expect(queue.textContent).toBe("Second question");
    expect(sendMessage).not.toHaveBeenCalled();
    expect(screen.queryByText("Queued")).toBeNull();
    expect(screen.queryByText("Working")).toBeNull();
    expect(screen.getByText("Thinking")).toBeTruthy();
    expect(screen.queryByText("Push")).toBeNull();

    await act(async () => {
      activeMessageStatus = "completed";
      finishActiveTurn?.({
        conversationId,
        activities: [],
        state: "completed",
        lastContiguousSequence: 0,
      });
    });

    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    expect(sendMessage.mock.calls[0]?.slice(0, 3)).toEqual(["workspace", conversationId, "Second question"]);
    await waitFor(() => expect(screen.queryByRole("list", { name: "Queued messages" })).toBeNull());
  });

  it("keeps a failed queued message at the head and reuses its key on retry", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    let finishActiveTurn: ((snapshot: unknown) => void) | undefined;
    let activeMessageStatus: "queued" | "completed" = "queued";
    const getActivities = vi.fn(() => new Promise((resolve) => {
      finishActiveTurn = resolve;
    }));
    const sendMessage = vi.fn()
      .mockRejectedValueOnce(new Error("ambiguous queued send failure"))
      .mockResolvedValue({
        conversationId,
        message: {
          ...activeMessage,
          id: "00000000-0000-4000-8000-000000000008",
          content: "Second question",
          sequence: 3,
        },
        execution: null,
        replayed: true,
      });
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [{ ...activeMessage, status: activeMessageStatus }],
        nextCursor: null,
      })),
      getActivities,
      sendMessage,
    });

    expect(await screen.findByText("First question", { selector: "article p" })).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Second question" } });
    await clickSendMessage();

    await act(async () => {
      activeMessageStatus = "completed";
      finishActiveTurn?.({
        conversationId,
        activities: [],
        state: "completed",
        lastContiguousSequence: 0,
      });
    });

    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    const queuedIntentKey = sendMessage.mock.calls[0]?.[3];
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(input.value).toBe("");
    expect(screen.getByRole("list", { name: "Queued messages" }).textContent).toContain("Second question");

    fireEvent.change(input, { target: { value: "Third question" } });
    await clickSendMessage();
    expect(sendMessage).toHaveBeenCalledOnce();
    expect(screen.getAllByRole("listitem").map((item) => item.querySelector("span")?.textContent))
      .toEqual(["Second question", "Third question"]);

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[3]).toBe(queuedIntentKey);
    expect(sendMessage.mock.calls[1]?.[2]).toBe("Second question");
    expect(screen.getByRole("list", { name: "Queued messages" }).textContent).toContain("Third question");
  });

  it("keeps a failed dispatch durable after unmount", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    let finishActiveTurn: ((snapshot: unknown) => void) | undefined;
    let rejectQueuedSend: ((error: Error) => void) | undefined;
    let activeMessageStatus: "queued" | "completed" = "queued";
    const overrides = {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [{ ...activeMessage, status: activeMessageStatus }],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise((resolve) => { finishActiveTurn = resolve; })),
      sendMessage: vi.fn(() => new Promise((_, reject) => { rejectQueuedSend = reject; })),
    };
    renderHome([ally], ally.id, overrides);

    await screen.findByText("First question", { selector: "article p" });
    await waitFor(() => expect(overrides.getActivities).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Keep this if sending fails" } });
    await clickSendMessage();
    await act(async () => {
      activeMessageStatus = "completed";
      finishActiveTurn?.({ conversationId, activities: [], state: "completed", lastContiguousSequence: 0 });
    });
    await waitFor(() => expect(overrides.sendMessage).toHaveBeenCalledOnce());
    expect(screen.queryByRole("button", { name: "Remove queued message" })).toBeNull();

    cleanup();
    await act(async () => rejectQueuedSend?.(new Error("ambiguous failure")));
    renderHome([ally], ally.id, overrides);

    expect(await screen.findByText("Keep this if sending fails")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(overrides.sendMessage).toHaveBeenCalledOnce();
  });

  it("merges cross-tab queue additions and does not resurrect removals", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "in_progress" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
    });

    await screen.findByText("First question", { selector: "article p" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "From this tab" } });
    await clickSendMessage();
    const storageKey = `allies:v1:queued-messages:workspace:${ally.id}`;
    const remoteQueue = [{
      id: "queued-remote",
      content: "From another tab",
      intentKey: "message-remote",
      queuedAt: Date.now() + 1,
      state: "queued",
    }];
    window.dispatchEvent(new StorageEvent("storage", {
      key: storageKey,
      newValue: JSON.stringify(remoteQueue),
      storageArea: window.localStorage,
    }));

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    expect(queue.textContent).toContain("From this tab");
    expect(queue.textContent).toContain("From another tab");
    const staleSnapshot = window.localStorage.getItem(storageKey);

    const localItem = screen.getByText("From this tab").closest("li");
    fireEvent.click(localItem!.querySelector('button[aria-label="Remove queued message"]')!);
    const remoteTombstoneKey = `${storageKey}:removed:${encodeURIComponent("queued-remote")}`;
    window.localStorage.setItem(remoteTombstoneKey, String(Date.now()));
    window.dispatchEvent(new StorageEvent("storage", {
      key: remoteTombstoneKey,
      newValue: window.localStorage.getItem(remoteTombstoneKey),
      storageArea: window.localStorage,
    }));
    window.dispatchEvent(new StorageEvent("storage", {
      key: storageKey,
      newValue: staleSnapshot,
      storageArea: window.localStorage,
    }));
    await waitFor(() => {
      expect(screen.queryByText("From this tab")).toBeNull();
      expect(screen.queryByText("From another tab")).toBeNull();
    });

    window.localStorage.setItem(storageKey, staleSnapshot!);
    cleanup();
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
    });
    await screen.findByText("First question", { selector: "article p" });
    expect(screen.queryByText("From this tab")).toBeNull();
    expect(screen.queryByText("From another tab")).toBeNull();
  });

  it("lets the user remove a frontend-queued message", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "in_progress" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const sendMessage = vi.fn();
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
      sendMessage,
    });

    expect(await screen.findByText("First question", { selector: "article p" })).toBeTruthy();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Never mind" } });
    await clickSendMessage();
    expect(await screen.findByText("Never mind")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Remove queued message" }));
    expect(screen.queryByText("Never mind")).toBeNull();
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("keeps frontend-queued messages across unmounts", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const overrides = {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
      sendMessage: vi.fn(),
    };
    renderHome([ally], ally.id, overrides);

    expect(await screen.findByText("First question", { selector: "article p" })).toBeTruthy();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep me waiting" } });
    await clickSendMessage();
    expect(await screen.findByText("Keep me waiting")).toBeTruthy();
    await waitFor(() => expect(window.localStorage.length).toBe(1));

    cleanup();
    renderHome([ally], ally.id, overrides);

    expect(await screen.findByText("Keep me waiting")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Queued messages" })).toBeTruthy();
    expect(overrides.sendMessage).not.toHaveBeenCalled();
  });

  it("offers a per-message retry and starts a fresh turn", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const stuckMessage = {
      id: "00000000-0000-4000-8000-000000000020",
      sender: "user" as const,
      content: "Still waiting",
      sequence: 2,
      status: "queued" as const,
      retryable: true,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const retriedMessage = {
      ...stuckMessage,
      id: "00000000-0000-4000-8000-000000000021",
      sequence: 3,
      retryable: false,
    };
    const retryMessage = vi.fn(async () => ({
      conversationId,
      message: retriedMessage,
      execution: null,
      replayed: false,
    }));
    renderHome([ally], ally.id, {
      retryMessage,
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [stuckMessage],
        nextCursor: null,
      })),
    });

    const retry = await screen.findByRole("button", { name: "Retry" });
    fireEvent.click(retry);
    await waitFor(() => expect(retryMessage).toHaveBeenCalledOnce());
    expect(retryMessage.mock.calls[0]?.slice(0, 3)).toEqual([
      "workspace",
      conversationId,
      stuckMessage.id,
    ]);
    expect(await screen.findAllByText("Still waiting")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("refetches after a terminal send without losing history, cursor, or activity", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const olderMessage = {
      id: "00000000-0000-4000-8000-000000000010",
      sender: "assistant" as const,
      content: "An older answer",
      sequence: 0,
      status: "completed" as const,
      createdAt: "2026-08-20T15:00:00Z",
    };
    const acceptedMessage = {
      id: "00000000-0000-4000-8000-000000000011",
      sender: "user" as const,
      content: "A terminal question",
      sequence: 2,
      status: "completed" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const terminalActivitySnapshot = {
      conversationId,
      activities: [{
        id: "00000000-0000-4000-8000-000000000012",
        messageId: acceptedMessage.id,
        sequence: 1,
        conversationTurnOrdinal: acceptedMessage.sequence,
        kind: "assistant_delta" as const,
        text: "Terminal replay answer",
        state: "completed" as const,
        createdAt: "2026-08-20T16:01:01Z",
      }],
      state: "completed" as const,
      lastContiguousSequence: 1,
    };
    const getAllyConversation = vi.fn()
      .mockResolvedValueOnce({
        id: conversationId,
        allyId: ally.id,
        messages: [{
          id: "00000000-0000-4000-8000-000000000006",
          sender: "assistant" as const,
          content: "What should we work on first?",
          sequence: 1,
          status: "completed" as const,
          createdAt: "2026-08-20T16:00:00Z",
        }],
        nextCursor: "cursor-1",
      })
      .mockResolvedValueOnce({
        id: conversationId,
        allyId: ally.id,
        messages: [acceptedMessage],
        nextCursor: "cursor-2",
      });
    const getConversation = vi.fn(async () => ({
      id: conversationId,
      allyId: ally.id,
      messages: [olderMessage],
      nextCursor: null,
    }));
    const sendMessage = vi.fn(async () => ({
      conversationId,
      message: acceptedMessage,
      execution: null,
      replayed: false,
    }));
    let resolveActivitySnapshot: ((snapshot: typeof terminalActivitySnapshot) => void) | undefined;
    let activitySignal: AbortSignal | undefined;
    const getActivities = vi.fn()
      .mockResolvedValueOnce({
        conversationId,
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      })
      .mockImplementationOnce((_workspaceId, _conversationId, _limit, signal: AbortSignal) => {
        activitySignal = signal;
        return new Promise((resolve) => { resolveActivitySnapshot = resolve; });
      });
    renderHome([ally], ally.id, { getAllyConversation, getConversation, getActivities, sendMessage });

    fireEvent.click(await screen.findByRole("button", { name: "Earlier messages" }));
    expect(await screen.findByText("An older answer")).toBeTruthy();

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "A terminal question" } });
    await clickSendMessage();

    await waitFor(() => expect(
      getAllyConversation.mock.calls.filter((call) => call[2]?.limit === 50),
    ).toHaveLength(2));
    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(2));
    expect(activitySignal?.aborted).toBe(false);
    resolveActivitySnapshot?.(terminalActivitySnapshot);
    expect(screen.getByText("An older answer")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Earlier messages" })).toBeNull();
    expect(await screen.findByText("Terminal replay answer")).toBeTruthy();
  });

  it("preserves the previous latest conversation window when polling invalidates it", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const previousLatestMessage = {
      id: "00000000-0000-4000-8000-000000000013",
      sender: "assistant" as const,
      content: "Previous latest answer",
      sequence: 1,
      status: "completed" as const,
      createdAt: "2026-08-20T16:00:00Z",
    };
    const acceptedMessage = {
      id: "00000000-0000-4000-8000-000000000014",
      sender: "user" as const,
      content: "A queued question",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    let messageAccepted = false;
    const getAllyConversation = vi.fn(async () => (
      messageAccepted
        ? {
          conversationId,
          id: conversationId,
          allyId: ally.id,
          messages: [acceptedMessage],
          nextCursor: null,
        }
        : {
          conversationId,
          id: conversationId,
          allyId: ally.id,
          messages: [previousLatestMessage],
          nextCursor: "cursor-1",
        }
    ));
    const getActivities = vi.fn()
      .mockResolvedValueOnce({
        conversationId,
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      })
      .mockResolvedValue({
        conversationId,
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      });
    const sendMessage = vi.fn(async () => {
      messageAccepted = true;
      return {
        conversationId,
        message: acceptedMessage,
        execution: null,
        replayed: false,
      };
    });
    renderHome([ally], ally.id, { getAllyConversation, getActivities, sendMessage });

    expect((await screen.findAllByText("Previous latest answer")).length).toBeGreaterThan(0);
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: acceptedMessage.content } });
    await clickSendMessage();

    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(2), { timeout: 2_000 });
    await waitFor(() => expect(getAllyConversation).toHaveBeenCalled());
    expect(screen.getAllByText("Previous latest answer").length).toBeGreaterThan(0);
    expect(screen.getByText("Thinking")).toBeTruthy();
  });

  it("shows pending activity text when a terminal snapshot has a sequence gap", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [{
          id: "00000000-0000-4000-8000-000000000015",
          sender: "user" as const,
          content: "A question with a partial answer",
          sequence: 2,
          status: "completed" as const,
          createdAt: "2026-08-20T16:01:00Z",
        }],
        nextCursor: null,
      })),
      getActivities: vi.fn(async () => ({
        conversationId,
        activities: [
          {
            id: "00000000-0000-4000-8000-000000000016",
            messageId: "00000000-0000-4000-8000-000000000015",
            sequence: 1,
            conversationTurnOrdinal: 2,
            kind: "assistant_delta" as const,
            text: "Available answer",
            state: "completed" as const,
            createdAt: "2026-08-20T16:01:01Z",
          },
          {
            id: "00000000-0000-4000-8000-000000000017",
            messageId: "00000000-0000-4000-8000-000000000015",
            sequence: 3,
            conversationTurnOrdinal: 2,
            kind: "assistant_delta" as const,
            text: "Pending answer text",
            state: "completed" as const,
            createdAt: "2026-08-20T16:01:02Z",
          },
        ],
        state: "completed" as const,
        lastContiguousSequence: 3,
      })),
    });

    expect(await screen.findByText("Available answer")).toBeTruthy();
    expect(await screen.findByText("Pending answer text")).toBeTruthy();
    expect(await screen.findByText("Some response text arrived out of order.")).toBeTruthy();
  });

  it("aborts an in-flight activity request when the thread unmounts", async () => {
    let resolveActivity: ((value: unknown) => void) | undefined;
    let activitySignal: AbortSignal | undefined;
    const getActivities = vi.fn((
      _workspaceId: string,
      _conversationId: string,
      _limit: number,
      signal?: AbortSignal,
    ) => {
      activitySignal = signal;
      return new Promise((resolve) => {
        resolveActivity = resolve;
      });
    });
    renderHome([ally], ally.id, { getActivities });

    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    cleanup();
    expect(activitySignal?.aborted).toBe(true);

    resolveActivity?.({
      conversationId: "00000000-0000-4000-8000-000000000005",
      activities: [],
      state: "completed",
      lastContiguousSequence: 0,
    });
    await act(async () => undefined);
  });

  it("surfaces activity history failure and retries terminal conversations", async () => {
    const getActivities = vi.fn()
      .mockRejectedValueOnce(new Error("temporary activity failure"))
      .mockResolvedValueOnce({
        conversationId: "00000000-0000-4000-8000-000000000005",
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      });
    renderHome([ally], ally.id, { getActivities });

    const error = await screen.findByText("We couldn't check the latest response status.");
    expect(error).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));

    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText("We couldn't check the latest response status.")).toBeNull());
  });

  it("interleaves each projected Ally reply with its user turn", async () => {
    const messages = [
      {
        id: "00000000-0000-4000-8000-000000000006",
        sender: "assistant" as const,
        content: "What should we work on first?",
        sequence: 1,
        status: "completed" as const,
        createdAt: "2026-08-20T16:00:00Z",
      },
      {
        id: "00000000-0000-4000-8000-000000000007",
        sender: "user" as const,
        content: "First question",
        sequence: 3,
        status: "completed" as const,
        createdAt: "2026-08-20T16:01:00Z",
      },
      {
        id: "00000000-0000-4000-8000-000000000008",
        sender: "user" as const,
        content: "Second question",
        sequence: 4,
        status: "completed" as const,
        createdAt: "2026-08-20T16:02:00Z",
      },
    ];
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: "00000000-0000-4000-8000-000000000005",
        allyId: ally.id,
        messages,
        nextCursor: null,
      })),
      getActivities: vi.fn(async () => ({
        conversationId: "00000000-0000-4000-8000-000000000005",
        activities: [
          {
            id: "00000000-0000-4000-8000-000000000011",
            messageId: messages[1]!.id,
            sequence: 1,
            conversationTurnOrdinal: 3,
            kind: "assistant_delta" as const,
            text: "First answer",
            state: "completed" as const,
            createdAt: "2026-08-20T16:01:01Z",
          },
          {
            id: "00000000-0000-4000-8000-000000000012",
            messageId: messages[2]!.id,
            sequence: 2,
            conversationTurnOrdinal: 4,
            kind: "assistant_delta" as const,
            text: "Second answer",
            state: "completed" as const,
            createdAt: "2026-08-20T16:02:01Z",
          },
        ],
        state: "completed" as const,
        lastContiguousSequence: 2,
      })),
    });

    const firstQuestion = await screen.findByText("First question");
    const firstAnswer = await screen.findByText("First answer");
    const secondQuestion = (await screen.findAllByText("Second question")).find((node) => node.closest("article"));
    if (!secondQuestion) throw new Error("Expected the second question to render inside a message article");
    const secondAnswer = await screen.findByText("Second answer");
    expect(firstQuestion.compareDocumentPosition(firstAnswer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(firstAnswer.compareDocumentPosition(secondQuestion) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(secondQuestion.compareDocumentPosition(secondAnswer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders markdown structure while an Ally response is still streaming", async () => {
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: "00000000-0000-4000-8000-000000000005",
        allyId: ally.id,
        messages: [{
          id: "00000000-0000-4000-8000-000000000007",
          sender: "user" as const,
          content: "Show me the details",
          sequence: 2,
          status: "queued" as const,
          createdAt: "2026-08-20T16:01:00Z",
        }],
        nextCursor: null,
      })),
      getActivities: vi.fn(async () => ({
        conversationId: "00000000-0000-4000-8000-000000000005",
        activities: [{
          id: "00000000-0000-4000-8000-000000000012",
          messageId: "00000000-0000-4000-8000-000000000007",
          sequence: 1,
          conversationTurnOrdinal: 2,
          kind: "assistant_delta" as const,
          text: "## A streamed heading\n\n- The first detail\n- The second detail",
          state: "running" as const,
          createdAt: "2026-08-20T16:01:01Z",
        }],
        state: "running" as const,
        lastContiguousSequence: 1,
      })),
    });

    expect(await screen.findByRole("heading", { name: "A streamed heading", level: 2 })).toBeTruthy();
    expect(screen.queryByText("Thinking")).toBeNull();
    expect(screen.getByRole("list")).toBeTruthy();
    expect(screen.getAllByRole("listitem")[0]?.textContent).toContain("The first detail");
  });

  it("uses explicit review copy when activity needs reconciliation", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [{
          id: "00000000-0000-4000-8000-000000000018",
          sender: "user" as const,
          content: "A question to review",
          sequence: 1,
          status: "completed" as const,
          createdAt: "2026-08-20T16:01:00Z",
        }],
        nextCursor: null,
      })),
      getActivities: vi.fn(async () => ({
        conversationId,
        activities: [{
          id: "00000000-0000-4000-8000-000000000019",
          messageId: "00000000-0000-4000-8000-000000000018",
          sequence: 1,
          conversationTurnOrdinal: 1,
          kind: "activity_completed" as const,
          text: "",
          state: "reconciliation_needed" as const,
          createdAt: "2026-08-20T16:01:01Z",
        }],
        state: "reconciliation_needed" as const,
        lastContiguousSequence: 1,
      })),
    });

    expect(await screen.findByText("This response needs review because some activity arrived out of order.")).toBeTruthy();
    expect(screen.queryByText("This response failed. Try sending your message again.")).toBeNull();
  });

  it("keeps the workspace and draft when an account refetch fails", async () => {
    const getCurrentAccount = vi.fn()
      .mockResolvedValueOnce(account)
      .mockRejectedValueOnce(new Error("temporary account failure"))
      .mockResolvedValue(account);
    const client = renderHome([ally], ally.id, { getCurrentAccount });
    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep this account draft" } });

    await act(async () => {
      await client.queryClient.invalidateQueries({ queryKey: ["account", "current"] });
    });
    await waitFor(() => expect(getCurrentAccount).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("heading", { name: "Mira" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Your current workspace is still shown.");
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Keep this account draft");

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(getCurrentAccount).toHaveBeenCalledTimes(3));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Keep this account draft");
  });

  it("keeps the workspace and draft when an Ally refetch fails", async () => {
    const listAllies = vi.fn()
      .mockResolvedValueOnce([ally])
      .mockRejectedValueOnce(new Error("temporary Ally failure"))
      .mockResolvedValue([ally]);
    const client = renderHome([ally], ally.id, { listAllies });
    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep this Ally draft" } });

    await act(async () => {
      await client.queryClient.invalidateQueries({ queryKey: ["workspaces", "workspace", "allies"] });
    });
    await waitFor(() => expect(listAllies).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("heading", { name: "Mira" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Your current workspace is still shown.");
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Keep this Ally draft");

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(listAllies).toHaveBeenCalledTimes(3));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Keep this Ally draft");
  });

  it("does not expose raw runtime diagnostics for a failed turn", async () => {
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: "00000000-0000-4000-8000-000000000005",
        allyId: ally.id,
        messages: [{
          id: "00000000-0000-4000-8000-000000000007",
          sender: "user" as const,
          content: "Failed question",
          sequence: 3,
          status: "failed" as const,
          createdAt: "2026-08-20T16:01:00Z",
        }],
        nextCursor: null,
      })),
      getActivities: vi.fn(async () => ({
        conversationId: "00000000-0000-4000-8000-000000000005",
        activities: [{
          id: "00000000-0000-4000-8000-000000000011",
          messageId: "00000000-0000-4000-8000-000000000007",
          sequence: 1,
          conversationTurnOrdinal: 3,
          kind: "assistant_delta" as const,
          text: "Provider authentication failed: secret runtime detail",
          state: "failed" as const,
          createdAt: "2026-08-20T16:01:01Z",
        }],
        state: "failed" as const,
        lastContiguousSequence: 1,
      })),
    });

    expect(await screen.findByText("This response failed. Try sending your message again.")).toBeTruthy();
    expect(screen.queryByText(/secret runtime detail/i)).toBeNull();
  });

  it("redirects signed-out visitors with the Home return path", async () => {
    useSessionMock.mockReturnValue({
      state: { status: "signed-out" },
      client: {},
      restore: vi.fn(),
      runCloudOperation: vi.fn(),
    });
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><HomeWorkspace selectedAllyId={null} /></QueryClientProvider>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/sign-in?returnTo=%2Fhome"));
  });
});
