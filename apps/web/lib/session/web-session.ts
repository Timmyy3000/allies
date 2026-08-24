import type { CloudCsrfToken, CloudError, AccountViewModel } from "@allies/cloud-client";
import { isCloudError } from "@allies/cloud-client";

import type { CloudCsrfTokenOwner } from "../cloud/csrf-token";

export type SessionState =
  | { status: "signed-out" }
  | { status: "signed-in" }
  | { status: "unavailable" };

export type RestoreResult =
  | { status: "signed-in"; account: AccountViewModel }
  | Exclude<SessionState, { status: "signed-in" }>;

export interface WebSessionClient {
  getCurrentAccount(signal?: AbortSignal): Promise<AccountViewModel>;
  getCsrf(signal?: AbortSignal): Promise<CloudCsrfToken>;
  refreshSession(signal?: AbortSignal): Promise<void>;
  logout(signal?: AbortSignal): Promise<void>;
}

export interface LogoutResult {
  status: "signed-out";
  serverConfirmed: boolean;
}

export interface RunCloudOperationOptions {
  signal?: AbortSignal;
  csrf?: boolean;
}

export type RunCloudOperation = <T>(
  operation: (signal?: AbortSignal) => Promise<T>,
  options?: RunCloudOperationOptions,
) => Promise<T>;

interface Gate {
  controller: AbortController;
  promise: Promise<void>;
}

function abortedError(): CloudError {
  return { kind: "aborted" };
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw abortedError();
}

function awaitWithSignal<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortedError());

  return new Promise<T>((resolve, reject) => {
    const onAbort = () => {
      cleanup();
      reject(abortedError());
    };
    const cleanup = () => signal.removeEventListener("abort", onAbort);
    signal.addEventListener("abort", onAbort, { once: true });
    void promise.then(
      (value) => {
        cleanup();
        resolve(value);
      },
      (error) => {
        cleanup();
        reject(error);
      },
    );
  });
}

function combineAbortSignals(caller: AbortSignal | undefined, internal: AbortSignal) {
  if (!caller) return { signal: internal, cleanup: () => undefined };

  const controller = new AbortController();
  const abort = () => controller.abort(caller.reason ?? internal.reason);
  if (caller.aborted || internal.aborted) abort();
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

function isUnauthorized(error: unknown): boolean {
  return isCloudError(error) && (error.kind === "unauthorized" || error.status === 401);
}

function isCsrfRejected(error: unknown): boolean {
  return isCloudError(error) && error.kind === "security" && error.code === "csrf_rejected";
}

export function createWebSessionAdapter(client: WebSessionClient, csrf: CloudCsrfTokenOwner) {
  let generation = 0;
  let activeRefresh: Gate | null = null;
  let activeCsrf: Gate | null = null;
  const activeRestorations = new Set<AbortController>();
  let activeLogoutCount = 0;

  const invalidateSession = () => {
    generation += 1;
    for (const controller of activeRestorations) controller.abort();
    activeRefresh?.controller.abort();
    activeCsrf?.controller.abort();
    csrf.clear();
  };

  const startCsrf = (): Gate => {
    if (activeCsrf) return activeCsrf;

    const controller = new AbortController();
    const capturedGeneration = generation;

    const gate = { controller, promise: Promise.resolve() };
    gate.promise = client.getCsrf(controller.signal).then((token) => {
      if (capturedGeneration === generation) csrf.replace(token);
    });
    activeCsrf = gate;
    void gate.promise.then(
      () => { if (activeCsrf === gate) activeCsrf = null; },
      () => { if (activeCsrf === gate) activeCsrf = null; },
    );
    return gate;
  };

  const ensureCsrf = async (signal?: AbortSignal): Promise<void> => {
    if (csrf.has()) return;
    throwIfAborted(signal);
    await awaitWithSignal(startCsrf().promise, signal);
    throwIfAborted(signal);
  };

  const refreshCsrf = async (signal?: AbortSignal): Promise<void> => {
    throwIfAborted(signal);
    await awaitWithSignal(startCsrf().promise, signal);
    throwIfAborted(signal);
  };

  const refreshOnce = (): Promise<void> => {
    if (activeRefresh) return activeRefresh.promise;

    const controller = new AbortController();
    const gate = { controller, promise: Promise.resolve() };
    gate.promise = (async () => {
      await refreshCsrf(controller.signal);
      await client.refreshSession(controller.signal);
    })();
    activeRefresh = gate;
    void gate.promise.then(
      () => { if (activeRefresh === gate) activeRefresh = null; },
      () => { if (activeRefresh === gate) activeRefresh = null; },
    );
    return gate.promise;
  };

  const runCloudOperationInternal: RunCloudOperation = async <T>(
    operation: (signal?: AbortSignal) => Promise<T>,
    options: RunCloudOperationOptions = {},
  ) => {
    const operationGeneration = generation;
    if (activeLogoutCount > 0) throw abortedError();
    throwIfAborted(options.signal);
    if (options.csrf) await ensureCsrf(options.signal);
    if (operationGeneration !== generation) throw abortedError();

    const invoke = () => {
      throwIfAborted(options.signal);
      return operation(options.signal);
    };

    try {
      const result = await invoke();
      throwIfAborted(options.signal);
      if (operationGeneration !== generation) throw abortedError();
      return result;
    } catch (error) {
      if (operationGeneration !== generation) throw abortedError();
      if (isUnauthorized(error)) {
        await awaitWithSignal(refreshOnce(), options.signal);
      } else if (isCsrfRejected(error)) {
        await refreshCsrf(options.signal);
      } else {
        throw error;
      }
      if (operationGeneration !== generation) throw abortedError();
      const result = await invoke();
      throwIfAborted(options.signal);
      if (operationGeneration !== generation) throw abortedError();
      return result;
    }
  };

  const runCloudOperation: RunCloudOperation = async (operation, options) => {
    try {
      return await runCloudOperationInternal(operation, options);
    } catch (error) {
      if (isUnauthorized(error)) invalidateSession();
      throw error;
    }
  };

  return {
    ensureCsrf,
    refreshCsrf,
    runCloudOperation,

    async restore(signal?: AbortSignal): Promise<RestoreResult> {
      if (activeLogoutCount > 0) return { status: "signed-out" };

      const restoreGeneration = generation;
      const controller = new AbortController();
      activeRestorations.add(controller);
      const combinedSignal = combineAbortSignals(signal, controller.signal);
      try {
        const account = await runCloudOperation(
          (operationSignal) => client.getCurrentAccount(operationSignal),
          { signal: combinedSignal.signal },
        );
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
      const logoutGeneration = ++generation;
      for (const controller of activeRestorations) controller.abort();

      const refresh = activeRefresh;
      if (refresh) {
        activeRefresh = null;
        refresh.controller.abort();
        try {
          await refresh.promise;
        } catch {
          // Logout remains the final session action even when refresh is interrupted.
        }
      }

      const csrfGate = activeCsrf;
      if (csrfGate) {
        activeCsrf = null;
        csrfGate.controller.abort();
      }

      let serverConfirmed = false;
      try {
        const token = await client.getCsrf(signal);
        if (logoutGeneration === generation) csrf.replace(token);
        await client.logout(signal);
        serverConfirmed = true;
      } catch {
        serverConfirmed = false;
      } finally {
        activeLogoutCount -= 1;
        if (activeLogoutCount === 0) csrf.clear();
      }

      return { status: "signed-out", serverConfirmed };
    },
  };
}
