// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CloudClient } from "@allies/cloud-client";
const mocks = vi.hoisted(() => ({ restore: vi.fn(), logout: vi.fn(), run: vi.fn(), pushLogout: vi.fn(), recover: vi.fn() }));
vi.mock("./web-session", () => ({ createWebSessionAdapter: () => ({ restore: mocks.restore, logout: mocks.logout, runCloudOperation: mocks.run }) }));
vi.mock("../pwa/push-lifecycle", () => ({ createPushLifecycle: () => ({ start: () => () => undefined, logout: mocks.pushLogout, recover: mocks.recover }) }));
import { createCloudCsrfTokenOwner } from "../cloud/csrf-token";
import { SessionProvider, useSession } from "./session-context";
const account = { userId: "owner", session: { id: "family" }, workspace: { id: "workspace" } };
function Probe() { const session = useSession(); return <><span>{session.state.status}</span><button onClick={() => void session.restore()}>Restore</button><button onClick={() => void session.logout().then(result => { document.body.dataset.cleanup = String(result.pushCleanupConfirmed); })}>Logout</button><button onClick={() => void session.runCloudOperation(async () => undefined).catch(() => undefined)}>Protected</button></>; }
beforeEach(() => { vi.clearAllMocks(); mocks.restore.mockResolvedValue({ status: "signed-in", account }); mocks.pushLogout.mockResolvedValue(true); });
afterEach(cleanup);
function mount() { render(<QueryClientProvider client={new QueryClient()}><SessionProvider client={{} as CloudClient} csrf={createCloudCsrfTokenOwner()}><Probe /></SessionProvider></QueryClientProvider>); }
it("paused signed-out cleanup cannot overwrite a newer successful restore", async () => {
  let release!: (value: boolean) => void;
  mocks.restore.mockResolvedValueOnce({ status: "signed-out" });
  mocks.pushLogout.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
  mount(); fireEvent.click(screen.getByText("Restore")); await waitFor(() => expect(release).toBeTypeOf("function"));
  fireEvent.click(screen.getByText("Restore")); await screen.findByText("signed-in"); release(true);
  await waitFor(() => expect(screen.getByText("signed-in")).toBeTruthy());
});
it("paused unauthorized cleanup cannot overwrite a newer successful restore", async () => {
  let release!: (value: boolean) => void;
  mocks.run.mockRejectedValue({ kind: "unauthorized", status: 401 }); mocks.pushLogout.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
  mount(); fireEvent.click(screen.getByText("Restore")); await screen.findByText("signed-in");
  fireEvent.click(screen.getByText("Protected")); await waitFor(() => expect(release).toBeTypeOf("function"));
  fireEvent.click(screen.getByText("Restore")); await waitFor(() => expect(mocks.restore).toHaveBeenCalledTimes(2)); release(true);
  await waitFor(() => expect(screen.getByText("signed-in")).toBeTruthy());
});

it("Cloud logout still completes while local notification cleanup is unconfirmed", async () => {
  mocks.pushLogout.mockResolvedValue(false); mocks.logout.mockResolvedValue({ status: "signed-out", serverConfirmed: true });
  mount(); fireEvent.click(screen.getByText("Logout")); await screen.findByText("signed-out");
  expect(mocks.logout).toHaveBeenCalledOnce(); expect(document.body.dataset.cleanup).toBe("false");
});
