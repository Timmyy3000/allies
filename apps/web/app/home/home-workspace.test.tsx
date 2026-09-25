// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_ACTIVITY_PROJECTION,
  type AllyViewModel,
  type AssistantReplyViewModel,
  type ConversationViewModel,
  type MessageViewModel,
  type RoutineChatItemViewModel,
  type RoutineDiscoveryDetail,
} from "@allies/cloud-client";
import type { RuntimeIntentRequester } from "../../lib/allies/runtime-intent";
import type { ActivityStreamOptions } from "../../lib/allies/activity-stream";
import HomePage from "./page";
import HomeLayout from "./layout";
import AllyHomePage from "./[allyId]/page";
import NewAllyPage from "./new/page";

import {
  ActivityReplayBoundError,
  activityReplayFailure,
  activitySnapshotBytes,
  buildQueuedFrameMessages,
  HomeWorkspace,
  hasOnboardingExchange,
  localTransferQueueStatus,
  mergeAssistantReplies,
  projectConversationActivity,
  queuedAttachmentQueueIds,
  ROUTINE_ACTION_SENT_TIMEOUT_MS,
} from "./home-workspace";

describe("assistant reply reconciliation", () => {
  const reply = (overrides: Partial<AssistantReplyViewModel> = {}): AssistantReplyViewModel => ({
    id: "reply-1",
    sourceMessageId: "message-1",
    conversationTurnOrdinal: 1,
    content: "Long in-progress prefix",
    status: "in_progress",
    hasFullPrefix: true,
    createdAt: "2026-09-18T10:00:00Z",
    updatedAt: "2026-09-18T10:00:01Z",
    ...overrides,
  });

  it.each([
    ["2026-09-18T10:00:00Z", "2026-09-18T10:00:00Z"],
    ["invalid", "invalid"],
    ["2026-09-18T10:00:02Z", "2026-09-18T10:00:01Z"],
    ["2026-09-18T10:00:01Z", "2026-09-18T10:00:02Z"],
  ])("keeps an exact terminal reply over stale progress (%s -> %s)", (progressAt, terminalAt) => {
    const merged = mergeAssistantReplies(
      [reply({ updatedAt: progressAt })],
      [reply({ content: "Final", status: "completed", updatedAt: terminalAt })],
      [reply({ content: "Stale progress after completion", updatedAt: "2026-09-18T10:00:03Z" })],
    );
    expect(merged[0]).toMatchObject({ content: "Final", status: "completed" });
  });

  it("accepts only a strictly newer valid terminal correction", () => {
    expect(mergeAssistantReplies(
      [reply({ content: "First final", status: "completed", updatedAt: "2026-09-18T10:00:02Z" })],
      [reply({ content: "Older correction", status: "completed", updatedAt: "2026-09-18T10:00:01Z" })],
      [reply({ content: "New correction", status: "completed", updatedAt: "2026-09-18T10:00:03Z" })],
    )[0]?.content).toBe("New correction");
  });

  it.each(["completed", "failed", "stopped"] as const)(
    "lets an incomplete %s snapshot end the turn without discarding the trusted prefix",
    (status) => {
      const merged = mergeAssistantReplies(
        [reply({ content: "Trusted full prefix", updatedAt: "2026-09-18T10:00:02Z" })],
        [reply({ content: "suffix only", status, hasFullPrefix: false, updatedAt: "invalid" })],
        [reply({ content: "Stale active text", updatedAt: "2026-09-18T10:00:03Z" })],
      );

      expect(merged[0]).toMatchObject({
        content: "Trusted full prefix",
        hasFullPrefix: true,
        status,
      });
    },
  );

  it.each(["completed", "failed", "stopped"] as const)(
    "accepts a strictly newer incomplete %s correction while retaining trusted terminal text",
    (status) => {
      const merged = mergeAssistantReplies(
        [reply({ content: "Trusted terminal text", status: "completed", updatedAt: "2026-09-18T10:00:02Z" })],
        [reply({ content: "suffix only", status, hasFullPrefix: false, updatedAt: "2026-09-18T10:00:03Z" })],
      );
      expect(merged[0]).toMatchObject({ content: "Trusted terminal text", hasFullPrefix: true, status });
    },
  );

  it.each([
    ["2026-09-18T10:00:02Z", "2026-09-18T10:00:02Z"],
    ["2026-09-18T10:00:02Z", "2026-09-18T10:00:01Z"],
    ["invalid", "2026-09-18T10:00:03Z"],
    ["2026-09-18T10:00:02Z", "invalid"],
  ])("rejects an incomplete terminal correction without strictly newer valid timestamps (%s -> %s)", (currentAt, incomingAt) => {
    const merged = mergeAssistantReplies(
      [reply({ content: "Trusted terminal text", status: "completed", updatedAt: currentAt })],
      [reply({ content: "suffix only", status: "failed", hasFullPrefix: false, updatedAt: incomingAt })],
    );
    expect(merged[0]).toMatchObject({ content: "Trusted terminal text", status: "completed" });
  });
});

