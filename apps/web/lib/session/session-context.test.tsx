// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CloudClient } from "@allies/cloud-client";
import { SessionProvider, useSession } from "./session-context";

const account = {
  userId: "usr_example",
  displayName: "Example User",
  avatarUrl: null,
  session: { id: "ses_example", expiresAt: "2026-08-13T12:00:00Z" },
  workspace: { id: "wsp_example", name: "Personal Workspace", role: "owner", capabilities: [] },
};

function SessionProbe() {
  const session = useSession();
  const label = session.state.status === "signed-out"
    ? `signed-out:${String(session.state.serverConfirmed)}`
    : session.state.status;
  return <button onClick={() => void session.logout()}>{label}</button>;
}

function RestoreProbe() {
  const session = useSession();
  return (
    <div>
      <span>{session.state.status}</span>
      <button onClick={() => void session.restore()}>Restore now</button>
    </div>
  );
}

describe("SessionProvider", () => {
  afterEach(cleanup);

  it.each([
    [false, "signed-out:true"],
    [true, "signed-out:false"],
  ] as const)("clears Query data and exposes server confirmation (failure: %s)", async (serverFails, expected) => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["account"], account);
    const client = {
      getCurrentAccount: vi.fn(async () => account),
      getCsrf: vi.fn(async () => undefined),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => {
        if (serverFails) throw new Error("Cloud unavailable");
      }),
    } as unknown as CloudClient;

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider client={client}>
          <SessionProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );

    await screen.findByText("signed-in");
    screen.getByRole("button").click();
    await screen.findByText(expected);
    await waitFor(() => expect(queryClient.getQueryData(["account"])).toBeUndefined());
  });

  it("does not let mount restoration overwrite a newer explicit restore", async () => {
    let rejectMount: ((reason: unknown) => void) | undefined;
    let calls = 0;
    const client = {
      getCurrentAccount: vi.fn(() => {
        calls += 1;
        if (calls === 1) {
          return new Promise<typeof account>((_resolve, reject) => { rejectMount = reject; });
        }
        return Promise.resolve(account);
      }),
      getCsrf: vi.fn(async () => undefined),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    } as unknown as CloudClient;

    render(
      <QueryClientProvider client={new QueryClient()}>
        <SessionProvider client={client}>
          <RestoreProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );

    screen.getByRole("button", { name: "Restore now" }).click();
    await screen.findByText("signed-in");
    rejectMount?.(new Error("late network failure"));

    await waitFor(() => expect(screen.getByText("signed-in")).toBeTruthy());
  });
});
