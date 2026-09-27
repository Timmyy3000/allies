// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useSessionMock = vi.hoisted(() => vi.fn());
vi.mock("../../lib/session/session-context", () => ({ useSession: useSessionMock }));

import { SafeInputLayer } from "./safe-input-layer";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const allyId = "00000000-0000-4000-8000-000000000002";
const request = (kind: "new" | "access") => ({
  id: "00000000-0000-4000-8000-000000000003",
  allyId,
  kind,
  safeInputId: kind === "access" ? "00000000-0000-4000-8000-000000000004" : null,
  name: "Amazon",
  website: "amazon.com",
  createdAt: "2026-09-27T10:00:00Z",
});

function renderLayer(client: Record<string, unknown>) {
  useSessionMock.mockReturnValue({
    client: { getAllyBrowserSession: vi.fn(async () => null), ...client },
    runCloudOperation: vi.fn(async (operation: (signal?: AbortSignal) => Promise<unknown>) => operation()),
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><SafeInputLayer workspaceId={workspaceId} allyId={allyId} allyName="Sally" accent="#4f46e5" /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SafeInputLayer", () => {
  it("saves a requested login without showing it back, then confirms", async () => {
    const resolveSafeInputRequest = vi.fn(async () => undefined);
    renderLayer({ listSafeInputRequests: vi.fn(async () => [request("new")]), resolveSafeInputRequest });

    expect(await screen.findByText("Sally needs your Amazon login. Sally can use it but never sees it.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Email or username"), { target: { value: "me@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Sally can sign in to amazon.com now.")).toBeTruthy();
    expect(resolveSafeInputRequest).toHaveBeenCalledWith(workspaceId, request("new").id, "allow", {
      name: "Amazon",
      website: "amazon.com",
      username: "me@example.com",
      password: "hunter2",
    }, undefined);
    expect(document.body.textContent).not.toContain("hunter2");
  });

  it("treats closing the sheet as not now", async () => {
    const resolveSafeInputRequest = vi.fn(async () => undefined);
    renderLayer({ listSafeInputRequests: vi.fn(async () => [request("new")]), resolveSafeInputRequest });
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }));
    await waitFor(() => expect(resolveSafeInputRequest).toHaveBeenCalledWith(workspaceId, request("new").id, "deny", {}, undefined));
  });

  it("asks before another Ally can use a saved login", async () => {
    const resolveSafeInputRequest = vi.fn(async () => undefined);
    renderLayer({ listSafeInputRequests: vi.fn(async () => [request("access")]), resolveSafeInputRequest });
    expect(await screen.findByText("Let Sally use your Amazon login?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Allow" }));
    await waitFor(() => expect(resolveSafeInputRequest).toHaveBeenCalledWith(workspaceId, request("access").id, "allow", {}, undefined));
  });

  it("shows the Ally's browser watch-only", async () => {
    renderLayer({
      listSafeInputRequests: vi.fn(async () => []),
      getAllyBrowserSession: vi.fn(async () => ({ liveUrl: "https://live.browser-use.com/x", expiresAt: "2026-09-27T10:20:00Z" })),
    });
    fireEvent.click(await screen.findByRole("button", { name: "Watch Sally's browser" }));
    expect(screen.getByText("You can watch. Only Sally can use this browser.")).toBeTruthy();
    expect(screen.getByTitle("Sally's browser").getAttribute("tabindex")).toBe("-1");
  });
});
