// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HomeWorkspace } from "./home-workspace";

const replace = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
const useSessionMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push }) }));
vi.mock("../../lib/session/session-context", () => ({ useSession: useSessionMock }));
vi.mock("../../components/ally-avatar", () => ({
  ALLY_SHAPES: ["boxy", "ghosty", "rocky", "rolly"],
  AllyAvatar: ({ label }: { label?: string }) => <span data-testid="ally-avatar" aria-label={label} />,
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
const ally = {
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
let desktopViewport = false;
beforeEach(() => {
  vi.clearAllMocks();
  desktopViewport = false;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn(() => ({
      matches: desktopViewport,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

function renderHome(
  allies: typeof ally[],
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

describe("HomeWorkspace", () => {
  it("keeps an empty account honest and offers the first-Ally flow", async () => {
    renderHome([]);
    expect(await screen.findByRole("heading", { name: "Meet your first Ally" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Mira" })).toBeNull();
    expect(screen.getAllByText("Meet your first Ally").length).toBeGreaterThan(1);
    expect(screen.getAllByRole("link", { name: "Meet your first Ally" })[0]?.getAttribute("href")).toBe("/home/new");
  });

  it("hosts Ally creation inside the Home thread", async () => {
    renderHome([], "new");
    expect(await screen.findByText("Shape your Ally")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders a compact real Ally row and its persisted conversation", async () => {
    const client = renderHome([ally], ally.id);
    expect(await screen.findByRole("heading", { name: "Mira" })).toBeTruthy();
    expect(screen.getAllByText("Study partner")).toHaveLength(2);
    expect(await screen.findByText("What should we work on first?")).toBeTruthy();
    await waitFor(() => expect(client.getAllyConversation).toHaveBeenCalled());
    expect(screen.queryByText(/unread/i)).toBeNull();
  });

  it("selects the first newest Ally on desktop Home", async () => {
    desktopViewport = true;
    const newest = { ...ally, id: "00000000-0000-4000-8000-000000000009", name: "Nova" };
    renderHome([newest, ally]);

    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/home/${newest.id}`));
    expect(replace).toHaveBeenCalledOnce();
  });

  it("keeps the Ally list as the mobile Home entry", async () => {
    renderHome([ally]);

    expect(await screen.findByRole("link", { name: /Mira/ })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
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
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByRole("alert");
    const firstKey = sendMessage.mock.calls[0]?.[3];

    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[3]).toBe(firstKey);

    fireEvent.change(input, { target: { value: "Hello again!" } });
    fireEvent.change(input, { target: { value: "Hello again" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(3));
    expect(sendMessage.mock.calls[2]?.[3]).not.toBe(firstKey);
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
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(getAllyConversation).toHaveBeenCalledTimes(2));
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
    const getAllyConversation = vi.fn()
      .mockResolvedValueOnce({
        conversationId,
        id: conversationId,
        allyId: ally.id,
        messages: [previousLatestMessage],
        nextCursor: "cursor-1",
      })
      .mockResolvedValueOnce({
        conversationId,
        id: conversationId,
        allyId: ally.id,
        messages: [acceptedMessage],
        nextCursor: null,
      });
    const getActivities = vi.fn()
      .mockResolvedValueOnce({
        conversationId,
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      })
      .mockResolvedValueOnce({
        conversationId,
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      });
    const sendMessage = vi.fn(async () => ({
      conversationId,
      message: acceptedMessage,
      execution: null,
      replayed: false,
    }));
    renderHome([ally], ally.id, { getAllyConversation, getActivities, sendMessage });

    expect(await screen.findByText("Previous latest answer")).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: acceptedMessage.content } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(2), { timeout: 2_000 });
    await waitFor(() => expect(getAllyConversation).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Previous latest answer")).toBeTruthy();
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
    const secondQuestion = await screen.findByText("Second question");
    const secondAnswer = await screen.findByText("Second answer");
    expect(firstQuestion.compareDocumentPosition(firstAnswer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(firstAnswer.compareDocumentPosition(secondQuestion) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(secondQuestion.compareDocumentPosition(secondAnswer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
