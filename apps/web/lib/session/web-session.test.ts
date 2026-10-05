import { describe, expect, it, vi } from "vitest";

import { createCloudCsrfTokenOwner } from "../cloud/csrf-token";
import { createWebSessionAdapter } from "./web-session";

const account = {
  userId: "usr_example",
  displayName: "Example User",
  avatarUrl: null,
  session: { id: "ses_example", expiresAt: "2026-08-13T12:00:00Z" },
  workspace: { id: "wsp_example", name: "Personal Workspace", role: "owner", capabilities: [] },
};
const token = "a".repeat(32);
const replacementToken = "b".repeat(64);

function client(overrides: Partial<{
  getCurrentAccount: (signal?: AbortSignal) => Promise<typeof account>;
  getCsrf: (signal?: AbortSignal) => Promise<string>;
  refreshSession: (signal?: AbortSignal) => Promise<void>;
  logout: (signal?: AbortSignal) => Promise<void>;
}> = {}) {
  return {
    getCurrentAccount: vi.fn(overrides.getCurrentAccount ?? (async () => account)),
    getCsrf: vi.fn(overrides.getCsrf ?? (async () => token)),
    refreshSession: vi.fn(overrides.refreshSession ?? (async () => undefined)),
    logout: vi.fn(overrides.logout ?? (async () => undefined)),
  };
}

function csrfRejected() {
  return { kind: "security", code: "csrf_rejected" } as const;
}

function unauthorized() {
  return { kind: "unauthorized", status: 401 } as const;
}

