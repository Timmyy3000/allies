import type { AccountViewModel, CloudError } from "@allies/cloud-client";

export type SessionState =
  | { status: "signed-out"; serverConfirmed?: boolean }
  | { status: "signed-in"; account: AccountViewModel }
  | { status: "unavailable" };

export interface WebSessionClient {
  getCurrentAccount(signal?: AbortSignal): Promise<AccountViewModel>;
  getCsrf(signal?: AbortSignal): Promise<void>;
  refreshSession(signal?: AbortSignal): Promise<void>;
  logout(signal?: AbortSignal): Promise<void>;
}

export interface LogoutResult {
  status: "signed-out";
  serverConfirmed: boolean;
}

function isUnauthorized(error: unknown): error is CloudError {
  return typeof error === "object" && error !== null && "kind" in error && error.kind === "unauthorized";
}

function combineAbortSignals(caller: AbortSignal | undefined, internal: AbortSignal) {
  if (!caller) return { signal: internal, cleanup: () => undefined };
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (caller.aborted || internal.aborted) controller.abort();
  caller.addEventListener("abort", abort, { once: true });
  internal.addEventListener("abort", abort, { once: true });
  return {
    signal: controller.signal,
    cleanup: () => {
      caller.removeEventListener("abort", abort);
      internal.removeEventListener("abort", abort);
    },
  };
}

export function createWebSessionAdapter(client: WebSessionClient) {
  let generation = 0;
  let activeRefresh: { controller: AbortController; promise: Promise<void> } | null = null;
  const activeRestorations = new Set<AbortController>();
  let activeLogoutCount = 0;

  const refreshOnce = () => {
    if (activeRefresh) return activeRefresh.promise;
    const controller = new AbortController();
    const refresh = {
      controller,
      promise: (async () => {
        await client.getCsrf(controller.signal);
        await client.refreshSession(controller.signal);
      })(),
    };
    activeRefresh = refresh;
    void refresh.promise.then(
      () => { if (activeRefresh === refresh) activeRefresh = null; },
      () => { if (activeRefresh === refresh) activeRefresh = null; },
    );
    return refresh.promise;
  };

  return {
    async restore(signal?: AbortSignal): Promise<SessionState> {
      if (activeLogoutCount > 0) return { status: "signed-out" };
      const restoreGeneration = generation;
      const controller = new AbortController();
      activeRestorations.add(controller);
      const combinedSignal = combineAbortSignals(signal, controller.signal);
      const restoreSignal = combinedSignal.signal;
      try {
        let account: AccountViewModel;
        try {
          account = await client.getCurrentAccount(restoreSignal);
        } catch (error) {
          if (!isUnauthorized(error)) throw error;
          if (restoreGeneration !== generation) return { status: "signed-out" };
          await refreshOnce();
          if (restoreSignal.aborted) throw { kind: "aborted" } satisfies CloudError;
          account = await client.getCurrentAccount(restoreSignal);
        }
        return restoreGeneration === generation
          ? { status: "signed-in", account }
          : { status: "signed-out" };
      } catch (error) {
        if (restoreGeneration !== generation || isUnauthorized(error)) return { status: "signed-out" };
        return { status: "unavailable" };
      } finally {
        combinedSignal.cleanup();
        activeRestorations.delete(controller);
      }
    },

    async logout(signal?: AbortSignal): Promise<LogoutResult> {
      activeLogoutCount += 1;
      generation += 1;
      for (const controller of activeRestorations) controller.abort();
      try {
        const refresh = activeRefresh;
        if (refresh) {
          refresh.controller.abort();
          try {
            await refresh.promise;
          } catch {
            // Logout must remain the final server-side session operation.
          }
        }
        try {
          await client.getCsrf(signal);
          await client.logout(signal);
          return { status: "signed-out", serverConfirmed: true };
        } catch {
          return { status: "signed-out", serverConfirmed: false };
        }
      } finally {
        activeLogoutCount -= 1;
      }
    },
  };
}