const selectedSegment = vi.hoisted(() => vi.fn<() => string | null>(() => null));
const replace = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
const useSessionMock = vi.hoisted(() => vi.fn());
const readActivityStreamMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push }), useSelectedLayoutSegment: selectedSegment }));
vi.mock("next/link", () => ({
  default: ({
    children,
    ...props
  }: React.PropsWithChildren<React.AnchorHTMLAttributes<HTMLAnchorElement>>) => <a {...props}>{children}</a>,
}));
vi.mock("next/image", () => ({
  default: ({ priority, ...props }: React.ImgHTMLAttributes<HTMLImageElement> & { priority?: boolean }) => {
    void priority;
    return createElement("img", { ...props, alt: props.alt ?? "" });
  },
}));
vi.mock("../../lib/allies/activity-stream", () => ({ readActivityStream: readActivityStreamMock }));
vi.mock("../../lib/session/session-context", () => ({ useSession: useSessionMock }));
vi.mock("../../lib/pwa/pwa-install", () => ({
  InstallInvitation: () => <aside data-testid="install-invitation" />,
}));
vi.mock("../../components/ally-avatar", () => ({
  ALLY_SHAPES: ["boxy", "ghosty", "rocky", "rolly"],
  AllyAvatar: ({ label, state }: { label?: string; state?: string }) => <span data-testid="ally-avatar" aria-label={label} data-state={state} />,
}));
vi.mock("../(onboarding)/_components", () => ({ default: () => <div>Shape your Ally</div> }));
vi.mock("../(onboarding)/_store/onboarding-store", () => ({ OnboardingStateProvider: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("../../lib/allies/authenticated-onboarding-flow", () => ({
  AuthenticatedAllyFlowProvider: ({
    onCreated,
    children,
  }: {
    onCreated: (created: AllyViewModel, handoff: { greeting: string; reply: string }) => void;
    children: React.ReactNode;
  }) => (
    <div>
      {children}
      <button
        type="button"
        onClick={() => onCreated({
          id: "00000000-0000-4000-8000-000000000099",
          bindingId: "00000000-0000-4000-8000-000000000098",
          operationId: "00000000-0000-4000-8000-000000000097",
          name: "Nova",
          job: "Study partner",
          personality: "Calm",
          appearance: { catalogVersion: "v1", key: "ghosty:fd304f" },
          provisioningState: "bound",
          retryable: false,
        }, { greeting: "Hello Nova", reply: "Help me study" })}
      >
        Finish create
      </button>
    </div>
  ),
}));

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

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});
beforeEach(() => {
  vi.clearAllMocks();
  readActivityStreamMock.mockReset();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  window.localStorage.clear();
  Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
  stubViewport(false);
});

function stubQueueMessageLocks() {
  Object.defineProperty(navigator, "locks", {
    configurable: true,
    value: { request: (_name: string, _options: unknown, task: () => Promise<unknown>) => task() },
  });
}

function stubViewport(desktop: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: desktop
        ? query.includes("min-width: 1024px")
        : query.includes("max-width: 1023px"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}

function renderHome(
  allies: AllyViewModel[],
  selectedAllyId: string | null = null,
  clientOverrides: Record<string, unknown> = {},
  page?: ReactNode,
) {
  selectedSegment.mockReturnValue(selectedAllyId);
  const client = {
    getCurrentAccount: vi.fn(async () => account),
    listAllies: vi.fn(async () => allies),
    requestAllyDeletion: vi.fn(async (_workspaceId: string, allyId: string) => ({
      allyId,
      operationId: "00000000-0000-4000-8000-000000000020",
      state: "pending" as const,
      retryable: true,
      safeErrorCode: "",
    })),
    getAllyDeletion: vi.fn(async (_workspaceId: string, allyId: string) => ({
      allyId,
      operationId: "00000000-0000-4000-8000-000000000020",
      state: "pending" as const,
      retryable: true,
      safeErrorCode: "",
    })),
    updateAllySettings: vi.fn(async (_workspaceId: string, allyId: string, input: { label: string; showLabel: boolean; settingsRevision: number }) => ({
      ...(allies.find((candidate) => candidate.id === allyId) ?? ally),
      label: input.label,
      showLabel: input.showLabel,
      settingsRevision: input.settingsRevision + 1,
    })),
    getApprovals: vi.fn(async () => []),
    getAllyConversation: vi.fn(async (_workspaceId: string, selectedId: string) => ({
      id: "00000000-0000-4000-8000-000000000005",
      allyId: selectedId,
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
  const view = render(
    <QueryClientProvider client={queryClient}>
      {page !== undefined ? <HomeLayout>{page}</HomeLayout> : <HomeWorkspace selectedAllyId={selectedAllyId} />}
    </QueryClientProvider>,
  );
  return Object.assign(client, { queryClient, view });
}

async function clickSendMessage() {
  const button = screen.getByRole("button", { name: "Send message" }) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  fireEvent.click(button);
}

describe.each([false, true])("public Home pages (desktop=%s)", (desktop) => {
  beforeEach(() => stubViewport(desktop));

  it("shows the animated loader immediately until the initial roster is ready", async () => {
    let resolveAllies!: (value: AllyViewModel[]) => void;
    const getAllies = vi.fn(() => new Promise<AllyViewModel[]>((resolve) => { resolveAllies = resolve; }));
    renderHome([ally], null, { listAllies: getAllies });
    expect(screen.getByRole("status", { name: "Loading your space" })).toBeTruthy();
    expect(screen.queryByText("My allies")).toBeNull();
    expect(screen.queryByText("Events")).toBeNull();
    await waitFor(() => expect(getAllies).toHaveBeenCalled());
    await act(async () => resolveAllies([ally]));
    await waitFor(() => expect(screen.queryByRole("status", { name: "Loading your space" })).toBeNull());
    expect(screen.getByRole("navigation", { name: "Choose an Ally" })).toBeTruthy();
  });

  it("previews the Ally's reply from older history instead of a newer user message", async () => {
    const getAllyConversation = vi.fn(async (_workspace: string, _ally: string, options?: { cursor?: string }) => ({
      id: "conversation", allyId: ally.id, assistantReplies: options?.cursor ? [] : [{ id: "partial", sourceMessageId: "question", conversationTurnOrdinal: 2, content: "suffix only", status: "completed", hasFullPrefix: false, createdAt: "2026-09-10T12:00:00Z", updatedAt: "2026-09-10T12:00:00Z" }], routineItems: [],
      messages: options?.cursor ? [{ id: "answer", sender: "assistant", content: "I have your schedule ready", sequence: 1, status: "completed", createdAt: "2026-09-10T10:00:00Z", retryable: false }]
        : [{ id: "question", sender: "user", content: "Thanks for that", sequence: 2, status: "completed", createdAt: "2026-09-10T11:00:00Z", retryable: false }],
      nextCursor: options?.cursor ? null : "older",
    }));
    renderHome([ally], null, { getAllyConversation });
    const row = await screen.findByRole("link", { name: /I have your schedule ready/ });
    expect(row.textContent).not.toContain("Thanks for that");
    expect(getAllyConversation).toHaveBeenCalledTimes(2);
    expect(getAllyConversation.mock.calls[1][2]?.cursor).toBe("older");
  });

  it("stops older preview pages when deletion begins during a pending history request", async () => {
    const page: ConversationViewModel = {
      id: "conversation", allyId: ally.id, messages: [], assistantReplies: [], routineItems: [], nextCursor: "older",
    };
    let resolveOlder!: (value: ConversationViewModel) => void;
    const older = new Promise<ConversationViewModel>((resolve) => { resolveOlder = resolve; });
    const getAllyConversation = vi.fn(async (_workspace: string, _ally: string, options?: { cursor?: string }) => (
      options?.cursor ? older : page
    ));
    const client = renderHome([ally], null, { getAllyConversation });
    await waitFor(() => expect(getAllyConversation).toHaveBeenCalledTimes(2));
    await act(async () => {
      client.queryClient.setQueryData(["workspaces", account.workspace.id, "allies"], [{ ...ally, deletionState: "pending" }]);
    });
    await waitFor(() => expect(screen.queryByRole("link", { name: /Mira/ })).toBeNull());
    await act(async () => { resolveOlder({ ...page, nextCursor: "even-older" }); });
    expect(getAllyConversation).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("link", { name: /Mira/ })).toBeNull();
    expect(client.queryClient.getQueryData(["workspaces", account.workspace.id, "allies", ally.id, "conversation", "preview"])).toBeUndefined();
  });

  it("loads the real roster and opens the created Ally through its actual page", async () => {
    const client = renderHome([ally], null, {
      getAllyConversation: vi.fn(async (_workspaceId: string, selectedId: string) => ({
        id: "00000000-0000-4000-8000-000000000005",
        allyId: selectedId,
        messages: selectedId === "00000000-0000-4000-8000-000000000099" ? [
          { id: "greeting", sender: "assistant", content: "Hello Nova", sequence: 1, status: "completed", createdAt: "2026-08-20T16:00:00Z" },
          { id: "reply", sender: "user", content: "Help me study", sequence: 2, status: "queued", createdAt: "2026-08-20T16:00:01Z" },
        ] : [],
        nextCursor: null,
      })),
    }, <HomePage />);
    expect(screen.queryByTestId("install-invitation")).toBeNull();
    const row = await screen.findByRole("link", { name: /Mira(?! settings)/ });
    expect(screen.getByTestId("install-invitation")).toBeTruthy();
    expect(row.getAttribute("href")).toBe(`/home/${ally.id}`);
    expect(client.listAllies).toHaveBeenCalledWith(account.workspace.id, expect.any(AbortSignal));
    expect(screen.queryByText("Sally Morano")).toBeNull();
    expect(screen.queryByText("Sam Dickson")).toBeNull();
    expect(screen.queryByText("SD")).toBeNull();
    expect(screen.getByRole("link", { name: account.displayName }).getAttribute("href")).toBe("/account");

    const chefButton = screen.getByRole("button", { name: "Recipes" }) as HTMLButtonElement;
    expect(chefButton.disabled).toBe(false);
    fireEvent.click(chefButton);
    expect(screen.getByText("Recipes are coming soon.")).toBeTruthy();
    expect(screen.queryByRole("dialog", { name: "Make your Ally" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Make an Ally" }));
    expect(await screen.findByRole("dialog", { name: "Make your Ally" })).toBeTruthy();
    expect(screen.queryByTestId("install-invitation")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Finish create" }));
    const createdId = "00000000-0000-4000-8000-000000000099";
    expect(replace).toHaveBeenCalledWith(`/home/${createdId}`);
    selectedSegment.mockReturnValue(createdId);
    const page = <AllyHomePage />;
    client.view.rerender(<QueryClientProvider client={client.queryClient}><HomeLayout>{page}</HomeLayout></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "Nova" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Make your Ally" })).toBeNull());
    expect(screen.queryByTestId("install-invitation")).toBeNull();
    await waitFor(() => expect(client.getAllyConversation).toHaveBeenCalledWith(
      account.workspace.id, createdId, expect.objectContaining({ limit: 50 }),
    ));
  });

  it("loads persisted history and sends through Cloud from the real Ally page", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const message = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "Route integration check",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    let sent = false;
    const sendMessage = vi.fn(async () => {
      sent = true;
      return { message, execution: { id: "execution", state: "queued" } };
    });
    const getActivities = vi.fn(async () => ({
      conversationId,
      activities: sent ? [{
        id: "00000000-0000-4000-8000-000000000009",
        messageId: message.id,
        sequence: 1,
        conversationTurnOrdinal: 2,
        kind: "assistant_delta" as const,
        text: "Response from the Cloud activity feed.",
        state: "completed" as const,
        createdAt: "2026-08-20T16:01:01Z",
      }] : [],
      state: "completed" as const,
      lastContiguousSequence: sent ? 1 : 0,
    }));
    const page = <AllyHomePage />;
    renderHome([ally], ally.id, { sendMessage, getActivities }, page);
    expect(await screen.findByRole("heading", { name: ally.name })).toBeTruthy();
    expect((await screen.findAllByText("What should we work on first?")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: message.content } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledWith(
      account.workspace.id, conversationId, message.content, expect.any(String), undefined, Intl.DateTimeFormat().resolvedOptions().timeZone, undefined,
    ));
    expect(await screen.findByText("Response from the Cloud activity feed.")).toBeTruthy();
    expect(screen.queryByText(/I will keep that with the rest of today/)).toBeNull();
  });

  it("keeps unknown Ally IDs honest", async () => {
    const page = <AllyHomePage />;
    renderHome([ally], "not-owned", {}, page);
    expect(await screen.findByText("That Ally isn't in this Workspace")).toBeTruthy();
    expect(screen.queryByText("Sally Morano")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("opens authenticated creation through /home/new", async () => {
    renderHome([], "new", {}, <NewAllyPage />);
    expect(await screen.findByRole("dialog", { name: "Make your Ally" })).toBeTruthy();
    expect(screen.getByText("Shape your Ally")).toBeTruthy();
  });

  it.each([false, true])("allows a tenth Ally (desktop: %s)", async (desktop) => {
    stubViewport(desktop);
    renderHome(Array.from({ length: 9 }, (_, index) => ({ ...ally, id: `ally-${index}` })));
    const button = await screen.findByRole("button", { name: "Make an Ally" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText("9 / 10 Allies")).toBeTruthy();
    fireEvent.click(button);
    expect(screen.getByText("Shape your Ally")).toBeTruthy();
  });

  it.each([10, 11])("blocks creation at %s Allies, including the direct route", async (count) => {
    renderHome(Array.from({ length: count }, (_, index) => ({ ...ally, id: `ally-${index}` })), "new");
    expect(await screen.findByRole("heading", { name: "Ally limit reached" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Make an Ally" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText("Shape your Ally")).toBeNull();
    expect(screen.queryByText("Finish create")).toBeNull();
    expect(screen.getAllByRole("link", { name: /Mira/ })).toHaveLength(count);
  });

  it.each(["home", "ally", "new"])("redirects signed-out visitors from %s without demo content", async (route) => {
    useSessionMock.mockReturnValue({
      state: { status: "signed-out" },
      client: {},
      restore: vi.fn(),
      runCloudOperation: vi.fn(),
    });
    const page = route === "home" ? <HomePage /> : route === "new" ? <NewAllyPage />
      : <AllyHomePage />;
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    selectedSegment.mockReturnValue(route === "home" ? null : route === "new" ? "new" : ally.id);
    render(<QueryClientProvider client={queryClient}><HomeLayout>{page}</HomeLayout></QueryClientProvider>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(screen.queryByText("SD")).toBeNull();
    expect(screen.queryByRole("button", { name: "Make an Ally" })).toBeNull();
    expect(screen.queryByText("Sally Morano")).toBeNull();
  });
});

describe("HomeWorkspace", () => {
  it("collapses a completed multi-file message into one expandable bundle", async () => {
    const files = [
      { id: "10000000-0000-4000-8000-000000000001", name: "one.pdf", size: 300_000, state: "retained" as const },
      { id: "10000000-0000-4000-8000-000000000002", name: "two.pdf", size: 400_000, state: "retained" as const },
      { id: "10000000-0000-4000-8000-000000000003", name: "three.pdf", size: 500_000, state: "retained" as const },
    ];
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: "00000000-0000-4000-8000-000000000005",
        allyId: ally.id,
        messages: [{
          id: "00000000-0000-4000-8000-000000000006",
          sender: "user" as const,
          content: "Review these",
          sequence: 1,
          status: "completed" as const,
          createdAt: "2026-08-20T16:00:00Z",
          preparation: "ready" as const,
          revision: 1,
          files,
        }],
        nextCursor: null,
      })),
    });

    const label = await screen.findByText("Attachments");
    const toggle = label.closest("button") as HTMLButtonElement;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.textContent).toContain("3 files · 1.1 MB");
    expect(screen.queryByText("one.pdf")).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("one.pdf")).toBeTruthy();
  });

  it("cancels the transfer before deleting when removing a cloud file message from the queue pill", async () => {
    const fileId = "10000000-0000-4000-8000-000000000001";
    const messageId = "00000000-0000-4000-8000-000000000006";
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const queuedFileMessage = {
      id: messageId,
      sender: "user" as const,
      content: "See this",
      sequence: 1,
      status: "queued" as const,
      queueState: "unclaimed" as const,
      createdAt: "2026-08-20T16:00:00Z",
      preparation: "ready" as const,
      revision: 1,
      files: [{ id: fileId, name: "notes.txt", size: 5, state: "ready" as const }],
    };
    const cancelFiles = vi.fn(async () => ({
      message: { id: messageId, status: "queued", preparation: "cancelled", revision: 2 },
      draft: {
        id: messageId,
        content: "Restored text",
        files: [{ id: fileId, name: "notes.txt", state: "retained" as const }],
      },
    }));
    const deleteQueuedMessage = vi.fn(async () => ({
      ...queuedFileMessage,
      content: "",
      status: "stopped" as const,
      queueState: null,
      deletedAt: "2026-08-20T16:01:00Z",
    }));
    renderHome([ally], ally.id, {
      files: { cancel: cancelFiles },
      deleteQueuedMessage,
      getAllyConversation: vi.fn(async () => deleteQueuedMessage.mock.calls.length
        ? { id: conversationId, allyId: ally.id, messages: [], nextCursor: null }
        : {
          id: conversationId,
          allyId: ally.id,
          messages: [queuedFileMessage],
          queue: [queuedFileMessage],
          nextCursor: null,
        }),
    });

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    expect(queue.textContent).toContain("See this");
    fireEvent.click(screen.getByRole("button", { name: "Remove queued message: See this" }));
    await waitFor(() => expect(cancelFiles).toHaveBeenCalled());
    await waitFor(() => expect(deleteQueuedMessage).toHaveBeenCalled());
    expect(cancelFiles.mock.invocationCallOrder[0]).toBeLessThan(deleteQueuedMessage.mock.invocationCallOrder[0]);
    await waitFor(() => expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Restored text"));
    await waitFor(() => expect(screen.queryByRole("list", { name: "Queued messages" })).toBeNull());
  });

  it("cancels once and deletes when using in-bubble Cancel on a failed cloud file message", async () => {
    const fileId = "10000000-0000-4000-8000-000000000001";
    const messageId = "00000000-0000-4000-8000-000000000006";
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const failedFileMessage = {
      id: messageId,
      sender: "user" as const,
      content: "See this",
      sequence: 1,
      status: "queued" as const,
      queueState: "unclaimed" as const,
      createdAt: "2026-08-20T16:00:00Z",
      preparation: "failed" as const,
      revision: 1,
      files: [{ id: fileId, name: "notes.txt", size: 5, state: "failed" as const }],
    };
    const cancelFiles = vi.fn(async () => ({
      message: { id: messageId, status: "queued", preparation: "cancelled", revision: 2 },
      draft: {
        id: messageId,
        content: "Restored text",
        files: [{ id: fileId, name: "notes.txt", state: "retained" as const }],
      },
    }));
    const deleteQueuedMessage = vi.fn(async () => ({
      ...failedFileMessage,
      content: "",
      status: "stopped" as const,
      queueState: null,
      deletedAt: "2026-08-20T16:01:00Z",
    }));
    renderHome([ally], ally.id, {
      files: { cancel: cancelFiles },
      deleteQueuedMessage,
      getAllyConversation: vi.fn(async () => deleteQueuedMessage.mock.calls.length
        ? { id: conversationId, allyId: ally.id, messages: [], nextCursor: null }
        : {
          id: conversationId,
          allyId: ally.id,
          messages: [failedFileMessage],
          queue: [failedFileMessage],
          nextCursor: null,
        }),
    });

    await screen.findByText("See this", { selector: "article p" });
    expect(screen.queryByRole("list", { name: "Queued messages" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(deleteQueuedMessage).toHaveBeenCalled());
    expect(cancelFiles).toHaveBeenCalledTimes(1);
    expect(cancelFiles.mock.invocationCallOrder[0]).toBeLessThan(deleteQueuedMessage.mock.invocationCallOrder[0]);
    await waitFor(() => expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Restored text"));
    await waitFor(() => expect(screen.queryByText("See this")).toBeNull());
  });

  it("leaves the draft untouched when deleting a cloud file message fails after cancel", async () => {
    const fileId = "10000000-0000-4000-8000-000000000001";
    const messageId = "00000000-0000-4000-8000-000000000006";
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const queuedFileMessage = {
      id: messageId,
      sender: "user" as const,
      content: "See this",
      sequence: 1,
      status: "queued" as const,
      queueState: "unclaimed" as const,
      createdAt: "2026-08-20T16:00:00Z",
      preparation: "ready" as const,
      revision: 1,
      files: [{ id: fileId, name: "notes.txt", size: 5, state: "ready" as const }],
    };
    const cancelFiles = vi.fn(async () => ({
      message: { id: messageId, status: "queued", preparation: "cancelled", revision: 2 },
      draft: {
        id: messageId,
        content: "Restored text",
        files: [{ id: fileId, name: "notes.txt", state: "retained" as const }],
      },
    }));
    const deleteQueuedMessage = vi.fn(async () => {
      throw { kind: "network" };
    });
    renderHome([ally], ally.id, {
      files: { cancel: cancelFiles },
      deleteQueuedMessage,
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [queuedFileMessage],
        queue: [queuedFileMessage],
        nextCursor: null,
      })),
    });

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    expect(queue.textContent).toContain("See this");
    fireEvent.click(screen.getByRole("button", { name: "Remove queued message: See this" }));
    await waitFor(() => expect(deleteQueuedMessage).toHaveBeenCalled());
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("");
    expect(screen.getByRole("list", { name: "Queued messages" }).textContent).toContain("See this");
  });

  it("falls back to the original file when the optimized preview is unavailable", async () => {
    const file = {
      id: "10000000-0000-4000-8000-000000000001",
      name: "Deutsch_üben_Wortschatz_und_Grammatik_A2_Verben_mit_Präpositionen_OCR.pdf",
      size: 300_000,
      state: "retained" as const,
    };
    const metadata = vi.fn(async () => ({
      ...file,
      type: "application/pdf",
      preview_kind: "pdf" as const,
      open_path: `/files/${file.id}`,
    }));
    const content = vi.fn(async (_workspace: string, _ally: string, _file: string, preview: boolean) => {
      if (preview) throw new Error("optimized preview unavailable");
      return new Blob(["pdf"], { type: "application/pdf" });
    });
    const createObjectUrlDescriptor = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const revokeObjectUrlDescriptor = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:original-file") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    try {
      renderHome([ally], ally.id, {
        files: { metadata, content },
        getAllyConversation: vi.fn(async () => ({
          id: "00000000-0000-4000-8000-000000000005",
          allyId: ally.id,
          messages: [{
            id: "00000000-0000-4000-8000-000000000006",
            sender: "user" as const,
            content: "See this",
            sequence: 1,
            status: "completed" as const,
            createdAt: "2026-08-20T16:00:00Z",
            preparation: "ready" as const,
            revision: 1,
            files: [file],
          }],
          nextCursor: null,
        })),
      });

      const displayedName = await screen.findByTitle(file.name);
      fireEvent.click(displayedName.closest("button") as HTMLButtonElement);

      await waitFor(() => expect(content).toHaveBeenCalledTimes(2));
      expect(content.mock.calls.map((call) => call[3])).toEqual([true, false]);
      await waitFor(() => expect(document.querySelector(`iframe[title="${file.name}"]`)).toBeTruthy());
      expect(screen.queryByText(/couldn’t open the preview/i)).toBeNull();
    } finally {
      cleanup();
      if (createObjectUrlDescriptor) Object.defineProperty(URL, "createObjectURL", createObjectUrlDescriptor);
      else Reflect.deleteProperty(URL, "createObjectURL");
      if (revokeObjectUrlDescriptor) Object.defineProperty(URL, "revokeObjectURL", revokeObjectUrlDescriptor);
      else Reflect.deleteProperty(URL, "revokeObjectURL");
    }
  });

  it("requires the exact onboarding greeting and reply before releasing the handoff", () => {
    const messages = [
      { id: "greeting", sender: "assistant", sequence: 1, content: "Hello Nova" },
      { id: "reply", sender: "user", sequence: 2, content: "Help me study" },
    ] as MessageViewModel[];

    expect(hasOnboardingExchange(messages, "Hello Nova", "Help me study")).toBe(true);
    expect(hasOnboardingExchange(messages, "Hello Nova", "Different reply")).toBe(false);
  });

  it("counts durable reply bytes with the replay activity payload", () => {
    const reply = {
      id: "00000000-0000-4000-8000-000000000018",
      sourceMessageId: "00000000-0000-4000-8000-000000000019",
      conversationTurnOrdinal: 2,
      content: "Réponse durable 🙂",
      status: "in_progress" as const,
      hasFullPrefix: true,
      createdAt: "2026-08-20T16:01:01Z",
      updatedAt: "2026-08-20T16:01:02Z",
    };
    const snapshot = {
      conversationId: "00000000-0000-4000-8000-000000000005",
      activities: [],
      assistantReply: reply,
      state: "running" as const,
      lastContiguousSequence: 0,
    };

    expect(activitySnapshotBytes(snapshot)).toBe(new TextEncoder().encode(JSON.stringify({
      activities: snapshot.activities,
      assistantReply: reply,
    })).byteLength);
    expect(activitySnapshotBytes(snapshot)).toBeGreaterThan(activitySnapshotBytes({
      ...snapshot,
      assistantReply: null,
    }));
  });

  it.each([
    [{ kind: "activity-cursor-gap" }, "gap"],
    [{ kind: "activity-cursor-expired" }, "expired"],
    [{ kind: "activity-cursor-invalid" }, "invalid"],
    [new ActivityReplayBoundError(), "bounds"],
  ] as const)("classifies replay recovery failure %s", (error, expected) => {
    expect(activityReplayFailure(error)).toBe(expected);
  });

  it("keeps an empty account honest and offers the first-Ally flow", async () => {
    renderHome([]);
    expect(await screen.findByText("No Allies here yet.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Mira" })).toBeNull();
    expect(screen.getByRole("button", { name: "Make an Ally" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Meet your first Ally" })).toBeTruthy();
  });

  it("opens mobile Ally creation in the homepage drawer", async () => {
    renderHome([], "new");
    expect(await screen.findByRole("dialog", { name: "Make your Ally" })).toBeTruthy();
    expect(screen.getByText("Shape your Ally")).toBeTruthy();
  });

  it("opens desktop Ally creation as the homepage overlay and leaves for the new chat", async () => {
    stubViewport(true);
    renderHome([ally], ally.id);

    fireEvent.click(await screen.findByRole("button", { name: "Make an Ally" }));
    expect(await screen.findByRole("dialog", { name: "Make your Ally" })).toBeTruthy();
    expect(screen.getByText("Shape your Ally")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Finish create" }));
    expect(replace).toHaveBeenCalledWith("/home/00000000-0000-4000-8000-000000000099");
    expect(screen.getByRole("heading", { name: "Opening Nova" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Ally sidebar" })).toBeNull();
  });

  it("renders a compact real Ally row and its persisted conversation", async () => {
    const client = renderHome([ally], ally.id);
    expect(await screen.findByRole("heading", { name: "Mira" })).toBeTruthy();
    expect(screen.getAllByText("Study partner")).toHaveLength(1);
    expect(await screen.findAllByText("What should we work on first?")).toHaveLength(2);
    await waitFor(() => expect(client.getAllyConversation).toHaveBeenCalled());
    expect(screen.queryByText(/unread/i)).toBeNull();
  });

  it("edits an Ally label, keeps Show label gated, and updates the roster", async () => {
    const client = renderHome([ally], ally.id);
    const settingsButton = (await screen.findAllByRole("button", { name: "Mira settings" }))[0];
    fireEvent.click(settingsButton);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    const label = within(dialog).getByRole("textbox", { name: "Label" }) as HTMLInputElement;
    const showLabel = within(dialog).getByRole("checkbox", { name: /Show label/ }) as HTMLInputElement;

    expect(showLabel.disabled).toBe(true);
    fireEvent.change(label, { target: { value: "chief of staff" } });
    expect(showLabel.disabled).toBe(false);
    fireEvent.click(showLabel);
    fireEvent.change(label, { target: { value: "" } });
    expect(showLabel.disabled).toBe(true);
    expect(showLabel.checked).toBe(false);
    fireEvent.change(label, { target: { value: "chief of staff" } });
    fireEvent.click(showLabel);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(client.updateAllySettings).toHaveBeenCalledOnce());
    expect(client.updateAllySettings).toHaveBeenCalledWith(
      account.workspace.id,
      ally.id,
      { label: "chief of staff", showLabel: true, settingsRevision: 0 },
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("chief of staff")).toBeTruthy();
    expect(within(dialog).getByRole("status").textContent).toBe("Settings saved.");
  });

  it("requires the exact deletion phrase and focuses confirmation before the destructive action", async () => {
    const client = renderHome([ally], ally.id);
    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));

    const confirmation = within(dialog).getByRole("textbox", { name: /Type the exact phrase to confirm/ }) as HTMLInputElement;
    await waitFor(() => expect(document.activeElement).toBe(confirmation));
    const deleteButton = within(dialog).getByRole("button", { name: "Delete Ally" }) as HTMLButtonElement;
    expect(within(dialog).getByText("Mira - deletes me")).toBeTruthy();
    expect(deleteButton.disabled).toBe(true);

    fireEvent.change(confirmation, { target: { value: "Mira - deletes Me" } });
    expect(deleteButton.disabled).toBe(true);
    fireEvent.click(deleteButton);
    expect(client.requestAllyDeletion).not.toHaveBeenCalled();
  });

  it("keeps a lost deletion request pending, then removes only the target after completion", async () => {
    const sibling = { ...ally, id: "00000000-0000-4000-8000-000000000010", name: "Sage" };
    const pending = {
      allyId: ally.id,
      operationId: "00000000-0000-4000-8000-000000000020",
      state: "pending" as const,
      retryable: true,
      safeErrorCode: "request_unknown",
    };
    const complete = {
      allyId: ally.id,
      state: "complete" as const,
      retryable: false,
      safeErrorCode: "",
    };
    const requestAllyDeletion = vi.fn().mockRejectedValue({ kind: "network" });
    const getAllyDeletion = vi.fn()
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(complete);
    const client = renderHome([ally, sibling], ally.id, { requestAllyDeletion, getAllyDeletion });
    const targetKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    const siblingKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${sibling.id}`;
    window.localStorage.setItem(targetKey, JSON.stringify([{ id: "target-queued", content: "remove me", intentKey: "target-intent", queuedAt: 1 }]));
    window.localStorage.setItem(`${targetKey}:removed:target-old`, String(Date.now()));
    window.localStorage.setItem(siblingKey, JSON.stringify([{ id: "sibling-queued", content: "keep me", intentKey: "sibling-intent", queuedAt: 1 }]));

    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));
    const confirmation = within(dialog).getByRole("textbox", { name: /Type the exact phrase to confirm/ });
    fireEvent.change(confirmation, { target: { value: "Mira - deletes me" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));

    await waitFor(() => expect(screen.getByText("We couldn't confirm the request. We'll keep checking its status.")).toBeTruthy());
    expect(screen.getByTestId("ally-deletion-status")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Sage/ })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Refresh status" }));
    await waitFor(() => expect(getAllyDeletion).toHaveBeenCalledOnce());
    expect(screen.getByTestId("ally-deletion-status")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Sage/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Mira/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Refresh deletion status" }));
    await waitFor(() => expect(getAllyDeletion).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId("ally-deletion-status")).toBeNull());
    expect(screen.getByRole("link", { name: /Sage/ })).toBeTruthy();
    expect(window.localStorage.getItem(targetKey)).toBeNull();
    expect(window.localStorage.getItem(`${targetKey}:removed:target-old`)).toBeNull();
    expect(window.localStorage.getItem(siblingKey)).toContain("sibling-queued");
    expect(client.queryClient.getQueryData(["workspaces", account.workspace.id, "allies", ally.id, "conversation"])).toBeUndefined();
  });

  it("reconciles a concurrent deletion conflict before entering tracked pending state", async () => {
    const sibling = { ...ally, id: "00000000-0000-4000-8000-000000000010", name: "Sage" };
    const pending = {
      allyId: ally.id,
      operationId: "00000000-0000-4000-8000-000000000020",
      state: "pending" as const,
      retryable: true,
      safeErrorCode: "",
    };
    const complete = {
      allyId: ally.id,
      state: "complete" as const,
      retryable: false,
      safeErrorCode: "",
    };
    const requestAllyDeletion = vi.fn().mockRejectedValue({
      kind: "conflict",
      status: 409,
      code: "deletion_conflict",
    });
    const getAllyDeletion = vi.fn()
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(complete);
    const client = renderHome([ally, sibling], ally.id, { requestAllyDeletion, getAllyDeletion });

    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: /Type the exact phrase to confirm/ }),
      { target: { value: "Mira - deletes me" } },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));

    await waitFor(() => expect(getAllyDeletion).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("ally-deletion-status")).toBeTruthy();
    expect(screen.getByText("This Ally is already being deleted. We'll keep checking its status.")).toBeTruthy();
    expect(screen.queryByText("This deletion request conflicted with a change.")).toBeNull();
    expect(client.queryClient.getQueryData<AllyViewModel[]>(["workspaces", account.workspace.id, "allies"])?.[0]?.deletionState).toBe("pending");
    expect(screen.getByRole("link", { name: /Sage/ })).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Refresh status" }));
    await waitFor(() => expect(getAllyDeletion).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByTestId("ally-deletion-status")).toBeNull());
    expect(screen.getByRole("link", { name: /Sage/ })).toBeTruthy();
  });

  it("keeps an exact-name deletion conflict in confirmation after status reconciliation finds no operation", async () => {
    const requestAllyDeletion = vi.fn().mockRejectedValue({
      kind: "conflict",
      status: 409,
      code: "deletion_conflict",
    });
    const getAllyDeletion = vi.fn().mockRejectedValue({ kind: "not-found", status: 404 });
    const client = renderHome([ally], ally.id, { requestAllyDeletion, getAllyDeletion });

    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: /Type the exact phrase to confirm/ }),
      { target: { value: "Mira - deletes me" } },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));

    await waitFor(() => expect(getAllyDeletion).toHaveBeenCalledOnce());
    expect(screen.getByRole("dialog", { name: "Mira settings" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("changed before deletion could start");
    expect(screen.queryByTestId("ally-deletion-status")).toBeNull();
    expect(screen.queryByText(/already being deleted/i)).toBeNull();
    expect(screen.getByRole("link", { name: /Mira/ })).toBeTruthy();
    expect(client.queryClient.getQueryData<AllyViewModel[]>(["workspaces", account.workspace.id, "allies"])?.[0]?.deletionState).toBeUndefined();
  });

  it("rejects a mismatched deletion status without fencing the other Ally", async () => {
    const sibling = { ...ally, id: "00000000-0000-4000-8000-000000000010", name: "Sage" };
    const requestAllyDeletion = vi.fn().mockRejectedValue({ kind: "conflict", status: 409 });
    const getAllyDeletion = vi.fn().mockResolvedValue({
      allyId: sibling.id,
      operationId: "00000000-0000-4000-8000-000000000020",
      state: "pending" as const,
      retryable: true,
      safeErrorCode: "",
    });
    const client = renderHome([ally, sibling], ally.id, { requestAllyDeletion, getAllyDeletion });

    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));
    fireEvent.change(
      within(dialog).getByRole("textbox", { name: /Type the exact phrase to confirm/ }),
      { target: { value: "Mira - deletes me" } },
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Ally" }));

    await waitFor(() => expect(getAllyDeletion).toHaveBeenCalledOnce());
    expect(screen.getByRole("dialog", { name: "Mira settings" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("couldn't verify whether another deletion is in progress");
    expect(within(dialog).getByRole("button", { name: "Check status" })).toBeTruthy();
    expect(screen.queryByTestId("ally-deletion-status")).toBeNull();
    expect(screen.getByRole("link", { name: /Mira/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Sage/ })).toBeTruthy();
    expect(client.queryClient.getQueryData<AllyViewModel[]>(["workspaces", account.workspace.id, "allies"])?.map((candidate) => candidate.deletionState)).toEqual([undefined, undefined]);
  });

  it("does not let a delayed settings save reactivate an Ally accepted for deletion", async () => {
    let resolveSave!: (value: AllyViewModel) => void;
    const updateAllySettings = vi.fn(() => new Promise<AllyViewModel>((resolve) => {
      resolveSave = resolve;
    }));
    const client = renderHome([ally], ally.id, { updateAllySettings });
    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    const label = within(dialog).getByRole("textbox", { name: "Label" });
    fireEvent.change(label, { target: { value: "new label" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledOnce());

    await act(async () => {
      client.queryClient.setQueryData<AllyViewModel[]>(["workspaces", account.workspace.id, "allies"], [
        { ...ally, deletionState: "pending" },
      ]);
    });
    expect(await screen.findByTestId("ally-deletion-status")).toBeTruthy();

    await act(async () => resolveSave({ ...ally, label: "new label", settingsRevision: 1 }));
    await waitFor(() => expect(client.queryClient.getQueryData<AllyViewModel[]>(["workspaces", account.workspace.id, "allies"])?.[0]?.deletionState).toBe("pending"));
    expect(screen.getByTestId("ally-deletion-status")).toBeTruthy();
  });

  it("keeps the draft and uses the refreshed revision after a settings conflict", async () => {
    const freshAlly = {
      ...ally,
      label: "project manager",
      showLabel: true,
      settingsRevision: 3,
    };
    const listAllies = vi.fn()
      .mockResolvedValueOnce([ally])
      .mockResolvedValue([freshAlly]);
    const updateAllySettings = vi.fn()
      .mockRejectedValueOnce({ kind: "conflict", status: 409 })
      .mockResolvedValueOnce({ ...freshAlly, label: "chief of staff", showLabel: true, settingsRevision: 4 });
    const client = renderHome([ally], ally.id, { listAllies, updateAllySettings });
    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    const label = within(dialog).getByRole("textbox", { name: "Label" }) as HTMLInputElement;
    const showLabel = within(dialog).getByRole("checkbox", { name: /Show label/ }) as HTMLInputElement;
    fireEvent.change(label, { target: { value: "chief of staff" } });
    fireEvent.click(showLabel);
    await act(async () => {
      client.queryClient.setQueryData(["workspaces", "workspace", "allies"], [freshAlly]);
    });
    await waitFor(() => expect(screen.getByText("project manager")).toBeTruthy());
    expect(label.value).toBe("chief of staff");
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledOnce());
    expect(updateAllySettings.mock.calls[0]?.[2]).toEqual({
      label: "chief of staff",
      showLabel: true,
      settingsRevision: 0,
    });
    await waitFor(() => expect(listAllies).toHaveBeenCalledTimes(2));
    expect(label.value).toBe("chief of staff");
    expect(within(dialog).getByRole("alert").textContent).toContain("refreshed its settings");

    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledTimes(2));
    expect(updateAllySettings.mock.calls[1]?.[2]).toEqual({
      label: "chief of staff",
      showLabel: true,
      settingsRevision: 3,
    });
  });

  it("keeps the draft and reports when conflict refresh fails", async () => {
    const listAllies = vi.fn()
      .mockResolvedValueOnce([ally])
      .mockRejectedValueOnce(new Error("temporary Ally failure"));
    const updateAllySettings = vi.fn().mockRejectedValueOnce({ kind: "conflict", status: 409 });
    renderHome([ally], ally.id, { listAllies, updateAllySettings });
    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    const label = within(dialog).getByRole("textbox", { name: "Label" }) as HTMLInputElement;
    fireEvent.change(label, { target: { value: "chief of staff" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledOnce());
    await waitFor(() => expect(listAllies).toHaveBeenCalledTimes(2));
    expect(label.value).toBe("chief of staff");
    expect(within(dialog).getByRole("alert").textContent).toContain("couldn't refresh");
  });

  it("preserves the draft after a failed settings save", async () => {
    let rejectSave!: (reason?: unknown) => void;
    const updateAllySettings = vi.fn(() => new Promise<AllyViewModel>((_resolve, reject) => {
      rejectSave = reject;
    }));
    renderHome([ally], ally.id, { updateAllySettings });
    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    const label = within(dialog).getByRole("textbox", { name: "Label" }) as HTMLInputElement;
    fireEvent.change(label, { target: { value: "chief of staff" } });
    const saveButton = within(dialog).getByRole("button", { name: "Save" }) as HTMLButtonElement;
    fireEvent.click(saveButton);

    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledOnce());
    expect(label.disabled).toBe(true);
    expect(saveButton.disabled).toBe(true);
    await act(async () => rejectSave({ kind: "network" }));
    await waitFor(() => expect(within(dialog).getByRole("alert")).toBeTruthy());
    expect(label.value).toBe("chief of staff");
    expect(within(dialog).getByRole("alert").textContent).toContain("Your draft is still here");
    expect((within(dialog).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("fences stale Ally reads around a settings save", async () => {
    const staleAlly = { ...ally, label: "stale roster", showLabel: true, settingsRevision: 0 };
    const staleResolvers: Array<(value: AllyViewModel[]) => void> = [];
    const staleSignals: AbortSignal[] = [];
    const listAllies = vi.fn()
      .mockResolvedValueOnce([ally])
      .mockImplementation((_workspaceId: string, signal?: AbortSignal) => new Promise<AllyViewModel[]>((resolve) => {
        staleResolvers.push(resolve);
        if (signal) staleSignals.push(signal);
      }));
    let resolveSave!: (value: AllyViewModel) => void;
    const updateAllySettings = vi.fn(() => new Promise<AllyViewModel>((resolve) => {
      resolveSave = resolve;
    }));
    const client = renderHome([ally], ally.id, { listAllies, updateAllySettings });
    fireEvent.click((await screen.findAllByRole("button", { name: "Mira settings" }))[0]);
    const dialog = await screen.findByRole("dialog", { name: "Mira settings" });
    const label = within(dialog).getByRole("textbox", { name: "Label" }) as HTMLInputElement;
    const showLabel = within(dialog).getByRole("checkbox", { name: /Show label/ }) as HTMLInputElement;
    fireEvent.change(label, { target: { value: "chief of staff" } });
    fireEvent.click(showLabel);

    const beforeSaveRead = client.queryClient.refetchQueries({
      queryKey: ["workspaces", "workspace", "allies"],
      exact: true,
    });
    await waitFor(() => expect(listAllies).toHaveBeenCalledTimes(2));
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledOnce());
    expect(staleSignals[0]?.aborted).toBe(true);

    const duringSaveRead = client.queryClient.refetchQueries({
      queryKey: ["workspaces", "workspace", "allies"],
      exact: true,
    });
    await waitFor(() => expect(listAllies).toHaveBeenCalledTimes(3));
    const savedAlly = { ...ally, label: "chief of staff", showLabel: true, settingsRevision: 1 };
    await act(async () => resolveSave(savedAlly));
    await waitFor(() => expect(screen.getByText("chief of staff")).toBeTruthy());
    expect(staleSignals[1]?.aborted).toBe(true);

    await act(async () => {
      staleResolvers.forEach((resolve) => resolve([staleAlly]));
      await Promise.all([beforeSaveRead, duringSaveRead]);
    });
    expect(client.queryClient.getQueryData<AllyViewModel[]>(["workspaces", "workspace", "allies"])?.[0]).toMatchObject(savedAlly);
  });

  it("keeps an active handoff Ally in settings when the roster cache omits it", async () => {
    const createdAlly: AllyViewModel = {
      id: "00000000-0000-4000-8000-000000000099",
      bindingId: "00000000-0000-4000-8000-000000000098",
      operationId: "00000000-0000-4000-8000-000000000097",
      name: "Nova",
      job: "Study partner",
      personality: "Calm",
      appearance: { catalogVersion: "v1", key: "ghosty:fd304f" },
      provisioningState: "bound",
      retryable: false,
    };
    const getAllyConversation = vi.fn(async (_workspaceId: string, selectedId: string) => ({
      id: "00000000-0000-4000-8000-000000000005",
      allyId: selectedId,
      messages: selectedId === createdAlly.id ? [
        { id: "greeting", sender: "assistant" as const, content: "Hello Nova", sequence: 1, status: "completed" as const, createdAt: "2026-08-20T16:00:00Z" },
        { id: "reply", sender: "user" as const, content: "Help me study", sequence: 2, status: "queued" as const, createdAt: "2026-08-20T16:00:01Z" },
      ] : [],
      nextCursor: null,
    }));
    const updateAllySettings = vi.fn(async (
      _workspaceId: string,
      _allyId: string,
      input: { label: string; showLabel: boolean; settingsRevision: number },
    ) => ({
      ...createdAlly,
      label: input.label,
      showLabel: input.showLabel,
      settingsRevision: input.settingsRevision + 1,
    }));
    const client = renderHome([], "new", { getAllyConversation, updateAllySettings }, <NewAllyPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Finish create" }));
    expect(await screen.findByText("Opening Nova")).toBeTruthy();
    await act(async () => {
      client.queryClient.setQueryData(["workspaces", "workspace", "allies"], []);
    });
    selectedSegment.mockReturnValue(createdAlly.id);
    client.view.rerender(<QueryClientProvider client={client.queryClient}><HomeLayout><NewAllyPage /></HomeLayout></QueryClientProvider>);
    await waitFor(() => expect(screen.queryByText("Opening Nova")).toBeNull());
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Nova settings" }).length).toBeGreaterThan(0));

    fireEvent.click(screen.getAllByRole("button", { name: "Nova settings" })[0]);
    const dialog = await screen.findByRole("dialog", { name: "Nova settings" });
    const label = within(dialog).getByRole("textbox", { name: "Label" }) as HTMLInputElement;
    const showLabel = within(dialog).getByRole("checkbox", { name: /Show label/ }) as HTMLInputElement;
    fireEvent.change(label, { target: { value: "chief of staff" } });
    fireEvent.click(showLabel);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateAllySettings).toHaveBeenCalledOnce());
    await waitFor(() => expect(label.value).toBe("chief of staff"));
    expect(client.queryClient.getQueryData<AllyViewModel[]>(["workspaces", "workspace", "allies"])?.[0]).toMatchObject({
      id: createdAlly.id,
      label: "chief of staff",
      showLabel: true,
      settingsRevision: 1,
    });

    await act(async () => {
      client.queryClient.setQueryData(["workspaces", "workspace", "allies"], []);
    });
    expect(label.value).toBe("chief of staff");
  });

  it("keeps automatic provisioning retries in the getting-ready state", async () => {
    const retryingAlly = { ...ally, provisioningState: "retryable" as const, retryable: true };
    renderHome([retryingAlly], retryingAlly.id);

    expect(await screen.findByText("Waking up")).toBeTruthy();
    expect(screen.queryByText(/finishing setup/i)).toBeNull();
    expect(screen.queryByText(/outside Home/i)).toBeNull();
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
      .mockResolvedValueOnce({ conversationId, activities: [], state: "completed" as const, lastContiguousSequence: 0 })
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
    const client = renderHome([pendingAlly], ally.id, { getAllyConversation, getActivities });

    expect(await screen.findByText("Initial question", { selector: "article p" })).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    expect(screen.queryByText("Thinking")).toBeNull();
    const readsBeforeProvisioning = getAllyConversation.mock.calls
      .filter((call) => call[2]?.limit === 50).length;
    provisioned = true;
    await act(async () => {
      client.queryClient.setQueryData(["workspaces", "workspace", "allies"], [ally]);
    });

    expect(screen.getByTestId("conversation-ally").getAttribute("data-state")).not.toBe("thinking");
    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(2), { timeout: 2_000 });
    await waitFor(() => expect(
      getAllyConversation.mock.calls.filter((call) => call[2]?.limit === 50).length,
    ).toBeGreaterThan(readsBeforeProvisioning));
    await act(async () => resolveResponse?.({
      conversationId,
      activities: [{
        id: "00000000-0000-4000-8000-000000000009",
        messageId: initialQuestion.id,
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
    expect(await screen.findByText("Initial question", { selector: "article p" })).toBeTruthy();
    expect(screen.queryByText("The initial response arrived.")).toBeNull();
  });

  it("keeps an unscoped v1 queue untouched with an explicit notice", async () => {
    const legacyKey = `allies:v1:queued-messages:${account.workspace.id}:${ally.id}`;
    window.localStorage.setItem(legacyKey, JSON.stringify([{
      id: "legacy-message",
      content: "Do not expose across accounts",
      intentKey: "legacy-intent",
    }]));

    renderHome([ally], ally.id);

    expect((await screen.findByRole("alert")).textContent).toContain("could not be restored safely");
    expect(window.localStorage.getItem(legacyKey)).toContain("legacy-message");
    expect(screen.queryByText("Do not expose across accounts")).toBeNull();
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
    const row = screen.getByRole("link", { name: /Mira(?! settings)/ });
    await waitFor(() => expect(row.getAttribute("data-ally-sleeping")).toBe("true"));
    expect(row.querySelector("[data-testid=ally-avatar]")?.getAttribute("data-state")).toBe("sleeping");

    fireEvent.change(input, { target: { value: "  " } });
    expect(requestRuntimeIntent).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "Hello" } });
    fireEvent.change(input, { target: { value: "Hello, again" } });

    expect(row.getAttribute("data-ally-sleeping")).toBe("false");
    expect(row.querySelector("[data-testid=ally-avatar]")?.getAttribute("data-state")).toBe("idle");
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

  it("keeps the Ally roster on /home on desktop", async () => {
    const newest = { ...ally, id: "00000000-0000-4000-8000-000000000009", name: "Nova" };
    renderHome([newest, ally]);

    expect(await screen.findByRole("link", { name: /Nova/ })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps the Ally list as the mobile Home entry", async () => {
    renderHome([ally]);

    const row = await screen.findByRole("link", { name: /Mira(?! settings)/ });
    expect(row.getAttribute("href")).toBe(`/home/${ally.id}`);
    expect(row.querySelector("[data-testid=ally-avatar]")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("uses the roster-only layout on mobile /home", async () => {
    renderHome([ally]);

    expect((await screen.findByRole("link", { name: "Timi Person" })).getAttribute("href")).toBe("/account");
    expect(screen.getByRole("button", { name: "Make an Ally" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Selected Ally conversation" })).toBeNull();
  });

  it("keeps the desktop dashboard two-pane with an empty chat beside", async () => {
    stubViewport(true);
    renderHome([ally]);

    expect(await screen.findByRole("link", { name: /Mira(?! settings)/ })).toBeTruthy();
    expect(screen.getByTestId("dashboard-ui-push")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Search Allies" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Make an Ally" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Selected Ally conversation" })).toBeTruthy();
    expect(screen.getByTestId("empty-thread")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("filters Allies by name without navigating and restores the list when search closes", async () => {
    renderHome([ally]);
    expect(await screen.findByRole("link", { name: /Mira(?! settings)/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Search Allies" }));
    const search = screen.getByRole("searchbox", { name: "Filter Allies by name" });
    fireEvent.change(search, { target: { value: "  mIrA  " } });
    expect(screen.getByRole("link", { name: /Mira(?! settings)/ })).toBeTruthy();
    fireEvent.change(search, { target: { value: "no matching name" } });
    expect(screen.queryByRole("link", { name: /Mira(?! settings)/ })).toBeNull();
    expect(screen.getByText("No Allies match your search.").getAttribute("role")).toBe("status");
    fireEvent.click(screen.getByRole("button", { name: "Search Allies" }));
    expect(screen.getByRole("link", { name: /Mira(?! settings)/ })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps sidebar nodes, search and sleeping state across Home layout navigation", async () => {
    stubViewport(true);
    const secondAlly = { ...ally, id: "00000000-0000-4000-8000-000000000010", name: "Nova" };
    const client = renderHome([ally, secondAlly], ally.id, {}, <AllyHomePage />);
    const row = await screen.findByRole("link", { name: /Mira(?! settings)/ });
    await waitFor(() => expect(row.getAttribute("data-ally-sleeping")).toBe("true"));
    const avatar = row.querySelector("[data-testid=ally-avatar]");
    const sidebar = screen.getByRole("complementary", { name: "Ally sidebar" });
    fireEvent.click(screen.getByRole("button", { name: "Search Allies" }));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "MiRa" } });
    selectedSegment.mockReturnValue(secondAlly.id);
    client.view.rerender(<QueryClientProvider client={client.queryClient}><HomeLayout><AllyHomePage /></HomeLayout></QueryClientProvider>);
    expect(await screen.findByRole("heading", { name: "Nova" })).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "Ally sidebar" })).toBe(sidebar);
    expect(screen.getByRole("link", { name: /Mira(?! settings)/ })).toBe(row);
    expect(row.querySelector("[data-testid=ally-avatar]")).toBe(avatar);
    expect(row.getAttribute("data-ally-sleeping")).toBe("true");
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("MiRa");
    expect(screen.queryByRole("button", { name: "Routines" })).toBeNull();
    expect(screen.queryByRole("button", { name: "My allies" })).toBeNull();
  });

  it("does not load another account's queued messages", async () => {
    const privateStorageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    window.localStorage.setItem(privateStorageKey, JSON.stringify([{
      id: "private-queued-message",
      content: "Private queued message",
      intentKey: "private-intent",
    }]));
    const otherAccount = { ...account, userId: "other-user" };

    renderHome([ally], ally.id, {
      getCurrentAccount: vi.fn(async () => otherAccount),
    });

    expect(await screen.findByRole("heading", { name: "Mira" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("Private queued message")).toBeNull());
    expect(window.localStorage.getItem(privateStorageKey)).toContain("Private queued message");
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

  it("keeps durable replies across older-page navigation and latest-window refresh", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const latestUserMessage = {
      id: "00000000-0000-4000-8000-000000000020",
      sender: "user" as const,
      content: "Latest question",
      sequence: 4,
      status: "completed" as const,
      createdAt: "2026-08-20T16:00:00Z",
    };
    const olderUserMessage = {
      id: "00000000-0000-4000-8000-000000000021",
      sender: "user" as const,
      content: "Earlier question",
      sequence: 2,
      status: "completed" as const,
      createdAt: "2026-08-20T15:00:00Z",
    };
    const latestReply = {
      id: "00000000-0000-4000-8000-000000000022",
      sourceMessageId: latestUserMessage.id,
      conversationTurnOrdinal: latestUserMessage.sequence,
      content: "Latest durable reply",
      status: "completed" as const,
      hasFullPrefix: true,
      createdAt: "2026-08-20T16:00:01Z",
      updatedAt: "2026-08-20T16:00:01Z",
    };
    const olderReply = {
      id: "00000000-0000-4000-8000-000000000023",
      sourceMessageId: olderUserMessage.id,
      conversationTurnOrdinal: olderUserMessage.sequence,
      content: `Earlier durable reply ${"r".repeat(300 * 1024)}`,
      status: "completed" as const,
      hasFullPrefix: true,
      createdAt: "2026-08-20T15:00:01Z",
      updatedAt: "2026-08-20T15:00:01Z",
    };
    const acceptedMessage = {
      id: "00000000-0000-4000-8000-000000000024",
      sender: "user" as const,
      content: "Refresh the window",
      sequence: 6,
      status: "completed" as const,
      createdAt: "2026-08-20T16:02:00Z",
    };
    const initialPage = {
      id: conversationId,
      allyId: ally.id,
      messages: [latestUserMessage],
      assistantReplies: [latestReply],
      nextCursor: "cursor-1",
    };
    const refreshedPage = {
      id: conversationId,
      allyId: ally.id,
      messages: [acceptedMessage],
      assistantReplies: [],
      nextCursor: null,
    };
    const getAllyConversation = vi.fn(async (
      _workspaceId: string,
      _allyId: string,
      options?: { limit?: number },
    ) => {
      if (options?.limit === 20) return initialPage;
      return getAllyConversation.mock.calls.filter((call) => call[2]?.limit === 50).length === 1
        ? initialPage
        : refreshedPage;
    });
    const getConversation = vi.fn(async () => ({
      id: conversationId,
      allyId: ally.id,
      messages: [olderUserMessage],
      assistantReplies: [olderReply],
      nextCursor: null,
    }));
    const sendMessage = vi.fn(async () => ({
      conversationId,
      message: acceptedMessage,
      execution: null,
      replayed: false,
    }));
    const getActivities = vi.fn(async () => ({
      conversationId,
      activities: [],
      state: "running" as const,
      lastContiguousSequence: 0,
    }));
    renderHome([ally], ally.id, { getAllyConversation, getConversation, getActivities, sendMessage });

    expect(await screen.findAllByText("Latest durable reply")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Earlier messages" }));
    expect(await screen.findByText("Earlier durable reply", { exact: false })).toBeTruthy();

    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: acceptedMessage.content } });
    await clickSendMessage();
    await waitFor(() => expect(
      getAllyConversation.mock.calls.filter((call) => call[2]?.limit === 50),
    ).toHaveLength(2));
    await waitFor(() => expect(screen.getAllByText("Latest durable reply")).toBeTruthy());
    expect(screen.getByText("Earlier durable reply", { exact: false })).toBeTruthy();
  });

  it("shows an explicit placeholder when an Ally appearance is unsupported", async () => {
    const unsupported = {
      ...ally,
      appearance: { catalogVersion: "v9", key: "ghosty:fd304f" },
    };
    renderHome([unsupported], unsupported.id);

    expect((await screen.findAllByTestId("ally-appearance-unavailable"))).toHaveLength(2);
  });

  it("keeps a failed send key when the draft returns to the same intent", async () => {
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
    expect(sendMessage.mock.calls[2]?.[3]).toBe(firstKey);
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

  it("keeps thinking visible after an awake send is accepted but not yet claimed", async () => {
    const sendMessage = vi.fn(async () => ({
      conversationId: "00000000-0000-4000-8000-000000000005",
      message: {
        id: "accepted-unclaimed", sender: "user" as const, content: "Start now",
        sequence: 2, status: "queued" as const, queueState: "unclaimed" as const,
        createdAt: new Date().toISOString(),
      },
      execution: null, replayed: false,
    }));
    const requestRuntimeIntent = vi.fn<RuntimeIntentRequester>(async () => ({ status: "already_ready" }));
    renderHome([ally], ally.id, { sendMessage, requestRuntimeIntent });
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "Start now" } });
    await waitFor(() => expect(requestRuntimeIntent).toHaveBeenCalledOnce());
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    expect(await screen.findByRole("status", { name: "Thinking" })).toBeTruthy();
    expect(screen.getByText("Start now")).toBeTruthy();
  });

  it("persists an immediate send before I/O and reuses its key after response loss and reload", async () => {
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    let firstKey: string | undefined;
    let storedBeforeFirstRequest: string | null = null;
    const sendMessage = vi.fn()
      .mockImplementationOnce(async (...args: unknown[]) => {
        firstKey = String(args[3]);
        storedBeforeFirstRequest = window.localStorage.getItem(storageKey);
        throw { kind: "timeout" };
      })
      .mockImplementationOnce(async () => {
        throw { kind: "timeout" };
      })
      .mockResolvedValueOnce({
        conversationId: "00000000-0000-4000-8000-000000000005",
        message: {
          id: "00000000-0000-4000-8000-000000000007",
          sender: "user" as const,
          content: "Recover this send",
          sequence: 2,
          status: "completed" as const,
          createdAt: "2026-08-20T16:01:00Z",
        },
        execution: null,
        replayed: true,
      });
    const overrides = { sendMessage };
    renderHome([ally], ally.id, overrides);

    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "Recover this send" } });
    await clickSendMessage();
    expect(await screen.findByText("We couldn't confirm your message")).toBeTruthy();
    expect(storedBeforeFirstRequest).toContain("Recover this send");
    expect(window.localStorage.getItem(storageKey)).toContain(firstKey);
    const failedQueue = screen.getByRole("list", { name: "Queued messages" });
    expect(failedQueue.textContent).toContain("Recover this send");
    expect((input as HTMLTextAreaElement).value).toBe("Recover this send");
    expect((screen.getByRole("button", { name: "Send message" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("Sending")).toBeNull();
    expect(screen.queryByText("Not confirmed")).toBeNull();
    expect(screen.queryByRole("status", { name: "Thinking" })).toBeNull();

    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[3]).toBe(firstKey);
    expect(window.localStorage.getItem(storageKey)).toContain(firstKey);

    cleanup();
    renderHome([ally], ally.id, overrides);
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(3));
    expect(sendMessage.mock.calls[2]?.[3]).toBe(firstKey);
    await waitFor(() => expect(window.localStorage.getItem(storageKey)).toBeNull());
  });

  it("retains an accepted tail when a pre-send conversation read resolves afterward", async () => {
    const head: MessageViewModel = {
      id: "head", sender: "user", content: "First question", sequence: 2,
      status: "queued", queueState: "claimed", createdAt: "2026-09-06T12:00:00Z",
    };
    const tail: MessageViewModel = { ...head, id: "tail", content: "Second question", sequence: 3, queueState: "unclaimed" };
    const initial: ConversationViewModel = {
      id: "conversation", allyId: ally.id, messages: [head], queue: [head], assistantReplies: [], routineItems: [], nextCursor: null,
    };
    const getAllyConversation = vi.fn(async () => initial);
    const sendMessage = vi.fn(async () => ({ conversationId: initial.id, message: tail, execution: null, replayed: false }));
    const client = renderHome([ally], ally.id, {
      getAllyConversation,
      getActivities: vi.fn(() => new Promise(() => undefined)),
      sendMessage,
    });
    await screen.findByText("First question", { selector: "article p, ol li span" });
    let finishRead!: (value: ConversationViewModel) => void;
    getAllyConversation.mockImplementationOnce(() => new Promise((resolve) => { finishRead = resolve; }));
    void client.queryClient.refetchQueries({ queryKey: ["workspaces", "workspace", "allies", ally.id, "conversation"] });
    await waitFor(() => expect(finishRead).toBeDefined());
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Second question" } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    await act(async () => { finishRead({ ...initial, messages: [...initial.messages] }); });
    await waitFor(() => expect(window.localStorage.getItem(`allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`)).toBeNull());
    expect(screen.getByRole("list", { name: "Queued messages" }).textContent).toContain("Second question");
  });

  it("advances a snapshot to the next head after a missed terminal and rejects an older head", () => {
    const head: MessageViewModel = {
      id: "head", sender: "user", content: "First question", sequence: 2,
      status: "in_progress", queueState: "claimed", createdAt: "2026-09-06T12:00:00Z",
    };
    const tail: MessageViewModel = { ...head, id: "tail", sequence: 3, status: "queued", queueState: "unclaimed" };
    const running = { ...EMPTY_ACTIVITY_PROJECTION, activeMessageId: head.id, state: "running" as const };
    const next = projectConversationActivity(running, {
      conversationId: "conversation", activeMessageId: tail.id, activities: [], state: "queued", lastContiguousSequence: 0,
    }, [head, tail]);
    expect(next.activeMessageId).toBe(tail.id);
    expect(next.state).toBe("queued");
    const stale = projectConversationActivity(next, {
      conversationId: "conversation", activeMessageId: head.id, activities: [], state: "completed", lastContiguousSequence: 0,
    }, [head, tail]);
    expect(stale.activeMessageId).toBe(tail.id);
    expect(stale.state).toBe("queued");
  });

  it("moves visible progress to the next head before a stale conversation page refreshes", async () => {
    const head: MessageViewModel = {
      id: "head", sender: "user", content: "First question", sequence: 2,
      status: "in_progress", queueState: "claimed", createdAt: "2026-09-06T12:00:00Z",
    };
    const tail: MessageViewModel = { ...head, id: "tail", content: "Second question", sequence: 3, status: "queued", queueState: "unclaimed" };
    const getActivities = vi.fn()
      .mockResolvedValueOnce({ conversationId: "conversation", activeMessageId: head.id, activities: [], state: "running", lastContiguousSequence: 0 })
      .mockResolvedValue({
        conversationId: "conversation", activeMessageId: tail.id, state: "running", lastContiguousSequence: 1,
        activities: [{ id: "next-progress", messageId: tail.id, sequence: 1, conversationTurnOrdinal: 3,
          kind: "assistant_delta", text: "Second task response", state: "running", createdAt: "2026-09-06T12:01:00Z" }],
      });
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({ id: "conversation", allyId: ally.id, messages: [head, tail], queue: [head, tail], assistantReplies: [], nextCursor: null })),
      getActivities,
    });
    await screen.findByText("First question", { selector: "article p, ol li span" });
    await waitFor(() => expect(screen.getByText("Second question", { selector: "article p" })).toBeTruthy(), { timeout: 3000 });
    expect(screen.queryByText("Second task response")).toBeNull();
    expect(screen.getByText("Second question", { selector: "article p" })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Queued messages" })?.textContent ?? "").not.toContain("Second question");
    expect(screen.queryByRole("list", { name: "Queued messages" })?.textContent ?? "").not.toContain("First question");
  });

  it("accepts later messages while the active turn is still running", async () => {
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
        queueState: "unclaimed" as const,
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

    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Second question" } });
    await clickSendMessage();

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    await waitFor(() => expect(queue.textContent).toBe("First questionSecond question"));
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    expect(sendMessage.mock.calls[0]?.slice(0, 3)).toEqual(["workspace", conversationId, "Second question"]);
    expect(screen.getByTestId("conversation-ally").getAttribute("data-state")).toBe("idle");
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
  });

  it("reuses a failed queued message key when the restored draft is resent", async () => {
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
      .mockResolvedValueOnce({
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

    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
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
    expect(input.value).toBe("Second question");

    fireEvent.change(input, { target: { value: "Second question edited" } });
    fireEvent.change(input, { target: { value: "Second question" } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[3]).toBe(queuedIntentKey);
  });

  it("preserves in-progress composition when a queued send fails", async () => {
    let rejectSend: ((reason: unknown) => void) | undefined;
    const sendMessage = vi.fn(() => new Promise((_resolve, reject) => { rejectSend = reject; }));
    renderHome([ally], ally.id, { sendMessage });
    const input = await screen.findByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Queued question" } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "未完成" } });
    await act(async () => rejectSend?.({ kind: "timeout", status: 408 }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(input.value).toBe("未完成");
    expect(screen.getByRole("list", { name: "Queued messages" }).textContent).toContain("Queued question");
    fireEvent.compositionEnd(input, { data: "未完成" });
    expect(input.value).toBe("未完成");
  });

  it("attempts a new draft after an ambiguous queued head", async () => {
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
      .mockRejectedValueOnce({ kind: "timeout", status: 408 })
      .mockRejectedValue({ kind: "timeout", status: 408 });
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

    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
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
    const firstKey = sendMessage.mock.calls[0]?.[3];
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(input.value).toBe("Second question");

    fireEvent.change(input, { target: { value: "Third question" } });
    await clickSendMessage();

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    expect(queue.textContent).toContain("Second question");
    expect(queue.textContent).toContain("Third question");
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[2]).toBe("Third question");
    expect(screen.getByRole("alert").textContent).toContain("couldn't confirm your message");
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    expect(JSON.parse(window.localStorage.getItem(storageKey) ?? "[]")[0]?.intentKey).toBe(firstKey);
    expect(sendMessage).toHaveBeenCalledTimes(2);
  });

  it("removes a definitively rejected message so edited content can send", async () => {
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
    let rejectSend: ((reason?: unknown) => void) | undefined;
    const sendMessage = vi.fn()
      .mockImplementationOnce(() => new Promise((_resolve, reject) => {
        rejectSend = reject;
      }))
      .mockResolvedValueOnce({
        conversationId,
        message: {
          ...activeMessage,
          id: "00000000-0000-4000-8000-000000000008",
          content: "Edited question",
          status: "completed" as const,
          sequence: 3,
        },
        execution: null,
        replayed: false,
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

    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Rejected question" } });
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
    const rejectedKey = sendMessage.mock.calls[0]?.[3];
    fireEvent.change(input, { target: { value: "Newer draft" } });
    await act(async () => {
      rejectSend?.({ kind: "validation", status: 422 });
      await Promise.resolve();
    });
    await waitFor(() => expect(input.value).toBe("Rejected question\n\nNewer draft"));
    await waitFor(() => expect(window.localStorage.getItem(
      `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`,
    )).toBeNull());
    expect(screen.queryByRole("list", { name: "Queued messages" })).toBeNull();

    fireEvent.change(input, { target: { value: "Edited question" } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[2]).toBe("Edited question");
    expect(sendMessage.mock.calls[1]?.[3]).not.toBe(rejectedKey);
  });

  it.each(["SecurityError", "QuotaExceededError"])("recovers an idle send after %s without sending before persistence", async (errorName) => {
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    let storedBeforeRequest: string | null = null;
    const sendMessage = vi.fn(async () => {
      storedBeforeRequest = window.localStorage.getItem(storageKey);
      return {
        conversationId: "00000000-0000-4000-8000-000000000005",
        message: {
          id: "00000000-0000-4000-8000-000000000007",
          sender: "user" as const,
          content: "Keep this draft",
          sequence: 2,
          status: "completed" as const,
          createdAt: "2026-08-20T16:01:00Z",
        },
        execution: null,
        replayed: false,
      };
    });
    renderHome([ally], ally.id, { sendMessage });
    const input = await screen.findByRole("textbox") as HTMLTextAreaElement;
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Storage unavailable", errorName);
    });
    try {
      fireEvent.change(input, { target: { value: "Keep this draft" } });
      await clickSendMessage();
      expect((await screen.findByRole("alert")).textContent).toContain("allow site storage or free up space");
      expect(input.value).toBe("Keep this draft");
      expect(sendMessage).not.toHaveBeenCalled();
      expect(window.localStorage.getItem(storageKey)).toBeNull();
    } finally {
      setItem.mockRestore();
    }
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
    expect(storedBeforeRequest).toContain("Keep this draft");
    expect(JSON.parse(storedBeforeRequest!)[0].intentKey).toBe(
      (sendMessage.mock.calls[0] as unknown[])[3],
    );
    await waitFor(() => expect(input.value).toBe(""));
    expect(screen.queryByText(/Message not sent: browser storage is unavailable/)).toBeNull();
  });

  it("retains the draft when queued-message persistence fails", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "in_progress" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    try {
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

      expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
      const input = screen.getByRole("textbox") as HTMLTextAreaElement;
      fireEvent.change(input, { target: { value: "Keep this draft" } });
      await clickSendMessage();

      expect((await screen.findByRole("alert")).textContent).toContain("Message not sent: browser storage is unavailable.");
      expect(input.value).toBe("Keep this draft");
      expect(screen.queryByRole("list", { name: "Queued messages" })).toBeNull();
      expect(sendMessage).not.toHaveBeenCalled();
    } finally {
      setItem.mockRestore();
    }
  });

  it("bounds the persisted frontend queue", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "in_progress" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    const existingQueue = Array.from({ length: 32 }, (_, index) => ({
      id: `queued-${index}`,
      content: `Queued question ${index}`,
      intentKey: `intent-${index}`,
    }));
    window.localStorage.setItem(storageKey, JSON.stringify(existingQueue));
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
      sendMessage: vi.fn(() => new Promise(() => undefined)),
    });

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    expect(queue.querySelectorAll("li")).toHaveLength(32);
    const input = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "Do not drop this" } });
    await clickSendMessage();

    expect((await screen.findByRole("alert")).textContent).toContain("up to 32 messages");
    expect(input.value).toBe("Do not drop this");
    expect(queue.textContent).not.toContain("Do not drop this");
    expect(JSON.parse(window.localStorage.getItem(storageKey) ?? "[]")).toHaveLength(32);
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
    const acceptedMessage = {
      ...activeMessage,
      id: "00000000-0000-4000-8000-000000000008",
      content: "From this tab",
      sequence: 3,
      status: "queued" as const,
      queueState: "unclaimed" as const,
    };
    const sendMessage = vi.fn(async (
      _workspaceId: string,
      _conversationId: string,
      content: string,
    ) => {
      if (content === "From this tab") {
        return { conversationId, message: acceptedMessage, execution: null, replayed: false };
      }
      throw { kind: "timeout", status: 408 };
    });
    const deleteQueuedMessage = vi.fn(async () => ({
      ...acceptedMessage,
      content: "",
      status: "stopped" as const,
      queueState: null,
      deletedAt: "2026-08-20T16:01:02Z",
    }));
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
      sendMessage,
      deleteQueuedMessage,
    });

    await screen.findByText("First question", { selector: "article p, ol li span" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "From this tab" } });
    await clickSendMessage();
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    const remoteQueue = [{
      id: "queued-remote",
      content: "From another tab",
      intentKey: "message-remote",
      queuedAt: Date.now() + 1,
    }];
    window.dispatchEvent(new StorageEvent("storage", {
      key: storageKey,
      newValue: JSON.stringify(remoteQueue),
      storageArea: window.localStorage,
    }));

    const queue = await screen.findByRole("list", { name: "Queued messages" });
    await waitFor(() => {
      expect(queue.textContent).toContain("From this tab");
      expect(queue.textContent).toContain("From another tab");
    });
    const staleSnapshot = window.localStorage.getItem(storageKey);

    fireEvent.click(screen.getByRole("button", { name: "Remove queued message: From this tab" }));
    await waitFor(() => expect(deleteQueuedMessage).toHaveBeenCalledWith(
      account.workspace.id,
      conversationId,
      acceptedMessage.id,
      undefined,
    ));
    await waitFor(() => expect(screen.queryByText("From this tab")).toBeNull());
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
      expect(screen.queryByRole("list", { name: "Queued messages" })?.textContent ?? "")
        .not.toContain("From another tab");
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
    await screen.findByText("First question", { selector: "article p, ol li span" });
    expect(screen.queryByText("From this tab")).toBeNull();
    expect(screen.queryByText("From another tab")).toBeNull();
  });

  it("keeps an in-flight queued dispatch durable across a remount", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    let activeMessageStatus: "queued" | "completed" = "queued";
    let finishActiveTurn: ((snapshot: unknown) => void) | undefined;
    let rejectFirstDispatch: ((reason?: unknown) => void) | undefined;
    const completedSnapshot = {
      conversationId,
      activities: [],
      state: "completed" as const,
      lastContiguousSequence: 0,
    };
    const getActivities = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => {
        finishActiveTurn = resolve;
      }))
      .mockResolvedValue(completedSnapshot);
    const getAllyConversation = vi.fn(async () => ({
      id: conversationId,
      allyId: ally.id,
      messages: [{ ...activeMessage, status: activeMessageStatus }],
      nextCursor: null,
    }));
    const sendMessage = vi.fn()
      .mockImplementationOnce(() => new Promise((_resolve, reject) => {
        rejectFirstDispatch = reject;
      }))
      .mockResolvedValue({
        conversationId,
        message: {
          ...activeMessage,
          id: "00000000-0000-4000-8000-000000000008",
          content: "Second question",
          sequence: 3,
          status: "completed" as const,
        },
        execution: null,
        replayed: true,
      });
    const overrides = { getAllyConversation, getActivities, sendMessage };

    renderHome([ally], ally.id, overrides);
    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Second question" } });
    await clickSendMessage();

    await act(async () => {
      activeMessageStatus = "completed";
      finishActiveTurn?.(completedSnapshot);
    });
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    const firstIntentKey = sendMessage.mock.calls[0]?.[3];
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    await waitFor(() => expect(window.localStorage.getItem(storageKey)).toContain("Second question"));

    cleanup();
    await act(async () => {
      rejectFirstDispatch?.(new Error("connection lost during dispatch"));
      await Promise.resolve();
    });
    renderHome([ally], ally.id, overrides);

    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(2));
    expect(sendMessage.mock.calls[1]?.[3]).toBe(firstIntentKey);
    await waitFor(() => expect(window.localStorage.getItem(storageKey)).toBeNull());
  });

  it("lets the user remove a frontend-queued message", async () => {
    stubQueueMessageLocks();
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "in_progress" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    window.localStorage.setItem(storageKey, JSON.stringify([{
      id: "queued-local",
      content: "Never mind",
      intentKey: "intent-local",
      queuedAt: Date.now(),
    }]));
    const pendingAlly = { ...ally, provisioningState: "pending" as const };
    const sendMessage = vi.fn();
    renderHome([pendingAlly], pendingAlly.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
      sendMessage,
    });

    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
    expect(await screen.findByText("Never mind")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Remove queued message: Never mind" }));
    await waitFor(() => expect(screen.queryByText("Never mind")).toBeNull());
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("does not offer local queue removal without Web Locks", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    const queuedMessage = {
      id: "queued-no-lock",
      content: "Keep until Cloud accepts",
      intentKey: "intent-no-lock",
      queuedAt: Date.now(),
    };
    window.localStorage.setItem(storageKey, JSON.stringify([queuedMessage]));
    const pendingAlly = { ...ally, provisioningState: "pending" as const };
    renderHome([pendingAlly], pendingAlly.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [],
        nextCursor: null,
      })),
    });

    expect(await screen.findByText(queuedMessage.content)).toBeTruthy();
    expect(screen.queryByRole("button", { name: `Remove queued message: ${queuedMessage.content}` })).toBeNull();
    expect(window.localStorage.getItem(storageKey)).toContain(queuedMessage.content);
  });

  it("does not remove a local queue item after another tab marks its send attempted", async () => {
    stubQueueMessageLocks();
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    const queuedMessage = {
      id: "queued-stale-ref",
      content: "Keep after another tab starts",
      intentKey: "intent-stale-ref",
      queuedAt: Date.now(),
    };
    window.localStorage.setItem(storageKey, JSON.stringify([queuedMessage]));
    const pendingAlly = { ...ally, provisioningState: "pending" as const };
    const sendMessage = vi.fn();
    renderHome([pendingAlly], pendingAlly.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [],
        nextCursor: null,
      })),
      sendMessage,
    });

    expect(await screen.findByText(queuedMessage.content)).toBeTruthy();
    window.localStorage.setItem(storageKey, JSON.stringify([{
      ...queuedMessage,
      attemptedAt: Date.now(),
    }]));

    fireEvent.click(screen.getByRole("button", { name: `Remove queued message: ${queuedMessage.content}` }));

    expect((await screen.findByRole("alert")).textContent).toContain("couldn't remove this queued message");
    expect(screen.getByText(queuedMessage.content)).toBeTruthy();
    expect(window.localStorage.getItem(`${storageKey}:removed:${encodeURIComponent(queuedMessage.id)}`)).toBeNull();
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("keeps a queued message visible when its removal cannot be persisted", async () => {
    stubQueueMessageLocks();
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const activeMessage = {
      id: "00000000-0000-4000-8000-000000000007",
      sender: "user" as const,
      content: "First question",
      sequence: 2,
      status: "in_progress" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const storageKey = `allies:v2:queued-messages:${account.userId}:${account.workspace.id}:${ally.id}`;
    window.localStorage.setItem(storageKey, JSON.stringify([{
      id: "queued-local",
      content: "Keep this queued",
      intentKey: "intent-local",
      queuedAt: Date.now(),
    }]));
    const pendingAlly = { ...ally, provisioningState: "pending" as const };
    const sendMessage = vi.fn();
    renderHome([pendingAlly], pendingAlly.id, {
      getAllyConversation: vi.fn(async () => ({
        id: conversationId,
        allyId: ally.id,
        messages: [activeMessage],
        nextCursor: null,
      })),
      getActivities: vi.fn(() => new Promise(() => undefined)),
      sendMessage,
    });

    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
    const queue = await screen.findByRole("list", { name: "Queued messages" });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    try {
      fireEvent.click(screen.getByRole("button", { name: "Remove queued message: Keep this queued" }));

      expect((await screen.findByRole("alert")).textContent).toContain("couldn't remove this queued message");
      expect(queue.textContent).toContain("Keep this queued");
      expect(sendMessage).not.toHaveBeenCalled();
    } finally {
      setItem.mockRestore();
    }
  });

  it("retries an ambiguous queued acceptance after an unmount", async () => {
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

    expect(await screen.findByText("First question", { selector: "article p, ol li span" })).toBeTruthy();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "Keep me waiting" } });
    await clickSendMessage();
    expect(await screen.findByText("Keep me waiting")).toBeTruthy();
    await waitFor(() => expect(window.localStorage.length).toBe(1));

    cleanup();
    renderHome([ally], ally.id, overrides);

    expect(await screen.findByText("Keep me waiting")).toBeTruthy();
    expect(screen.getByRole("list", { name: "Queued messages" })).toBeTruthy();
    await waitFor(() => expect(overrides.sendMessage).toHaveBeenCalledTimes(2));
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
    expect(await screen.findAllByText("Still waiting")).toHaveLength(2);
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

  it("keeps durable replies moving while the activity stream is connected", async () => {
    vi.stubEnv("NEXT_PUBLIC_ACTIVITY_SSE_ENABLED", "true");
    vi.stubEnv("NEXT_PUBLIC_RESPONSE_PRESENTATION_MODE", "stream");
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const acceptedMessage = {
      id: "00000000-0000-4000-8000-000000000018",
      sender: "user" as const,
      content: "Keep the durable reply moving",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const durableReply = (content: string, updatedAt: string) => ({
      id: "00000000-0000-4000-8000-000000000019",
      sourceMessageId: acceptedMessage.id,
      conversationTurnOrdinal: acceptedMessage.sequence,
      content,
      status: "in_progress" as const,
      hasFullPrefix: true,
      createdAt: "2026-08-20T16:01:01Z",
      updatedAt,
    });
    const getActivities = vi.fn()
      .mockResolvedValueOnce({
        conversationId,
        activities: [],
        state: "completed" as const,
        lastContiguousSequence: 0,
      })
      .mockRejectedValueOnce(new Error("temporary snapshot failure"))
      .mockResolvedValueOnce({
        conversationId,
        activities: [],
        assistantReply: durableReply("The durable answer recovered.", "2026-08-20T16:01:03Z"),
        state: "running" as const,
        lastContiguousSequence: 0,
      });
    const sendMessage = vi.fn(async () => ({
      conversationId,
      message: acceptedMessage,
      execution: null,
      replayed: false,
    }));
    let openStream: (() => void) | undefined;
    let closeStream: ReturnType<typeof vi.fn> | undefined;
    readActivityStreamMock.mockImplementation((options: { onOpen?: () => void }) => {
      openStream = options.onOpen;
      closeStream = vi.fn();
      return { close: closeStream };
    });
    renderHome([ally], ally.id, { getActivities, sendMessage });

    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: acceptedMessage.content } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    await waitFor(() => expect(readActivityStreamMock).toHaveBeenCalledOnce());

    await act(async () => {
      openStream?.();
    });
    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(2), {
      timeout: 4_000,
      interval: 50,
    });
    expect(closeStream).not.toHaveBeenCalled();
    await waitFor(() => expect(getActivities).toHaveBeenCalledTimes(3), {
      timeout: 4_000,
      interval: 50,
    });
    expect(screen.getByTestId("activity-reply-2").textContent).toContain("The durable answer recovered.");
    expect(closeStream).not.toHaveBeenCalled();
  }, 10_000);

  it("projects a delayed prior-turn approval from the activity stream without another approval-list read", async () => {
    vi.stubEnv("NEXT_PUBLIC_ACTIVITY_SSE_ENABLED", "true");
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const acceptedMessage = {
      id: "00000000-0000-4000-8000-000000000018",
      sender: "user" as const,
      content: "Do the protected action",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const priorMessageId = "00000000-0000-4000-8000-000000000006";
    const approvalId = "00000000-0000-4000-8000-000000000020";
    const approvalDetail = {
      id: approvalId,
      messageId: priorMessageId,
      status: "pending" as const,
      expiresAt: "2099-01-01T00:05:00Z",
      decidedAt: null,
      acknowledgementDeadlineAt: null,
      actionLabel: "Run code",
      actionPreview: "Run the protected action",
    };
    const getApprovals = vi.fn(async () => []);
    const getApproval = vi.fn(async () => approvalDetail);
    const sendMessage = vi.fn(async () => ({
      conversationId,
      message: acceptedMessage,
      execution: null,
      replayed: false,
    }));
    readActivityStreamMock.mockImplementation(() => ({ close: vi.fn() }));
    renderHome([ally], ally.id, { getApprovals, getApproval, sendMessage });

    await waitFor(() => expect(getApprovals).toHaveBeenCalledOnce());
    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: acceptedMessage.content } });
    await clickSendMessage();
    await waitFor(() => expect(readActivityStreamMock).toHaveBeenCalledOnce());

    const stream = readActivityStreamMock.mock.calls[0][0] as ActivityStreamOptions;
    await act(async () => {
      stream.onOpen?.();
      stream.onEvent({
        type: "activity",
        conversationId,
        cursor: "cursor-approval",
        activity: {
          id: "00000000-0000-4000-8000-000000000021",
          messageId: priorMessageId,
          sequence: 1,
          conversationTurnOrdinal: 1,
          kind: "awaiting_action",
          text: "Approval needed",
          state: "awaiting_action",
          createdAt: "2026-08-20T16:01:01Z",
          approval: {
            id: approvalId,
            status: "pending",
            expiresAt: approvalDetail.expiresAt,
            decidedAt: null,
          },
        },
      });
    });

    expect(await screen.findByRole("button", { name: "Approval needed" })).toBeTruthy();
    expect(getApprovals).toHaveBeenCalledOnce();
    expect(getApproval).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Approval needed" }));
    expect(await screen.findByText(approvalDetail.actionPreview)).toBeTruthy();
    expect(getApproval).toHaveBeenCalledOnce();
  });

  it.each(["error", "mismatch"])("keeps healthy SSE open and grants bounded fallback after companion exhaustion (%s)", async (failure) => {
    vi.stubEnv("NEXT_PUBLIC_ACTIVITY_SSE_ENABLED", "true");
    vi.stubEnv("NEXT_PUBLIC_CLOUD_API_URL", "https://cloud.example.com");
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const acceptedMessage = {
      id: "00000000-0000-4000-8000-000000000020",
      sender: "user" as const,
      content: "Keep the stream alive",
      sequence: 2,
      status: "queued" as const,
      createdAt: "2026-08-20T16:01:00Z",
    };
    const getActivities = vi.fn(async () => ({
      conversationId,
      activities: [],
      state: "running" as const,
      lastContiguousSequence: 0,
    }));
    const sendMessage = vi.fn(async () => ({
      conversationId,
      message: acceptedMessage,
      execution: null,
      replayed: false,
    }));
    let openStream: (() => void) | undefined;
    let closeStream: ReturnType<typeof vi.fn> | undefined;
    readActivityStreamMock.mockImplementation((options: { onOpen?: () => void }) => {
      openStream = options.onOpen;
      closeStream = vi.fn();
      return { close: closeStream };
    });
    renderHome([ally], ally.id, { getActivities, sendMessage });

    await waitFor(() => expect(getActivities).toHaveBeenCalledOnce());
    const input = await screen.findByRole("textbox");
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: acceptedMessage.content } });
    await clickSendMessage();
    await waitFor(() => expect(sendMessage).toHaveBeenCalledOnce());
    await waitFor(() => expect(readActivityStreamMock).toHaveBeenCalledOnce());

    let companionPoll: (() => void) | undefined;
    const browserTimers: Window = window;
    const originalSetInterval = browserTimers.setInterval.bind(browserTimers);
    const setIntervalSpy = vi.spyOn(browserTimers, "setInterval").mockImplementation((handler, timeout) => {
      if (timeout === 3_000 && typeof handler === "function") {
        companionPoll = handler as () => void;
        return originalSetInterval(() => undefined, 60_000);
      }
      return originalSetInterval(handler, timeout);
    });
    try {
      await act(async () => {
        openStream?.();
      });
      await waitFor(() => expect(companionPoll).toEqual(expect.any(Function)));

      await act(async () => {
        for (let index = 0; index < 241; index += 1) {
          companionPoll?.();
          await Promise.resolve();
          await Promise.resolve();
          await Promise.resolve();
          await Promise.resolve();
        }
      });
      expect(getActivities.mock.calls.length).toBeGreaterThanOrEqual(241);
      expect(closeStream).not.toHaveBeenCalled();
      expect(screen.getByText("Status checking is paused.")).toBeTruthy();
      expect(screen.getByRole("status", { name: "Thinking" })).toBeTruthy();
      const readsBeforeFallback = getActivities.mock.calls.length;
      const streamOptions = readActivityStreamMock.mock.calls[0][0] as ActivityStreamOptions;
      await act(async () => {
        if (failure === "error") {
          streamOptions.onError?.(new Error("Disconnected"));
        } else {
          streamOptions.onEvent({ type: "error", conversationId: "another-conversation", code: "mismatch" });
        }
      });
      await waitFor(() => expect(getActivities.mock.calls.length).toBeGreaterThan(readsBeforeFallback));
      expect(screen.queryByText("Status checking is paused.")).toBeNull();
      expect(screen.queryByText("Live updates paused. Checking again…")).toBeNull();
      expect(readActivityStreamMock).toHaveBeenCalledOnce();
    } finally {
      cleanup();
      setIntervalSpy.mockRestore();
    }
  }, 10_000);

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
    expect(screen.getByTestId("conversation-ally").getAttribute("data-state")).toBe("idle");
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

  it("renders markdown structure once an Ally response is completed", async () => {
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
          state: "completed" as const,
          createdAt: "2026-08-20T16:01:01Z",
        }],
        state: "completed" as const,
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
    expect(screen.queryByText("This response failed.")).toBeNull();
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

    expect(await screen.findByText("This response failed.")).toBeTruthy();
    expect(screen.queryByText(/secret runtime detail/i)).toBeNull();
  });

  it("releases a sent routine-action lock after its bounded retry window", async () => {
    const conversationId = "00000000-0000-4000-8000-000000000005";
    const routineId = "00000000-0000-4000-8000-000000000010";
    const routineItem: RoutineChatItemViewModel = {
      id: routineId,
      kind: "created",
      routineId,
      conversationId,
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
      responsibleAllyId: ally.id,
      title: routineItem.titleSnapshot,
      schedule: routineItem.schedule,
      revision: routineItem.routineRevision,
      scheduleGeneration: routineItem.scheduleGeneration,
      scheduleState: "active",
      nextRunAt: "2026-09-10T09:30:00Z",
      createdAt: routineItem.occurredAt,
      updatedAt: routineItem.occurredAt,
      workspaceId: account.workspace.id,
      ownerUserId: account.userId,
      bindingId: ally.bindingId,
      mainConversationId: conversationId,
      executionPrompt: "Check the latest brief and report any changes.",
    };
    const sendMessage = vi.fn(async (_workspaceId: string, _conversationId: string, content: string) => ({
      conversationId,
      message: {
        id: "00000000-0000-4000-8000-000000000011",
        sender: "user" as const,
        content,
        sequence: 2,
        status: "queued" as const,
        queueState: "unclaimed" as const,
        createdAt: "2026-09-09T08:01:00Z",
      },
      execution: null,
      replayed: false,
    }));
    const conversation: ConversationViewModel = {
      id: conversationId,
      allyId: ally.id,
      messages: [{
        id: "00000000-0000-4000-8000-000000000006",
        sender: "assistant",
        content: "What should we work on first?",
        sequence: 1,
        status: "completed",
        createdAt: "2026-09-09T08:00:00Z",
      }],
      assistantReplies: [],
      routineItems: [routineItem],
      nextCursor: null,
    };
    renderHome([ally], ally.id, {
      getAllyConversation: vi.fn(async () => conversation),
      getRoutine: vi.fn(async () => detail),
      sendMessage,
    });

    fireEvent.click(await screen.findByRole("button", { name: /Morning brief/ }));
    const pause = await screen.findByRole("button", { name: "Pause" }) as HTMLButtonElement;
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      fireEvent.click(pause);
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(sendMessage).toHaveBeenCalledOnce();
      expect(pause.disabled).toBe(true);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ROUTINE_ACTION_SENT_TIMEOUT_MS - 1);
      });
      expect(pause.disabled).toBe(true);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(pause.disabled).toBe(false);
    } finally {
      vi.useRealTimers();
    }
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
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("restores the saved scroll anchor on reload instead of jumping to latest", async () => {
    window.sessionStorage.setItem(
      "allies:scroll:workspace:00000000-0000-4000-8000-000000000005",
      JSON.stringify({ atBottom: false, messageId: "00000000-0000-4000-8000-000000000006", sequence: 1, offsetPx: 40, updatedAt: Date.now() }),
    );
    const offsetTops = new Map<string, number>([["00000000-0000-4000-8000-000000000006", 500]]);
    const descriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetTop");
    Object.defineProperty(HTMLElement.prototype, "offsetTop", {
      configurable: true,
      get(this: HTMLElement) {
        return offsetTops.get(this.dataset.messageId ?? "") ?? 0;
      },
    });
    try {
      renderHome([ally], ally.id);
      const canvas = await screen.findByTestId("conversation-frame-canvas");
      const scrollTo = vi.fn();
      Object.defineProperties(canvas, {
        scrollHeight: { configurable: true, value: 2000 },
        clientHeight: { configurable: true, value: 400 },
        scrollTop: { configurable: true, value: 0, writable: true },
        scrollTo: { configurable: true, value: scrollTo },
      });
      await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 540 }));
    } finally {
      window.sessionStorage.clear();
      if (descriptor) Object.defineProperty(HTMLElement.prototype, "offsetTop", descriptor);
    }
  });

  it("falls back to the latest message when no scroll anchor was saved", async () => {
    window.sessionStorage.clear();
    renderHome([ally], ally.id);
    const canvas = await screen.findByTestId("conversation-frame-canvas");
    const scrollTo = vi.fn();
    Object.defineProperties(canvas, {
      scrollHeight: { configurable: true, value: 2000 },
      clientHeight: { configurable: true, value: 400 },
      scrollTop: { configurable: true, value: 0, writable: true },
      scrollTo: { configurable: true, value: scrollTo },
    });
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 2000 }));
  });

  it("falls back to the oldest loaded message when the anchor aged out of the window", async () => {
    window.sessionStorage.setItem(
      "allies:scroll:workspace:00000000-0000-4000-8000-000000000005",
      JSON.stringify({ atBottom: false, messageId: "00000000-0000-4000-8000-000000000000", sequence: 0, offsetPx: 0, updatedAt: Date.now() }),
    );
    try {
      renderHome([ally], ally.id);
      const canvas = await screen.findByTestId("conversation-frame-canvas");
      const scrollTo = vi.fn();
      Object.defineProperties(canvas, {
        scrollHeight: { configurable: true, value: 2000 },
        clientHeight: { configurable: true, value: 400 },
        scrollTop: { configurable: true, value: 0, writable: true },
        scrollTo: { configurable: true, value: scrollTo },
      });
      await waitFor(() => expect(scrollTo).toHaveBeenCalledWith({ top: 0 }));
    } finally {
      window.sessionStorage.clear();
    }
  });
});

describe("buildQueuedFrameMessages", () => {
  const cloudMessage = (overrides: Partial<MessageViewModel> = {}): MessageViewModel => ({
    id: "cloud-1",
    sender: "user",
    content: "Review this",
    sequence: 2,
    status: "queued",
    queueState: "unclaimed",
    createdAt: "2026-09-06T12:00:00Z",
    ...overrides,
  });

  it("carries cloud file previews into the queue", () => {
    const items = buildQueuedFrameMessages(
      [cloudMessage({
        files: [
          { id: "00000000-0000-4000-8000-000000000001", name: "a.pdf", size: 76600, state: "ready" },
          { id: "00000000-0000-4000-8000-000000000002", name: "b.png", size: 1200, state: "retained" },
        ],
      })],
      [],
      null,
      false,
    );
    expect(items).toEqual([{
      id: "cloud-1",
      content: "Review this",
      removable: true,
      statusLabel: null,
      attachments: [
        { id: "00000000-0000-4000-8000-000000000001", name: "a.pdf", ready: true },
        { id: "00000000-0000-4000-8000-000000000002", name: "b.png", ready: true },
      ],
    }]);
  });

  it("resolves local file previews without reordering the queue", () => {
    const items = buildQueuedFrameMessages(
      [],
      [
        { id: "queued-text", content: "First", intentKey: "key-1", queuedAt: 1 },
        { id: "queued-files", content: "Second", intentKey: "key-2", queuedAt: 2, fileTransferId: "11111111-1111-4111-8111-111111111111" },
      ],
      null,
      false,
      true,
      (fileTransferId) => fileTransferId === "11111111-1111-4111-8111-111111111111"
        ? {
          files: [{ id: "local-1", name: "c.pdf", src: "blob:c", ready: true, local: true as const }],
          status: "Uploading 42%",
        }
        : null,
    );
    expect(items.map((item) => item.id)).toEqual(["queued-text", "queued-files"]);
    expect(items[1]).toMatchObject({
      attachments: [{ id: "local-1", name: "c.pdf", src: "blob:c", ready: true }],
      statusLabel: "Uploading 42%",
    });
    expect(items[0]).toMatchObject({ statusLabel: null });
    expect(items[0]).not.toHaveProperty("attachments");
  });

  it("labels uploading cloud file pills when no local transfer is visible", () => {
    const items = buildQueuedFrameMessages(
      [cloudMessage({
        preparation: "uploading",
        files: [
          { id: "00000000-0000-4000-8000-000000000001", name: "a.pdf", size: 76600, state: "pending" },
        ],
      })],
      [],
      null,
      false,
    );
    expect(items[0]).toMatchObject({ statusLabel: "Uploading…" });
  });
});

describe("queuedAttachmentQueueIds", () => {
  const fileMessage = (overrides: Partial<MessageViewModel> = {}): MessageViewModel => ({
    id: "file-1",
    sender: "user",
    content: "Review this",
    sequence: 2,
    status: "queued",
    queueState: "unclaimed",
    createdAt: "2026-09-06T12:00:00Z",
    files: [{ id: "00000000-0000-4000-8000-000000000001", name: "a.pdf", size: 76600, state: "ready" }],
    ...overrides,
  });

  it("keeps waiting file messages in the queue, including ones still uploading", () => {
    const waiting = fileMessage({ id: "waiting" });
    const uploading = fileMessage({
      id: "uploading",
      preparation: "uploading",
      files: [{ id: "00000000-0000-4000-8000-000000000001", name: "a.pdf", size: 76600, state: "pending" }],
    });
    const sent = fileMessage({ id: "sent", status: "completed" });
    expect(queuedAttachmentQueueIds([waiting, uploading, sent], null)).toEqual(new Set(["waiting", "uploading"]));
  });

  it("keeps failed, claimed, and active file messages in the timeline", () => {
    const failed = fileMessage({ id: "cloud-failed", preparation: "failed" });
    const claimed = fileMessage({ id: "cloud-claimed", preparation: "ready", queueState: "claimed" });
    const active = fileMessage({ id: "cloud-active", preparation: "ready" });
    const waiting = fileMessage({ id: "cloud-waiting", preparation: "ready" });
    expect(queuedAttachmentQueueIds([failed, claimed, active, waiting], "cloud-active")).toEqual(new Set(["cloud-waiting"]));
  });

  it("ignores text-only queued messages", () => {
    const textOnly: MessageViewModel = {
      id: "text",
      sender: "user",
      content: "Just words",
      sequence: 2,
      status: "queued",
      queueState: "unclaimed",
      createdAt: "2026-09-06T12:00:00Z",
    };
    expect(queuedAttachmentQueueIds([textOnly], null)).toEqual(new Set());
  });
});

describe("localTransferQueueStatus", () => {
  it.each([
    ["uploading", [{ state: "pending", progress: 99 }], "Uploading 99%"],
    ["uploading", [{ state: "pending", progress: 40 }, { state: "pending", progress: 80 }], "Uploading 40%"],
    ["uploading", [{ state: "receiving", progress: 50 }], "Checking file…"],
    ["uploading", [{ state: "validating", progress: 50 }], "Checking file…"],
    ["uploading", [{ state: "ready", progress: 100 }], null],
    ["checking", [{ state: "pending", progress: 10 }], "Checking file…"],
    ["failed", [{ state: "pending", progress: 10 }], "Needs attention"],
    ["ready", [{ state: "ready", progress: 100 }], null],
    ["cancelled", [{ state: "pending", progress: 10 }], null],
  ])("maps %s transfer state to %s", (phase, files, expected) => {
    expect(localTransferQueueStatus({ phase, files })).toBe(expected);
  });
});
