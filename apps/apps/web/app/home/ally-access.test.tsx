// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useSessionMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/session/session-context", () => ({ useSession: useSessionMock }));

import type { IntegrationReturn } from "../../lib/integrations/integration-connect";

import { AllyAccess } from "./ally-access";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const connection = (level: "read" | "send" | "write" | "none") => ({
  connectionId: "00000000-0000-4000-8000-000000000003",
  accountEmail: "me@example.com",
  scopes: [],
  connectedAt: "2026-09-20T10:00:00Z",
  allyGrants: level === "none" ? [] : [{ allyId, level, grantGeneration: 1, updatedAt: "2026-09-20T10:00:00Z" }],
});

const byProvider = (connections: Record<string, unknown>) => vi.fn(async (_workspaceId: string, provider: string) => connections[provider] ?? null);

function renderAccess(client: Record<string, unknown>, returned: IntegrationReturn | null = null) {
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
    const beginIntegrationConnect = vi.fn(async () => ({
      connectSessionId: "00000000-0000-4000-8000-000000000004",
      authUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=x",
      expiresAt: "2026-09-20T10:10:00Z",
    }));
    renderAccess({ getIntegrationConnection: byProvider({}), beginIntegrationConnect });

    fireEvent.click(await screen.findByRole("button", { name: "Connect Gmail" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?state=x"));
    expect(beginIntegrationConnect).toHaveBeenCalledWith(
      workspaceId,
      "gmail",
      { allyId, grantLevel: "read", returnTo: `/home/${allyId}` },
      expect.stringMatching(/^[0-9a-f-]{36}$/),
      undefined,
    );
  });

  it("connects Calendar on its own and asks for write access", async () => {
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign });
    const beginIntegrationConnect = vi.fn(async () => ({
      connectSessionId: "00000000-0000-4000-8000-000000000004",
      authUrl: "https://accounts.google.com/o/oauth2/v2/auth?state=y",
      expiresAt: "2026-09-20T10:10:00Z",
    }));
    renderAccess({ getIntegrationConnection: byProvider({ gmail: connection("read") }), beginIntegrationConnect });

    fireEvent.click(await screen.findByRole("button", { name: "Connect Calendar" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?state=y"));
    expect(beginIntegrationConnect).toHaveBeenCalledWith(
      workspaceId,
      "calendar",
      { allyId, grantLevel: "write", returnTo: `/home/${allyId}` },
      expect.stringMatching(/^[0-9a-f-]{36}$/),
      undefined,
    );
    expect(screen.getByRole("switch", { name: "Gmail access" })).toBeTruthy();
  });

  it("confirms a completed connection and explains a failed one on return", async () => {
    renderAccess({ getIntegrationConnection: byProvider({ gmail: connection("read") }) }, { provider: "gmail", status: "connected" });
    expect(await screen.findByText("me@example.com")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    cleanup();
    renderAccess({ getIntegrationConnection: byProvider({}) }, { provider: "gmail", status: "failed", message: "Gmail wasn't connected." });
    expect((await screen.findByRole("alert")).textContent).toBe("Gmail wasn't connected.");
    expect(await screen.findByRole("button", { name: "Connect Gmail" })).toBeTruthy();
  });

  it("grants read, and rolls back to Cloud's state when a change fails", async () => {
    const getIntegrationConnection = byProvider({ gmail: connection("none") });
    const setIntegrationGrant = vi.fn().mockRejectedValue({ kind: "server", status: 503 });
    renderAccess({ getIntegrationConnection, setIntegrationGrant });

    const toggle = await screen.findByRole("switch", { name: "Gmail access" }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);
    expect(setIntegrationGrant).toHaveBeenCalledWith(workspaceId, "gmail", allyId, "read", undefined);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Gmail isn't responding. Try again.");
    await waitFor(() => expect(getIntegrationConnection.mock.calls.filter(([, provider]) => provider === "gmail")).toHaveLength(2));
    expect((screen.getByRole("switch", { name: "Gmail access" }) as HTMLInputElement).checked).toBe(false);
  });

  it("shows send as on and turning it off removes access", async () => {
    const setIntegrationGrant = vi.fn(async () => ({ allyId, level: "none", grantGeneration: 0, updatedAt: "2026-09-20T10:00:00Z" }));
    renderAccess({ getIntegrationConnection: byProvider({ gmail: connection("send") }), setIntegrationGrant });
    const toggle = await screen.findByRole("switch", { name: "Gmail access" }) as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    fireEvent.click(toggle);
    expect(setIntegrationGrant).toHaveBeenCalledWith(workspaceId, "gmail", allyId, "none", undefined);
    await waitFor(() => expect((screen.getByRole("switch", { name: "Gmail access" }) as HTMLInputElement).checked).toBe(false));
  });

  it("offers Reconnect when Google revoked the connection", async () => {
    const setIntegrationGrant = vi.fn().mockRejectedValue({ kind: "conflict", status: 409, code: "refresh_revoked" });
    renderAccess({ getIntegrationConnection: byProvider({ gmail: connection("none") }), setIntegrationGrant });
    fireEvent.click(await screen.findByRole("switch", { name: "Gmail access" }));
    expect(await screen.findByRole("button", { name: "Reconnect Gmail" })).toBeTruthy();
  });

  it("turns Calendar on with write access without touching Gmail", async () => {
    const setIntegrationGrant = vi.fn(async () => ({ allyId, level: "write", grantGeneration: 1, updatedAt: "2026-09-20T10:00:00Z" }));
    renderAccess({ getIntegrationConnection: byProvider({ gmail: connection("read"), calendar: connection("none") }), setIntegrationGrant });
    const toggle = await screen.findByRole("switch", { name: "Calendar access" }) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    expect((screen.getByRole("switch", { name: "Gmail access" }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(toggle);
    expect(setIntegrationGrant).toHaveBeenCalledWith(workspaceId, "calendar", allyId, "write", undefined);
    await waitFor(() => expect((screen.getByRole("switch", { name: "Calendar access" }) as HTMLInputElement).checked).toBe(true));
    expect((screen.getByRole("switch", { name: "Gmail access" }) as HTMLInputElement).checked).toBe(true);
  });
});
