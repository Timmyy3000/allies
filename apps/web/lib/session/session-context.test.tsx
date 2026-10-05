// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CloudClient } from "@allies/cloud-client";
import { CURRENT_ACCOUNT_QUERY_KEY } from "../account/account-query";
import { createCloudCsrfTokenOwner } from "../cloud/csrf-token";
import { SessionProvider, useSession } from "./session-context";

const account = {
  userId: "usr_example",
  displayName: "Example User",
  avatarUrl: null,
  session: { id: "ses_example", expiresAt: "2026-08-13T12:00:00Z" },
  workspace: { id: "wsp_example", name: "Personal Workspace", role: "owner", capabilities: [] },
};

function RestoreProbe() {
  const session = useSession();
  return (
    <div>
      <span data-testid="status">{session.state.status}</span>
      <button onClick={() => void session.restore()}>Restore now</button>
    </div>
  );
}

function LogoutProbe() {
  const session = useSession();
  const [result, setResult] = useState<string>("");
  return (
    <div>
      <span data-testid="status">{session.state.status}</span>
      <span data-testid="result">{result}</span>
      <button onClick={() => void session.logout().then((value) => setResult(String(value.serverConfirmed)))}>
        Logout
      </button>
    </div>
  );
}

function OperationProbe() {
  const session = useSession();
  return (
    <div>
      <span data-testid="status">{session.state.status}</span>
      <button onClick={() => void session.runCloudOperation(async () => {
        throw { kind: "unauthorized", status: 401 };
      }).catch(() => undefined)}>
        Run protected operation
      </button>
    </div>
  );
}

describe("SessionProvider", () => {
  afterEach(cleanup);

  it("revalidates an existing session without returning to a restoring state", async () => {
    const queryClient = new QueryClient();
    let resolveSecond: ((value: typeof account) => void) | undefined;
    const getCurrentAccount = vi.fn()
      .mockResolvedValueOnce(account)
      .mockImplementationOnce(() => new Promise<typeof account>((resolve) => { resolveSecond = resolve; }));
    const client = {
      getCurrentAccount,
      getCsrf: vi.fn(async () => "a".repeat(32)),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    } as unknown as CloudClient;

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client} csrf={createCloudCsrfTokenOwner()}>
          <RestoreProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );
    screen.getByRole("button", { name: "Restore now" }).click();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("signed-in"));
    screen.getByRole("button", { name: "Restore now" }).click();
    await waitFor(() => expect(getCurrentAccount).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("status").textContent).toBe("signed-in");
    resolveSecond?.(account);
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("signed-in"));
  });

  it("starts unknown and restores explicitly into Query-owned account state", async () => {
    const queryClient = new QueryClient();
    let resolveAccount: ((value: typeof account) => void) | undefined;
    const client = {
      getCurrentAccount: vi.fn(() => new Promise<typeof account>((resolve) => { resolveAccount = resolve; })),
      getCsrf: vi.fn(async () => "a".repeat(32)),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    } as unknown as CloudClient;
    const csrf = createCloudCsrfTokenOwner();

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client} csrf={csrf}>
          <RestoreProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByTestId("status").textContent).toBe("unknown");
    expect(client.getCurrentAccount).not.toHaveBeenCalled();
    screen.getByRole("button", { name: "Restore now" }).click();
    await waitFor(() => expect(screen.getByTestId("status").textContent).toBe("restoring"));
    resolveAccount?.(account);
    await screen.findByText("signed-in");

    expect(queryClient.getQueryData(CURRENT_ACCOUNT_QUERY_KEY)).toEqual(account);
  });

  it("removes only private account data after signed-out restoration", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(CURRENT_ACCOUNT_QUERY_KEY, account);
    queryClient.setQueryData(["workspaces", "wsp_example", "allies"], [{ id: "ally" }]);
    queryClient.setQueryData(["waitlist", "entry"], { greeting: "Hello" });
    const client = {
      getCurrentAccount: vi.fn(async () => { throw { kind: "unauthorized" }; }),
      getCsrf: vi.fn(async () => "a".repeat(32)),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    } as unknown as CloudClient;

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client} csrf={createCloudCsrfTokenOwner()}>
          <RestoreProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );
    screen.getByRole("button", { name: "Restore now" }).click();
    await screen.findByText("signed-out");

    expect(queryClient.getQueryData(CURRENT_ACCOUNT_QUERY_KEY)).toBeUndefined();
    expect(queryClient.getQueryData(["workspaces", "wsp_example", "allies"])).toBeUndefined();
    expect(queryClient.getQueryData(["waitlist", "entry"])).toEqual({ greeting: "Hello" });
  });

  it("clears private account data and returns server confirmation separately from status", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(CURRENT_ACCOUNT_QUERY_KEY, account);
    const client = {
      getCurrentAccount: vi.fn(async () => account),
      getCsrf: vi.fn(async () => "a".repeat(32)),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    } as unknown as CloudClient;

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client} csrf={createCloudCsrfTokenOwner()}>
          <LogoutProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );

    // Explicit restoration is route-owned; this test seeds only the private cache.
    expect(screen.getByTestId("status").textContent).toBe("unknown");
    screen.getByRole("button", { name: "Logout" }).click();
    await screen.findByText("true");
    expect(screen.getByTestId("status").textContent).toBe("signed-out");
    expect(queryClient.getQueryData(CURRENT_ACCOUNT_QUERY_KEY)).toBeUndefined();
  });

  it("signs out and clears private data after a replayed 401", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(CURRENT_ACCOUNT_QUERY_KEY, account);
    const client = {
      getCurrentAccount: vi.fn(async () => account),
      getCsrf: vi.fn(async () => "a".repeat(32)),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    } as unknown as CloudClient;

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client} csrf={createCloudCsrfTokenOwner()}>
          <OperationProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );

    screen.getByRole("button", { name: "Run protected operation" }).click();
    await screen.findByText("signed-out");

    expect(client.refreshSession).toHaveBeenCalledOnce();
    expect(queryClient.getQueryData(CURRENT_ACCOUNT_QUERY_KEY)).toBeUndefined();
  });
});