describe("createWebSessionAdapter", () => {
  it("composes caller cancellation without requiring AbortSignal.any", async () => {
    const originalAny = AbortSignal.any;
    Object.defineProperty(AbortSignal, "any", { configurable: true, value: undefined });
    try {
      const adapterClient = client();
      const adapter = createWebSessionAdapter(adapterClient, createCloudCsrfTokenOwner());

      await expect(adapter.restore(new AbortController().signal)).resolves.toEqual({ status: "signed-in", account });
    } finally {
      Object.defineProperty(AbortSignal, "any", { configurable: true, value: originalAny });
    }
  });

  it("shares one refresh across concurrent restorations", async () => {
    let attempts = 0;
    const adapterClient = client({
      getCurrentAccount: async () => {
        attempts += 1;
        if (attempts <= 2) throw unauthorized();
        return account;
      },
    });
    const adapter = createWebSessionAdapter(adapterClient, createCloudCsrfTokenOwner());

    const states = await Promise.all([adapter.restore(), adapter.restore()]);

    expect(adapterClient.refreshSession).toHaveBeenCalledTimes(1);
    expect(states).toEqual([
      { status: "signed-in", account },
      { status: "signed-in", account },
    ]);
  });

  it("lets logout win over a late restore and clears the token", async () => {
    let finish: ((value: typeof account) => void) | undefined;
    const adapterClient = client({
      getCurrentAccount: () => new Promise<typeof account>((resolve) => { finish = resolve; }),
    });
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapter = createWebSessionAdapter(adapterClient, owner);
    const restoration = adapter.restore();

    await adapter.logout();
    finish?.(account);

    expect(await restoration).toEqual({ status: "signed-out" });
    expect(owner.has()).toBe(false);
  });

  it("does not refresh when logout beats an unauthorized initial request", async () => {
    let rejectCurrent: ((reason: unknown) => void) | undefined;
    const adapterClient = client({
      getCurrentAccount: () => new Promise<typeof account>((_resolve, reject) => { rejectCurrent = reject; }),
    });
    const adapter = createWebSessionAdapter(adapterClient, createCloudCsrfTokenOwner());
    const restoration = adapter.restore();

    await adapter.logout();
    rejectCurrent?.(unauthorized());

    expect(await restoration).toEqual({ status: "signed-out" });
    expect(adapterClient.refreshSession).not.toHaveBeenCalled();
  });

  it("keeps restorations signed out while logout is in progress", async () => {
    let finishLogoutCsrf: (() => void) | undefined;
    const adapterClient = client({
      getCsrf: () => new Promise<string>((resolve) => { finishLogoutCsrf = () => resolve(token); }),
    });
    const adapter = createWebSessionAdapter(adapterClient, createCloudCsrfTokenOwner());
    const logout = adapter.logout();

    await expect(adapter.restore()).resolves.toEqual({ status: "signed-out" });
    finishLogoutCsrf?.();

    await expect(logout).resolves.toEqual({ status: "signed-out", serverConfirmed: true });
    expect(adapterClient.getCurrentAccount).not.toHaveBeenCalled();
  });

  it("aborts and settles refresh before sending logout", async () => {
    const operations: string[] = [];
    let markRefreshStarted: (() => void) | undefined;
    const refreshStarted = new Promise<void>((resolve) => { markRefreshStarted = resolve; });
    const adapterClient = client({
      getCurrentAccount: async () => { throw unauthorized(); },
      refreshSession: (signal) => new Promise<void>((_resolve, reject) => {
        operations.push("refresh-started");
        markRefreshStarted?.();
        signal?.addEventListener("abort", () => {
          operations.push("refresh-aborted");
          reject({ kind: "aborted" });
        });
      }),
      logout: async () => { operations.push("logout"); },
    });
    const adapter = createWebSessionAdapter(adapterClient, createCloudCsrfTokenOwner());
    const restoration = adapter.restore();
    await refreshStarted;

    const result = await adapter.logout();

    expect(result).toEqual({ status: "signed-out", serverConfirmed: true });
    expect(await restoration).toEqual({ status: "signed-out" });
    expect(operations).toEqual(["refresh-started", "refresh-aborted", "logout"]);
  });

  it("captures and replaces the token after a CSRF rejection", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapterClient = client({ getCsrf: async () => replacementToken });
    let attempts = 0;
    const adapter = createWebSessionAdapter(adapterClient, owner);

    await expect(adapter.runCloudOperation(async () => {
      attempts += 1;
      if (attempts === 1) throw csrfRejected();
      return "ok";
    })).resolves.toBe("ok");

    expect(attempts).toBe(2);
    expect(adapterClient.getCsrf).toHaveBeenCalledOnce();
    expect(owner.prepare(new Request("https://cloud.example.com/api/v1/auths/logout", { method: "POST" }))
      .headers.get("X-CSRFToken")).toBe(replacementToken);
  });

  it.each([
    ["401 -> csrf_rejected", [unauthorized(), csrfRejected()]],
    ["csrf_rejected -> 401", [csrfRejected(), unauthorized()]],
  ] as const)("uses exactly two invocation slots for %s", async (_name, failures) => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapterClient = client();
    const adapter = createWebSessionAdapter(adapterClient, owner);
    let attempts = 0;

    await expect(adapter.runCloudOperation(async () => {
      const failure = failures[attempts];
      attempts += 1;
      if (failure) throw failure;
      return "unexpected";
    })).rejects.toMatchObject(failures[1]);

    expect(attempts).toBe(2);
    expect(adapterClient.refreshSession).toHaveBeenCalledTimes(failures[0].kind === "unauthorized" ? 1 : 0);
    expect(adapterClient.getCsrf).toHaveBeenCalledTimes(failures[0].kind === "security" ? 1 : 1);
  });

  it("does not invoke the operation when CSRF bootstrap fails", async () => {
    const owner = createCloudCsrfTokenOwner();
    const operation = vi.fn(async () => "unexpected");
    const adapterClient = client({ getCsrf: async () => { throw { kind: "contract" }; } });
    const adapter = createWebSessionAdapter(adapterClient, owner);

    await expect(adapter.runCloudOperation(operation, { csrf: true })).rejects.toMatchObject({ kind: "contract" });
    expect(operation).not.toHaveBeenCalled();
  });

  it("does not retry a transient failure unless the caller opts in", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapter = createWebSessionAdapter(client(), owner);
    const operation = vi.fn(async () => { throw { kind: "network" } as const; });

    await expect(adapter.runCloudOperation(operation)).rejects.toMatchObject({ kind: "network" });
    expect(operation).toHaveBeenCalledOnce();
  });

  it("uses the second and final operation slot for an opted-in transient retry", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapter = createWebSessionAdapter(client(), owner);
    const operation = vi.fn()
      .mockRejectedValueOnce({ kind: "timeout" })
      .mockResolvedValueOnce("ok");

    await expect(adapter.runCloudOperation(operation, { retryTransient: true })).resolves.toBe("ok");
    expect(operation).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["network", { kind: "network" }],
    ["timeout", { kind: "timeout" }],
    ["408", { kind: "client", status: 408 }],
    ["429", { kind: "throttled", status: 429 }],
    ["server", { kind: "server", status: 503 }],
  ] as const)("delays one approval-read retry for %s", async (_name, failure) => {
    vi.useFakeTimers();
    try {
      const owner = createCloudCsrfTokenOwner();
      owner.replace(token);
      const adapter = createWebSessionAdapter(client(), owner);
      let attempts = 0;
      const operation = vi.fn(async () => {
        attempts += 1;
        if (attempts === 1) throw failure;
        return "ok";
      });
      const result = adapter.runCloudOperation(operation, { retryTransient: "approval-read" });
      await Promise.resolve();
      await Promise.resolve();
      expect(operation).toHaveBeenCalledOnce();
      await vi.advanceTimersByTimeAsync(999);
      expect(operation).toHaveBeenCalledOnce();
      await vi.advanceTimersByTimeAsync(1);
      await expect(result).resolves.toBe("ok");
      expect(operation).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    { kind: "throttled", status: 429 },
    { kind: "server", status: 503 },
  ] as const)("keeps legacy boolean retry from retrying approval failure %j", async (failure) => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapter = createWebSessionAdapter(client(), owner);
    const operation = vi.fn(async () => { throw failure; });

    await expect(adapter.runCloudOperation(operation, { retryTransient: true })).rejects.toMatchObject(failure);
    expect(operation).toHaveBeenCalledOnce();
  });

  it("aborts an approval-read delay without invoking a second request", async () => {
    vi.useFakeTimers();
    try {
      const owner = createCloudCsrfTokenOwner();
      owner.replace(token);
      const adapter = createWebSessionAdapter(client(), owner);
      const controller = new AbortController();
      const operation = vi.fn(async () => { throw { kind: "network" } as const; });
      const result = adapter.runCloudOperation(operation, { retryTransient: "approval-read", signal: controller.signal });
      await Promise.resolve();
      await Promise.resolve();
      controller.abort();
      await expect(result).rejects.toMatchObject({ kind: "aborted" });
      await vi.advanceTimersByTimeAsync(1_000);
      expect(operation).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("fences an approval-read replay when logout wins during its delay", async () => {
    vi.useFakeTimers();
    try {
      const owner = createCloudCsrfTokenOwner();
      owner.replace(token);
      const adapter = createWebSessionAdapter(client(), owner);
      const operation = vi.fn(async () => { throw { kind: "network" } as const; });
      const result = adapter.runCloudOperation(operation, { retryTransient: "approval-read" });
      const resultExpectation = expect(result).rejects.toMatchObject({ kind: "aborted" });
      await Promise.resolve();
      await Promise.resolve();
      await adapter.logout();
      await vi.advanceTimersByTimeAsync(1_000);
      await resultExpectation;
      expect(operation).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    ["401 -> refresh -> network", unauthorized(), { kind: "network" }],
    ["csrf_rejected -> refresh -> timeout", csrfRejected(), { kind: "timeout" }],
  ] as const)("never spends a third operation slot after %s", async (_name, firstFailure, secondFailure) => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapterClient = client();
    const adapter = createWebSessionAdapter(adapterClient, owner);
    const operation = vi.fn()
      .mockRejectedValueOnce(firstFailure)
      .mockRejectedValueOnce(secondFailure)
      .mockResolvedValue("unexpected third result");

    await expect(adapter.runCloudOperation(operation, { csrf: true, retryTransient: true }))
      .rejects.toMatchObject(secondFailure);
    expect(operation).toHaveBeenCalledTimes(2);
    if (firstFailure.kind === "unauthorized") expect(adapterClient.refreshSession).toHaveBeenCalledOnce();
    expect(adapterClient.getCsrf).toHaveBeenCalledOnce();
  });

  it("shares one refresh gate while retaining a budget per concurrent operation", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    let refreshResolve: (() => void) | undefined;
    const refreshGate = new Promise<void>((resolve) => { refreshResolve = resolve; });
    const adapterClient = client({
      refreshSession: () => refreshGate,
    });
    const adapter = createWebSessionAdapter(adapterClient, owner);
    const attempts = [0, 0];
    const operations = attempts.map((_value, index) => adapter.runCloudOperation(async () => {
      attempts[index] += 1;
      if (attempts[index] === 1) throw unauthorized();
      return index;
    }));

    await vi.waitFor(() => expect(adapterClient.refreshSession).toHaveBeenCalledOnce());
    refreshResolve?.();
    await expect(Promise.all(operations)).resolves.toEqual([0, 1]);
    expect(attempts).toEqual([2, 2]);
  });

  it("shares one CSRF recovery gate for concurrent rejections", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapterClient = client({ getCsrf: async () => replacementToken });
    const adapter = createWebSessionAdapter(adapterClient, owner);
    const attempts = [0, 0];
    const operations = attempts.map((_value, index) => adapter.runCloudOperation(async () => {
      attempts[index] += 1;
      if (attempts[index] === 1) throw csrfRejected();
      return index;
    }));

    await expect(Promise.all(operations)).resolves.toEqual([0, 1]);
    expect(adapterClient.getCsrf).toHaveBeenCalledOnce();
    expect(attempts).toEqual([2, 2]);
  });

  it("keeps a shared CSRF recovery alive when one caller cancels", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    let resolveCsrf: ((value: string) => void) | undefined;
    let csrfSignal: AbortSignal | undefined;
    const adapterClient = client({
      getCsrf: (signal) => new Promise<string>((resolve) => {
        csrfSignal = signal;
        resolveCsrf = resolve;
      }),
    });
    const adapter = createWebSessionAdapter(adapterClient, owner);
    const controllers = [new AbortController(), new AbortController()];
    const attempts = [0, 0];
    const operations = attempts.map((_value, index) => adapter.runCloudOperation(async () => {
      attempts[index] += 1;
      if (attempts[index] === 1) throw csrfRejected();
      return index;
    }, { signal: controllers[index].signal }));

    await vi.waitFor(() => expect(adapterClient.getCsrf).toHaveBeenCalledOnce());
    controllers[0].abort();
    await expect(operations[0]).rejects.toMatchObject({ kind: "aborted" });
    expect(csrfSignal?.aborted).toBe(false);
    resolveCsrf?.(replacementToken);

    await expect(operations[1]).resolves.toBe(1);
    expect(attempts).toEqual([1, 2]);
  });

  it("invalidates concurrent work after a terminal unauthorized replay", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    const adapter = createWebSessionAdapter(client(), owner);
    let finishConcurrent: ((value: string) => void) | undefined;
    const concurrent = adapter.runCloudOperation(() => new Promise<string>((resolve) => {
      finishConcurrent = resolve;
    }));
    const terminal = adapter.runCloudOperation(async () => { throw unauthorized(); });

    await expect(terminal).rejects.toMatchObject({ kind: "unauthorized" });
    finishConcurrent?.("late");

    await expect(concurrent).rejects.toMatchObject({ kind: "aborted" });
    expect(owner.has()).toBe(false);
  });

  it("stops in-flight work when logout wins the generation", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    let finish: (() => void) | undefined;
    const adapterClient = client({
      getCurrentAccount: () => new Promise<typeof account>((resolve) => { finish = () => resolve(account); }),
    });
    const adapter = createWebSessionAdapter(adapterClient, owner);
    const operation = adapter.runCloudOperation((signal) => new Promise<typeof account>((resolve, reject) => {
      finish = () => resolve(account);
      signal?.addEventListener("abort", () => reject({ kind: "aborted" }));
    }));

    await adapter.logout();
    finish?.();

    await expect(operation).rejects.toMatchObject({ kind: "aborted" });
    expect(owner.has()).toBe(false);
  });

  it("rejects a late replay result after logout wins the generation", async () => {
    const owner = createCloudCsrfTokenOwner();
    owner.replace(token);
    let finishReplay: ((value: string) => void) | undefined;
    let attempts = 0;
    const adapterClient = client();
    const adapter = createWebSessionAdapter(adapterClient, owner);
    const operation = adapter.runCloudOperation(async () => {
      attempts += 1;
      if (attempts === 1) throw unauthorized();
      return new Promise<string>((resolve) => { finishReplay = resolve; });
    });

    await vi.waitFor(() => expect(attempts).toBe(2));
    await adapter.logout();
    finishReplay?.("late");

    await expect(operation).rejects.toMatchObject({ kind: "aborted" });
  });
});
