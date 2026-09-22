// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApprovalDetail } from "@allies/cloud-client";
import { ConversationApprovalSlot, ConversationApprovals, approvalStatusAt, mergeApprovalSummaries, pruneDecisionIntents, type ApprovalClient } from "./conversation-approvals";

const approval: ApprovalDetail = {
  id: "e9cfec70-9140-4e08-8ba7-42c6edce5142",
  messageId: "75ce0467-b673-46cb-bcf9-dd02b1d5c16d",
  status: "pending", expiresAt: new Date(Date.now() + 300_000).toISOString(),
  decidedAt: null, acknowledgementDeadlineAt: null,
  actionLabel: "Connect a knowledge space", actionPreview: "Connect to the selected knowledge space using the supplied credential.",
};

afterEach(cleanup);
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); this.querySelector<HTMLButtonElement>("button")?.focus(); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});

function setup(overrides: Partial<ApprovalClient> = {}, canApprove = true, children?: ReactNode, activityApprovals: ApprovalDetail[] = [], liveUpdatesConnected = false) {
  const client: ApprovalClient = {
    getApprovals: vi.fn().mockResolvedValue([approval]),
    getApproval: vi.fn().mockResolvedValue(approval),
    decideApproval: vi.fn().mockResolvedValue({ ...approval, status: "decision_recorded", decidedAt: new Date().toISOString(), acknowledgementDeadlineAt: new Date(Date.now() + 30_000).toISOString() }),
    ...overrides,
  };
  const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove={canApprove} activityApprovals={activityApprovals} liveUpdatesConnected={liveUpdatesConnected}>{children}</ConversationApprovals></QueryClientProvider>);
  return client;
}

