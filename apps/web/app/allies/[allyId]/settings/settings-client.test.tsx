// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { AllySettingsClient } from "./settings-client";

const mocks = vi.hoisted(() => ({ session: vi.fn(), push: vi.fn(), replace: vi.fn() }));
vi.mock("@/lib/session/session-context", () => ({ useSession: mocks.session }));
vi.mock("next/navigation", () => ({ useRouter: () => mocks }));
vi.mock("@/components/allies-loading", () => ({ AlliesLoading: () => <p>Loading</p> }));
vi.mock("./settings-details", () => ({ AllySettingsDetails: ({ ally }: { ally: { name: string } }) => <p>{ally.name}</p> }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function setup(status = "signed-in") {
  const getAlly = vi.fn().mockResolvedValue({ id: "ally", name: "Mira" });
  const getCurrentAccount = vi.fn().mockResolvedValue({ workspace: { id: "workspace" } });
  mocks.session.mockReturnValue({
    state: { status }, restore: vi.fn(), client: { getAlly, getCurrentAccount },
    runCloudOperation: (operation: (signal: AbortSignal) => unknown, options: { signal: AbortSignal }) => operation(options.signal),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = () => render(<QueryClientProvider client={client}><AllySettingsClient allyId="ally" /></QueryClientProvider>);
  return { getAlly, getCurrentAccount, view, client };
}

it("loads only the signed-in workspace's ally and returns to that chat", async () => {
  const { getAlly, view } = setup();
  view();
  await screen.findByText("Mira");
  expect(getAlly).toHaveBeenCalledWith("workspace", "ally", expect.any(AbortSignal));
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(mocks.push).toHaveBeenCalledWith("/home/ally");
});

it("redirects a signed-out session without fetching private settings", async () => {
  const { getAlly, getCurrentAccount, view } = setup("signed-out");
  view();
  await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/sign-in?returnTo=%2Fallies%2Fally%2Fsettings"));
  expect(getAlly).not.toHaveBeenCalled();
  expect(getCurrentAccount).not.toHaveBeenCalled();
});

it("retries a failed read without exposing stale details", async () => {
  const { getAlly, view } = setup();
  getAlly.mockRejectedValueOnce({ kind: "network" });
  view();
  await screen.findByRole("alert");
  expect(screen.queryByText("Mira")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("Mira");
  expect(getAlly).toHaveBeenCalledTimes(2);
});

it("recovers both failed reads with one retry when the workspace is cached", async () => {
  const { getAlly, getCurrentAccount, view, client } = setup();
  client.setQueryData(["account", "current"], { workspace: { id: "workspace" } });
  getCurrentAccount.mockRejectedValueOnce({ kind: "network" });
  getAlly.mockRejectedValueOnce({ kind: "network" });
  view();
  await waitFor(() => {
    expect(client.getQueryState(["account", "current"])?.status).toBe("error");
    expect(client.getQueryState(["workspaces", "workspace", "allies", "ally", "settings"])?.status).toBe("error");
  });
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("Mira");
  expect(getCurrentAccount).toHaveBeenCalledTimes(2);
  expect(getAlly).toHaveBeenCalledTimes(2);
});

it("waits for account recovery before loading an uncached workspace", async () => {
  const { getAlly, getCurrentAccount, view } = setup();
  getCurrentAccount.mockRejectedValueOnce({ kind: "network" });
  view();
  await screen.findByRole("alert");
  expect(getAlly).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("Mira");
  expect(getAlly).toHaveBeenCalledTimes(1);
  expect(getAlly).toHaveBeenCalledWith("workspace", "ally", expect.any(AbortSignal));
});
