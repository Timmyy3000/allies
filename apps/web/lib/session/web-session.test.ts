import { describe, expect, it, vi } from "vitest";

import { createWebSessionAdapter } from "./web-session";

const account = {
  userId: "usr_example",
  displayName: "Example User",
  avatarUrl: null,
  session: { id: "ses_example", expiresAt: "2026-08-13T12:00:00Z" },
  workspace: { id: "wsp_example", name: "Personal Workspace", role: "owner", capabilities: [] },
};

describe("createWebSessionAdapter", () => {
  it("composes caller cancellation without requiring AbortSignal.any", async () => {
    const originalAny = AbortSignal.any;
    Object.defineProperty(AbortSignal, "any", { configurable: true, value: undefined });
    try {
      const client = {
        getCurrentAccount: vi.fn(async () => account),
        getCsrf: vi.fn(async () => undefined),
        refreshSession: vi.fn(async () => undefined),
        logout: vi.fn(async () => undefined),
      };
      const adapter = createWebSessionAdapter(client);

      await expect(adapter.restore(new AbortController().signal)).resolves.toEqual({ status: "signed-in", account });
    } finally {
      Object.defineProperty(AbortSignal, "any", { configurable: true, value: originalAny });
    }
  });

  it("shares one refresh across concurrent restorations", async () => {
    let attempts = 0;
    const client = {
      getCurrentAccount: vi.fn(async () => {
        attempts += 1;
        if (attempts <= 2) throw { kind: "unauthorized" };
        return account;
      }),
      getCsrf: vi.fn(async () => undefined),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    };
    const adapter = createWebSessionAdapter(client);

    const states = await Promise.all([adapter.restore(), adapter.restore()]);

    expect(client.refreshSession).toHaveBeenCalledTimes(1);
    expect(states).toEqual([
      { status: "signed-in", account },
      { status: "signed-in", account },
    ]);
  });

  it("lets logout win over a late restore", async () => {
    let finish: ((value: typeof account) => void) | undefined;
    const client = {
      getCurrentAccount: vi.fn(() => new Promise<typeof account>((resolve) => { finish = resolve; })),
      getCsrf: vi.fn(async () => undefined),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    };
    const adapter = createWebSessionAdapter(client);
    const restoration = adapter.restore();

    await adapter.logout();
    finish?.(account);

    expect(await restoration).toEqual({ status: "signed-out" });
  });

  it("does not refresh when logout beats an unauthorized initial request", async () => {
    let rejectCurrent: ((reason: unknown) => void) | undefined;
    const client = {
      getCurrentAccount: vi.fn(() => new Promise<typeof account>((_resolve, reject) => { rejectCurrent = reject; })),
      getCsrf: vi.fn(async () => undefined),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    };
    const adapter = createWebSessionAdapter(client);
    const restoration = adapter.restore();

    await adapter.logout();
    rejectCurrent?.({ kind: "unauthorized" });

    expect(await restoration).toEqual({ status: "signed-out" });
    expect(client.refreshSession).not.toHaveBeenCalled();
  });

  it("keeps restorations signed out while logout is in progress", async () => {
    let finishLogoutCsrf: (() => void) | undefined;
    const client = {
      getCurrentAccount: vi.fn(async () => account),
      getCsrf: vi.fn(() => new Promise<void>((resolve) => { finishLogoutCsrf = resolve; })),
      refreshSession: vi.fn(async () => undefined),
      logout: vi.fn(async () => undefined),
    };
    const adapter = createWebSessionAdapter(client);
    const logout = adapter.logout();

    await expect(adapter.restore()).resolves.toEqual({ status: "signed-out" });
    finishLogoutCsrf?.();

    await expect(logout).resolves.toEqual({ status: "signed-out", serverConfirmed: true });
    expect(client.getCurrentAccount).not.toHaveBeenCalled();
  });

  it("aborts and settles refresh before sending logout", async () => {
    const operations: string[] = [];
    let markRefreshStarted: (() => void) | undefined;
    const refreshStarted = new Promise<void>((resolve) => { markRefreshStarted = resolve; });
    const client = {
      getCurrentAccount: vi.fn(async () => { throw { kind: "unauthorized" }; }),
      getCsrf: vi.fn(async () => undefined),
      refreshSession: vi.fn(
        (signal?: AbortSignal) =>
          new Promise<void>((_resolve, reject) => {
            operations.push("refresh-started");
            markRefreshStarted?.();
            signal?.addEventListener("abort", () => {
              operations.push("refresh-aborted");
              reject({ kind: "aborted" });
            });
          }),
      ),
      logout: vi.fn(async () => { operations.push("logout"); }),
    };
    const adapter = createWebSessionAdapter(client);
    const restoration = adapter.restore();
    await refreshStarted;

    const result = await adapter.logout();

    expect(result).toEqual({ status: "signed-out", serverConfirmed: true });
    expect(await restoration).toEqual({ status: "signed-out" });
    expect(operations).toEqual(["refresh-started", "refresh-aborted", "logout"]);
  });
});
