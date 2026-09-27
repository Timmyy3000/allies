// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useSessionMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/session/session-context", () => ({ useSession: useSessionMock }));

import type { GmailReturn } from "../../lib/integrations/gmail-connect";

import { AllyAccess } from "./ally-access";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const connection = (level: "read" | "send" | "none") => ({
  connectionId: "00000000-0000-4000-8000-000000000003",
  accountEmail: "me@example.com",
  scopes: [],
  connectedAt: "2026-09-20T10:00:00Z",
  allyGrants: level === "none" ? [] : [{ allyId, level, grantGeneration: 1, updatedAt: "2026-09-20T10:00:00Z" }],
});

function renderAccess(client: Record<string, unknown>, returned: GmailReturn | null = null) {
  useSessionMock.mockReturnValue({
    client,
    runCloudOperation: vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation()),
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><AllyAccess workspaceId={workspaceId} allyId={allyId} returned={returned} /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

describe("AllyAccess", () => {
  it("connects Gmail for this Ally and asks Cloud to return to its chat", async () => {
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign });
    const beginGmailConnect = vi.fn(async () => ({
      connectSessionId: "00000000-0000-4000-8000-000000000004",
      authUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=x",
      expiresAt: "2026-09-20T10:10:00Z",
    }));
    renderAccess({ getGmailConnection: vi.fn(async () => null), beginGmailConnect });

    fireEvent.click(await screen.findByRole("button", { name: "Connect" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?state=x"));
    expect(beginGmailConnect).toHaveBeenCalledWith(
      workspaceId,
      { allyId, grantLevel: "read", returnTo: `/home/${allyId}` },
      expect.stringMatching(/^[0-9a-f-]{36}$/),
      undefined,
    );
  });

  it("confirms a completed connection and explains a failed one on return", async () => {
    renderAccess({ getGmailConnection: vi.fn(async () => connection("read")) }, { status: "connected" });
    expect((await screen.findByRole("status")).textContent).toBe("Gmail connected");
    cleanup();
    renderAccess({ getGmailConnection: vi.fn(async () => null) }, { status: "failed", message: "Gmail wasn't connected." });
    expect((await screen.findByRole("alert")).textContent).toBe("Gmail wasn't connected.");
    expect(await screen.findByRole("button", { name: "Connect" })).toBeTruthy();
  });

  it("grants read, and rolls back to Cloud's state when a change fails", async () => {
    const getGmailConnection = vi.fn()
      .mockResolvedValueOnce(connection("none"))
      .mockResolvedValue(connection("none"));
    const setGmailGrant = vi.fn().mockRejectedValue({ kind: "server", status: 503 });
    renderAccess({ getGmailConnection, setGmailGrant });

    const toggle = await screen.findByRole("switch", { name: "Gmail access" }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);
    expect(setGmailGrant).toHaveBeenCalledWith(workspaceId, allyId, "read", undefined);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Gmail isn't responding. Try again.");
    await waitFor(() => expect(getGmailConnection).toHaveBeenCalledTimes(2));
    expect((screen.getByRole("switch", { name: "Gmail access" }) as HTMLInputElement).checked).toBe(false);
  });

  it("shows send as on and turning it off removes access", async () => {
    const setGmailGrant = vi.fn(async () => ({ allyId, level: "none", grantGeneration: 0, updatedAt: "2026-09-20T10:00:00Z" }));
    renderAccess({ getGmailConnection: vi.fn(async () => connection("send")), setGmailGrant });
    const toggle = await screen.findByRole("switch", { name: "Gmail access" }) as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    expect(setGmailGrant).toHaveBeenCalledWith(workspaceId, allyId, "none", undefined);
    await waitFor(() => expect((screen.getByRole("switch", { name: "Gmail access" }) as HTMLInputElement).checked).toBe(false));
  });

  it("offers Reconnect when Google revoked the connection", async () => {
    const setGmailGrant = vi.fn().mockRejectedValue({ kind: "conflict", status: 409, code: "refresh_revoked" });
    renderAccess({ getGmailConnection: vi.fn(async () => connection("none")), setGmailGrant });
    fireEvent.click(await screen.findByRole("switch", { name: "Gmail access" }));
    expect(await screen.findByRole("button", { name: "Reconnect" })).toBeTruthy();
  });
});