describe("conversation approvals", () => {
  it("does not let stale activity regress a hydrated terminal approval", () => {
    expect(mergeApprovalSummaries(
      [{ ...approval, status: "approved" }],
      [approval],
      {},
    )[0]?.status).toBe("approved");
  });

  it("does not carry a locally recorded approval into another conversation", async () => {
    const recorded = {
      ...approval,
      status: "decision_recorded" as const,
      decidedAt: new Date().toISOString(),
      acknowledgementDeadlineAt: new Date(Date.now() + 30_000).toISOString(),
    };
    const client: ApprovalClient = {
      getApprovals: vi.fn(async (_workspace, conversation) => conversation === "conversation-a" ? [approval] : []),
      getApproval: vi.fn().mockResolvedValue(approval),
      decideApproval: vi.fn().mockResolvedValue(recorded),
    };
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const content = (conversationId: string) => <QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId={conversationId} allyName="Shaka" accent="#ff5800" canApprove /></QueryClientProvider>;
    const view = render(content("conversation-a"));

    fireEvent.click(await screen.findByRole("button", { name: "Approval needed" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("button", { name: "Decision recorded · Waiting for Ally" })).toBeTruthy();

    view.rerender(content("conversation-b"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Decision recorded · Waiting for Ally" })).toBeNull());
  });

  it("shows an activity approval before initial hydration completes and fetches detail only when opened", async () => {
    const getApprovals = vi.fn(() => new Promise<ApprovalDetail[]>(() => undefined));
    const getApproval = vi.fn().mockResolvedValue(approval);
    setup({ getApprovals, getApproval }, true, undefined, [approval], true);

    expect(await screen.findByRole("button", { name: "Approval needed" })).toBeTruthy();
    expect(getApprovals).toHaveBeenCalledOnce();
    expect(getApproval).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Approval needed" }));
    await screen.findByText(approval.actionPreview);
    expect(getApproval).toHaveBeenCalledOnce();
  });

  it("suppresses unresolved approval polling while live updates are connected and resumes after disconnect", async () => {
    vi.useFakeTimers();
    try {
      const getApprovals = vi.fn().mockResolvedValue([approval]);
      const client: ApprovalClient = {
        getApprovals,
        getApproval: vi.fn().mockResolvedValue(approval),
        decideApproval: vi.fn(),
      };
      const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
      const content = (connected: boolean) => <QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove activityApprovals={[approval]} liveUpdatesConnected={connected} /></QueryClientProvider>;
      const view = render(content(true));
      await act(async () => {
        await Promise.resolve();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(getApprovals).toHaveBeenCalledOnce();

      await act(async () => { await vi.advanceTimersByTimeAsync(9_000); });
      expect(getApprovals).toHaveBeenCalledOnce();

      view.rerender(content(false));
      await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
      expect(getApprovals).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("applies streamed status changes once without another list read", async () => {
    const getApprovals = vi.fn().mockResolvedValue([]);
    const client: ApprovalClient = {
      getApprovals,
      getApproval: vi.fn().mockResolvedValue(approval),
      decideApproval: vi.fn(),
    };
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const content = (status: ApprovalDetail["status"]) => <QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove activityApprovals={[{ ...approval, status }]} liveUpdatesConnected /></QueryClientProvider>;
    const view = render(content("pending"));
    expect(await screen.findByRole("button", { name: "Approval needed" })).toBeTruthy();

    view.rerender(content("approved"));
    expect(await screen.findByRole("button", { name: "Approved" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approval needed" })).toBeNull();
    expect(document.querySelectorAll(`[data-approval-id="${approval.id}"]`)).toHaveLength(1);
    expect(getApprovals).toHaveBeenCalledOnce();
  });

  it("retains unresolved intent across a long history and prunes only confirmed terminal IDs", () => {
    const intents = Object.fromEntries(Array.from({ length: 60 }, (_, index) => [String(index), { decision: "approve" as const, key: String(index) }]));
    const pruned = pruneDecisionIntents(intents, [{ ...approval, id: "59", status: "approved" }]);
    expect(pruned["0"]).toEqual(intents["0"]);
    expect(pruned["59"]).toBeUndefined();
    expect(Object.keys(pruned)).toHaveLength(59);
  });
  it("shows fixed summary copy and keeps technical details closed until opened", async () => {
    const client = setup();
    fireEvent.click(await screen.findByRole("button", { name: "Approval needed" }));
    await screen.findByText(approval.actionPreview);
    expect(screen.getByText("Your Ally is requesting permission to perform an action.")).toBeTruthy();
    const technical = screen.getByText("View technical details", { exact: true }).closest("details");
    expect(technical?.open).toBe(false);
    fireEvent.click(screen.getByText("View technical details", { exact: true }));
    expect(technical?.open).toBe(true);
    fireEvent.click(screen.getByText("View technical details", { exact: true }));
    expect(technical?.open).toBe(false);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close" }));
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: false, cancelable: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(client.decideApproval).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Approval needed" }));
    await screen.findByRole("dialog");
  });

  it("records once on duplicate taps and waits for runtime acknowledgement", async () => {
    let finish!: (value: ApprovalDetail) => void;
    const decideApproval = vi.fn(() => new Promise<ApprovalDetail>((resolve) => { finish = resolve; }));
    setup({ decideApproval });
    fireEvent.click(await screen.findByRole("button", { name: "Approval needed" }));
    const approve = await screen.findByRole("button", { name: "Approve" });
    fireEvent.click(approve); fireEvent.click(approve);
    expect(decideApproval).toHaveBeenCalledTimes(1);
    await act(async () => finish({ ...approval, status: "decision_recorded", decidedAt: new Date().toISOString(), acknowledgementDeadlineAt: new Date(Date.now() + 30_000).toISOString() }));
    await screen.findByText("Decision recorded · Waiting for Ally");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Decision recorded · Waiting for Ally" })));
    fireEvent.click(screen.getByRole("button", { name: "Decision recorded · Waiting for Ally" }));
    await screen.findByRole("dialog");
  });

  it("restores focus to a terminal approval history row", async () => {
    const approved = { ...approval, status: "approved" as const, decidedAt: new Date().toISOString() };
    setup({ decideApproval: vi.fn().mockResolvedValue(approved) });
    fireEvent.click(await screen.findByRole("button", { name: "Approval needed" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Approved" }));
    });
  });

  it("places an approval beside its message and keeps unmatched approvals in the fallback slot", async () => {
    setup({}, true, <>
      <section aria-label="matching"><ConversationApprovalSlot messageId={approval.messageId} /></section>
      <section aria-label="other"><ConversationApprovalSlot messageId="other-message" /></section>
      <section aria-label="fallback"><ConversationApprovalSlot visibleMessageIds={new Set([approval.messageId])} /></section>
    </>);
    await screen.findByRole("button", { name: "Approval needed" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("region", { name: "matching" }).textContent).toContain("Approval needed");
    expect(screen.getByRole("region", { name: "other" }).textContent).toBe("");
    expect(screen.getByRole("region", { name: "fallback" }).textContent).toBe("");
  });

  it("moves two approvals exactly once between fallback, active, and historical slots", async () => {
    const second = { ...approval, id: "second-approval", messageId: "second-message" };
    const client: ApprovalClient = {
      getApprovals: vi.fn().mockResolvedValue([approval, second]),
      getApproval: vi.fn().mockImplementation(async (_workspace, _conversation, id) => id === second.id ? second : approval),
      decideApproval: vi.fn(),
    };
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const slots = (phase: "missing" | "active" | "historical") => <>
      <section aria-label="active">{phase === "active" ? <ConversationApprovalSlot messageId={approval.messageId} /> : null}</section>
      <section aria-label="historical">{phase === "historical" ? <ConversationApprovalSlot messageId={approval.messageId} /> : null}<ConversationApprovalSlot messageId={second.messageId} /></section>
      <section aria-label="fallback"><ConversationApprovalSlot visibleMessageIds={new Set(phase === "missing" ? [second.messageId] : [approval.messageId, second.messageId])} /></section>
    </>;
    const view = render(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove>{slots("missing")}</ConversationApprovals></QueryClientProvider>);
    const initialButtons = await screen.findAllByRole("button", { name: "Approval needed" });
    expect(initialButtons).toHaveLength(2);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(view.container.querySelectorAll(`[data-approval-id="${approval.id}"]`)).toHaveLength(1);
    expect(screen.getByRole("region", { name: "fallback" }).textContent).toContain("Approval needed");
    view.rerender(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove>{slots("active")}</ConversationApprovals></QueryClientProvider>);
    expect(view.container.querySelectorAll(`[data-approval-id="${approval.id}"]`)).toHaveLength(1);
    expect(screen.getByRole("region", { name: "active" }).textContent).toContain("Approval needed");
    view.rerender(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove>{slots("historical")}</ConversationApprovals></QueryClientProvider>);
    expect(view.container.querySelectorAll(`[data-approval-id="${approval.id}"]`)).toHaveLength(1);
    expect(view.container.querySelectorAll(`[data-approval-id="${second.id}"]`)).toHaveLength(1);
    expect(screen.getByRole("region", { name: "historical" }).textContent).toContain("Approval needed");
  });

  it("hides cached approval UI as soon as access is disabled", async () => {
    const client: ApprovalClient = { getApprovals: vi.fn().mockResolvedValue([approval]), getApproval: vi.fn().mockResolvedValue(approval), decideApproval: vi.fn() };
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const view = render(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove><ConversationApprovalSlot messageId={approval.messageId} /></ConversationApprovals></QueryClientProvider>);
    await screen.findByRole("button", { name: "Approval needed" });
    fireEvent.click(screen.getByRole("button", { name: "Approval needed" }));
    await screen.findByRole("dialog");
    view.rerender(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove enabled={false}><ConversationApprovalSlot messageId={approval.messageId} /></ConversationApprovals></QueryClientProvider>);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(view.container.querySelector(`[data-approval-id="${approval.id}"]`)).toBeNull();
  });

  it("hides a cached approval error as soon as access is disabled", async () => {
    const client: ApprovalClient = { getApprovals: vi.fn().mockRejectedValue(new Error("denied")), getApproval: vi.fn(), decideApproval: vi.fn() };
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const view = render(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove /></QueryClientProvider>);
    await screen.findByText("Could not check this approval. Try again.");
    view.rerender(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove enabled={false} /></QueryClientProvider>);
    expect(screen.queryByText("Could not check this approval. Try again.")).toBeNull();
  });

  it("keeps cached approvals through transient poll failures and waits before toasting", async () => {
    const getApprovals = vi.fn()
      .mockResolvedValueOnce([approval])
      .mockRejectedValue({ kind: "network" });
    const client: ApprovalClient = {
      getApprovals,
      getApproval: vi.fn().mockResolvedValue(approval),
      decideApproval: vi.fn(),
    };
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    render(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove><ConversationApprovalSlot messageId={approval.messageId} /></ConversationApprovals></QueryClientProvider>);
    await screen.findByRole("button", { name: "Approval needed" });
    expect(screen.queryByRole("dialog")).toBeNull();

    for (let attempt = 1; attempt <= 3; attempt += 1) {
      await query.refetchQueries({ queryKey: ["workspaces", "workspace", "approvals", "conversation"] });
      expect(screen.getByRole("button", { name: "Approval needed" })).toBeTruthy();
      if (attempt < 3) expect(screen.queryByText("Could not check approvals after several attempts. Try again.")).toBeNull();
      await new Promise((resolve) => setTimeout(resolve, 2));
    }

    expect(await screen.findByText("Could not check approvals after several attempts. Try again.")).toBeTruthy();
  });

  it("retries an uncertain response with the same choice and idempotency key", async () => {
    const decideApproval = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValue({ ...approval, status: "rejected" });
    setup({ decideApproval });
    fireEvent.click(await screen.findByRole("button", { name: "Approval needed" }));
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    await screen.findByRole("alert");
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(decideApproval).toHaveBeenCalledTimes(2));
    expect(decideApproval.mock.calls[0].slice(0, 5)).toEqual(decideApproval.mock.calls[1].slice(0, 5));
  });

  it("prevents read-only decisions", async () => {
    const client = setup({}, false);
    fireEvent.click(await screen.findByRole("button", { name: "Approval needed" }));
    const approve = await screen.findByRole("button", { name: "Approve" });
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(approve);
    expect(client.decideApproval).not.toHaveBeenCalled();
  });

  it("keeps an uncertain choice and key when dismissed and reopened", async () => {
    const decideApproval = vi.fn().mockImplementationOnce(() => new Promise(() => undefined)).mockResolvedValue({ ...approval, status: "decision_recorded" });
    setup({ decideApproval });
    fireEvent.click(await screen.findByRole("button", { name: "Approval needed" }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: /^Close$/ }));
    fireEvent.click(screen.getByRole("button", { name: "Approval needed" }));
    const reject = await screen.findByRole("button", { name: "Reject" });
    expect((reject as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(reject);
    expect(decideApproval).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(decideApproval).toHaveBeenCalledTimes(2));
    expect(decideApproval.mock.calls[0].slice(0, 5)).toEqual(decideApproval.mock.calls[1].slice(0, 5));
  });

  it("prefers a confirmed terminal detail over an older recorded summary", async () => {
    setup({
      getApprovals: vi.fn().mockResolvedValue([{ ...approval, status: "decision_recorded", acknowledgementDeadlineAt: new Date(0).toISOString() }]),
      getApproval: vi.fn().mockResolvedValue({ ...approval, status: "approved" }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Decision recorded; Ally outcome could not be confirmed" }));
    await screen.findByText(approval.actionPreview);
    expect(screen.getByRole("dialog").textContent).toContain("Approved");
    expect(screen.getByRole("dialog").textContent).not.toContain("could not be confirmed");
  });

  it("applies exact expiry and acknowledgement deadlines without claiming success", () => {
    const expires = Date.parse(approval.expiresAt);
    expect(approvalStatusAt(approval, expires - 1)).toBe("pending");
    expect(approvalStatusAt(approval, expires)).toBe("expired");
    expect(approvalStatusAt({ ...approval, status: "decision_recorded", acknowledgementDeadlineAt: approval.expiresAt }, expires)).toBe("outcome_unknown");
  });

  it("stops summary and detail polling after a pending approval expires", async () => {
    vi.useFakeTimers();
    try {
      const start = Date.now();
      const expiring = { ...approval, expiresAt: new Date(start + 1_000).toISOString() };
      const getApprovals = vi.fn().mockResolvedValue([expiring]);
      const getApproval = vi.fn().mockResolvedValue(expiring);
      setup({ getApprovals, getApproval });
      await act(async () => {
        await Promise.resolve();
        await vi.advanceTimersByTimeAsync(0);
      });
      fireEvent.click(screen.getByRole("button", { name: "Approval needed" }));
      await act(async () => {
        await Promise.resolve();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(getApprovals).toHaveBeenCalledTimes(1);
      expect(getApproval).toHaveBeenCalledTimes(1);

      await act(async () => {
        vi.setSystemTime(start + 1_000);
        await vi.advanceTimersByTimeAsync(4_000);
      });

      expect(screen.getByRole("dialog").textContent).toContain("Approval expired");
      expect(getApprovals).toHaveBeenCalledTimes(2);
      expect(getApproval).toHaveBeenCalledTimes(2);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(9_000);
      });
      expect(getApprovals).toHaveBeenCalledTimes(2);
      expect(getApproval).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps an explicitly opened approval visible when it expires", async () => {
    vi.useFakeTimers();
    try {
      const start = Date.now();
      const expiring = { ...approval, expiresAt: new Date(start + 1_000).toISOString() };
      setup({ getApprovals: vi.fn().mockResolvedValue([expiring]), getApproval: vi.fn().mockResolvedValue(expiring) });
      await act(async () => {
        await Promise.resolve();
        await vi.advanceTimersByTimeAsync(0);
      });
      fireEvent.click(screen.getByRole("button", { name: "Approval needed" }));
      await act(async () => {
        await Promise.resolve();
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByRole("dialog")).toBeTruthy();

      await act(async () => {
        vi.setSystemTime(start + 1_000);
        await vi.advanceTimersByTimeAsync(1_000);
      });

      expect(screen.getByRole("dialog").textContent).toContain("Approval expired");
    } finally {
      vi.useRealTimers();
    }
  });
});
