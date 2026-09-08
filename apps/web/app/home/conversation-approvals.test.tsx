// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApprovalDetail } from "@allies/cloud-client";
import { ConversationApprovals, approvalStatusAt, pruneDecisionIntents, type ApprovalClient } from "./conversation-approvals";

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

function setup(overrides: Partial<ApprovalClient> = {}, canApprove = true) {
  const client: ApprovalClient = {
    getApprovals: vi.fn().mockResolvedValue([approval]),
    getApproval: vi.fn().mockResolvedValue(approval),
    decideApproval: vi.fn().mockResolvedValue({ ...approval, status: "decision_recorded", decidedAt: new Date().toISOString(), acknowledgementDeadlineAt: new Date(Date.now() + 30_000).toISOString() }),
    ...overrides,
  };
  const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={query}><ConversationApprovals client={client} workspaceId="workspace" conversationId="conversation" allyName="Shaka" accent="#ff5800" canApprove={canApprove} /></QueryClientProvider>);
  return client;
}

describe("conversation approvals", () => {
  it("retains unresolved intent across a long history and prunes only confirmed terminal IDs", () => {
    const intents = Object.fromEntries(Array.from({ length: 60 }, (_, index) => [String(index), { decision: "approve" as const, key: String(index) }]));
    const pruned = pruneDecisionIntents(intents, [{ ...approval, id: "59", status: "approved" }]);
    expect(pruned["0"]).toEqual(intents["0"]);
    expect(pruned["59"]).toBeUndefined();
    expect(Object.keys(pruned)).toHaveLength(59);
  });
  it("loads the full action, dismisses with Escape and allows reopening without deciding", async () => {
    const client = setup();
    await screen.findByText(approval.actionPreview);
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
    const approve = await screen.findByRole("button", { name: "Approve" });
    fireEvent.click(approve); fireEvent.click(approve);
    expect(decideApproval).toHaveBeenCalledTimes(1);
    await act(async () => finish({ ...approval, status: "decision_recorded", decidedAt: new Date().toISOString(), acknowledgementDeadlineAt: new Date(Date.now() + 30_000).toISOString() }));
    await screen.findByText("Decision recorded · Waiting for Ally");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("retries an uncertain response with the same choice and idempotency key", async () => {
    const decideApproval = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValue({ ...approval, status: "rejected" });
    setup({ decideApproval });
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    await screen.findByRole("alert");
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(decideApproval).toHaveBeenCalledTimes(2));
    expect(decideApproval.mock.calls[0].slice(0, 5)).toEqual(decideApproval.mock.calls[1].slice(0, 5));
  });

  it("prevents read-only decisions", async () => {
    const client = setup({}, false);
    const approve = await screen.findByRole("button", { name: "Approve" });
    expect((approve as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(approve);
    expect(client.decideApproval).not.toHaveBeenCalled();
  });

  it("keeps an uncertain choice and key when dismissed and reopened", async () => {
    const decideApproval = vi.fn().mockImplementationOnce(() => new Promise(() => undefined)).mockResolvedValue({ ...approval, status: "decision_recorded" });
    setup({ decideApproval });
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
    fireEvent.click(await screen.findByText("Previous approvals"));
    fireEvent.click(screen.getByRole("button", { name: "Decision recorded; Ally outcome could not be confirmed" }));
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

  it("keeps an auto-opened approval visible when it expires", async () => {
    vi.useFakeTimers();
    try {
      const start = Date.now();
      const expiring = { ...approval, expiresAt: new Date(start + 1_000).toISOString() };
      setup({ getApprovals: vi.fn().mockResolvedValue([expiring]), getApproval: vi.fn().mockResolvedValue(expiring) });
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
