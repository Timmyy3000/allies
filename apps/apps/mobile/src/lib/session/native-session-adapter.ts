import type {
  AccountViewModel,
  CloudError,
  NativeAuthClient,
  NativeGoogleCodeExchangeInput,
  NativeSessionTokens,
} from '@allies/cloud-client';
import { isCloudError } from '@allies/cloud-client';

import type { NativeSessionStore } from './secure-session-store';

export type NativeSessionState =
  | { status: 'checking' }
  | { status: 'refreshing' }
  | { status: 'signed-out'; reason: 'missing-refresh' | 'session-invalid' | 'canceled' }
  | { status: 'signed-in'; account: AccountViewModel }
  | { status: 'offline-with-session' }
  | { status: 'unavailable'; reason: 'storage' | 'auth' };

export interface NativeSessionClient extends NativeAuthClient {
  setAccessToken(token: string | null): void;
  getCurrentAccount(signal?: AbortSignal): Promise<AccountViewModel>;
}

export interface NativeSessionLogoutResult {
  status: 'signed-out';
  serverConfirmed: boolean;
  localCleared: boolean;
}

export interface NativeSessionAdapter {
  restore(signal?: AbortSignal): Promise<NativeSessionState>;
  completeSignIn(input: NativeGoogleCodeExchangeInput, signal?: AbortSignal): Promise<NativeSessionState>;
  cancelSignIn(): Promise<void>;
  refresh(signal?: AbortSignal): Promise<boolean>;
  withRefresh<T>(operation: () => Promise<T>): Promise<T>;
  logout(signal?: AbortSignal): Promise<NativeSessionLogoutResult>;
  clearLocal(): Promise<boolean>;
  getAccessToken(): string | null;
}

export interface NativeSessionAdapterOptions {
  onSessionInvalidated?: () => void;
  onStorageUnavailable?: () => void;
}

interface NativeSessionRuntime {
  client: NativeSessionClient;
  store: NativeSessionStore;
  accessToken: string | null;
  generation: number;
  activeRefresh: Promise<boolean> | null;
  activeRefreshController: AbortController | null;
  activeSignInController: AbortController | null;
  activeRestorations: Set<AbortController>;
  activeLogoutCount: number;
  storageTail: Promise<void>;
  signInTokenGeneration: number | null;
  options: NativeSessionAdapterOptions;
}

const runtimes = new WeakMap<NativeSessionStore, NativeSessionRuntime>();

function runtimeFor(client: NativeSessionClient, store: NativeSessionStore, options: NativeSessionAdapterOptions) {
  const existing = runtimes.get(store);
  if (existing) {
    if (existing.client !== client) {
      existing.client.setAccessToken(null);
      existing.client = client;
      existing.client.setAccessToken(existing.accessToken);
    }
    existing.options = options;
    return existing;
  }

  const runtime: NativeSessionRuntime = {
    client,
    store,
    accessToken: null,
    generation: 0,
    activeRefresh: null,
    activeRefreshController: null,
    activeSignInController: null,
    activeRestorations: new Set(),
    activeLogoutCount: 0,
    storageTail: Promise.resolve(),
    signInTokenGeneration: null,
    options,
  };
  runtimes.set(store, runtime);
  return runtime;
}

function storageError(): CloudError {
  return { kind: 'client', code: 'secure_store' };
}

function isUnauthorized(error: unknown): boolean {
  return isCloudError(error) && (error.kind === 'unauthorized' || error.code === 'session_invalid');
}

function isTransient(error: unknown): boolean {
  return isCloudError(error) && ['network', 'timeout', 'server', 'throttled'].includes(error.kind);
}

function combineAbortSignals(caller: AbortSignal | undefined, internal: AbortSignal) {
  if (!caller) return { signal: internal, cleanup: () => undefined };
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (caller.aborted || internal.aborted) controller.abort();
  caller.addEventListener('abort', abort, { once: true });
  internal.addEventListener('abort', abort, { once: true });
  return {
    signal: controller.signal,
    cleanup: () => {
      caller.removeEventListener('abort', abort);
      internal.removeEventListener('abort', abort);
    },
  };
}

function enqueueStorage<T>(runtime: NativeSessionRuntime, operation: () => Promise<T>): Promise<T> {
  const next = runtime.storageTail.then(operation, operation);
  runtime.storageTail = next.then(() => undefined, () => undefined);
  return next;
}

async function clearStore(runtime: NativeSessionRuntime): Promise<boolean> {
  runtime.accessToken = null;
  runtime.client.setAccessToken(null);
  try {
    await runtime.store.clear();
    return true;
  } catch {
    return false;
  }
}

function setAccessToken(runtime: NativeSessionRuntime, token: string | null) {
  runtime.accessToken = token;
  runtime.client.setAccessToken(token);
}

export function createNativeSessionAdapter(
  client: NativeSessionClient,
  store: NativeSessionStore,
  options: NativeSessionAdapterOptions = {},
): NativeSessionAdapter {
  const runtime = runtimeFor(client, store, options);

  const abortActiveWork = () => {
    runtime.activeSignInController?.abort();
    for (const controller of runtime.activeRestorations) controller.abort();
    runtime.activeRefreshController?.abort();
  };

  const clearAndInvalidate = async (): Promise<boolean> => {
    runtime.generation += 1;
    abortActiveWork();
    return enqueueStorage(runtime, async () => {
      const localCleared = await clearStore(runtime);
      if (localCleared) runtime.signInTokenGeneration = null;
      return localCleared;
    });
  };

  const invalidateLocal = async () => {
    const localCleared = await clearAndInvalidate();
    if (localCleared) runtime.options.onSessionInvalidated?.();
    else runtime.options.onStorageUnavailable?.();
    return localCleared;
  };

  const markStorageUnavailable = async () => {
    await clearAndInvalidate();
    runtime.options.onStorageUnavailable?.();
  };

  const commitTokens = (
    tokens: NativeSessionTokens,
    operationGeneration: number,
    signal: AbortSignal,
    owner: 'refresh' | 'sign-in',
  ) => enqueueStorage(runtime, async () => {
    if (operationGeneration !== runtime.generation || signal.aborted) return false;
    if (owner === 'sign-in') runtime.signInTokenGeneration = operationGeneration;

    try {
      await runtime.store.writeRefresh(tokens.refreshToken);
    } catch {
      await clearStore(runtime);
      throw storageError();
    }

    if (operationGeneration !== runtime.generation || signal.aborted) {
      const localCleared = await clearStore(runtime);
      if (!localCleared) throw storageError();
      if (owner === 'sign-in') runtime.signInTokenGeneration = null;
      return false;
    }

    setAccessToken(runtime, tokens.accessToken);
    return true;
  });

  const refresh = (signal?: AbortSignal): Promise<boolean> => {
    if (runtime.activeRefresh) return runtime.activeRefresh;

    const operationGeneration = runtime.generation;
    const controller = new AbortController();
    runtime.activeRefreshController = controller;
    const combined = combineAbortSignals(signal, controller.signal);
    const operationClient = runtime.client;
    const operation = (async () => {
      let refreshToken: string | null;
      try {
        refreshToken = await runtime.store.readRefresh();
      } catch {
        throw storageError();
      }
      if (operationGeneration !== runtime.generation || combined.signal.aborted) return false;
      if (!refreshToken) {
        setAccessToken(runtime, null);
        return false;
      }
      const tokens = await operationClient.refreshSession(refreshToken, combined.signal);
      return commitTokens(tokens, operationGeneration, combined.signal, 'refresh');
    })();
    runtime.activeRefresh = operation;
    void operation.then(
      () => {
        if (runtime.activeRefresh === operation) runtime.activeRefresh = null;
        if (runtime.activeRefreshController === controller) runtime.activeRefreshController = null;
      },
      () => {
        if (runtime.activeRefresh === operation) runtime.activeRefresh = null;
        if (runtime.activeRefreshController === controller) runtime.activeRefreshController = null;
      },
    );
    return operation.finally(combined.cleanup);
  };

  const restore = async (signal?: AbortSignal): Promise<NativeSessionState> => {
    if (runtime.activeLogoutCount > 0) return { status: 'signed-out', reason: 'canceled' };
    const restoreGeneration = runtime.generation;
    const controller = new AbortController();
    runtime.activeRestorations.add(controller);
    const combined = combineAbortSignals(signal, controller.signal);
    try {
      let refreshToken: string | null;
      try {
        refreshToken = await runtime.store.readRefresh();
      } catch {
        throw storageError();
      }
      if (restoreGeneration !== runtime.generation || combined.signal.aborted) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      if (!refreshToken) {
        setAccessToken(runtime, null);
        return { status: 'signed-out', reason: 'missing-refresh' };
      }
      const refreshed = await refresh(combined.signal);
      if (!refreshed || restoreGeneration !== runtime.generation || combined.signal.aborted) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      const account = await runtime.client.getCurrentAccount(combined.signal);
      return restoreGeneration === runtime.generation && !combined.signal.aborted
        ? { status: 'signed-in', account }
        : { status: 'signed-out', reason: 'canceled' };
    } catch (error) {
      if (restoreGeneration !== runtime.generation || combined.signal.aborted) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      if (isUnauthorized(error)) {
        const localCleared = await invalidateLocal();
        return localCleared
          ? { status: 'signed-out', reason: 'session-invalid' }
          : { status: 'unavailable', reason: 'storage' };
      }
      if (isCloudError(error) && error.code === 'secure_store') {
        await clearAndInvalidate();
        return { status: 'unavailable', reason: 'storage' };
      }
      if (isTransient(error)) return { status: 'offline-with-session' };
      return { status: 'unavailable', reason: 'auth' };
    } finally {
      combined.cleanup();
      runtime.activeRestorations.delete(controller);
    }
  };

  const completeSignIn = async (
    input: NativeGoogleCodeExchangeInput,
    signal?: AbortSignal,
  ): Promise<NativeSessionState> => {
    const signInGeneration = ++runtime.generation;
    abortActiveWork();
    const controller = new AbortController();
    runtime.activeSignInController = controller;
    const combined = combineAbortSignals(signal, controller.signal);
    const operationClient = runtime.client;

    try {
      if (combined.signal.aborted) return { status: 'signed-out', reason: 'canceled' };
      const tokens = await operationClient.exchangeGoogleCode(input, combined.signal);
      if (signInGeneration !== runtime.generation || combined.signal.aborted) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      const committed = await commitTokens(tokens, signInGeneration, combined.signal, 'sign-in');
      if (!committed) return { status: 'signed-out', reason: 'canceled' };
      const account = await runtime.client.getCurrentAccount(combined.signal);
      return signInGeneration === runtime.generation && !combined.signal.aborted
        ? { status: 'signed-in', account }
        : { status: 'signed-out', reason: 'canceled' };
    } catch (error) {
      if (signInGeneration !== runtime.generation || combined.signal.aborted) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      if (isUnauthorized(error)) {
        const localCleared = await invalidateLocal();
        return localCleared
          ? { status: 'signed-out', reason: 'session-invalid' }
          : { status: 'unavailable', reason: 'storage' };
      }
      if (isCloudError(error) && error.code === 'secure_store') {
        await markStorageUnavailable();
        return { status: 'unavailable', reason: 'storage' };
      }
      if (isTransient(error)) return { status: 'offline-with-session' };
      return { status: 'unavailable', reason: 'auth' };
    } finally {
      combined.cleanup();
      if (runtime.activeSignInController === controller) runtime.activeSignInController = null;
    }
  };

  const cancelSignIn = async (): Promise<void> => {
    const canceledGeneration = ++runtime.generation;
    runtime.activeSignInController?.abort();
    const cleared = await enqueueStorage(runtime, async () => {
      if (runtime.signInTokenGeneration === null || runtime.signInTokenGeneration >= canceledGeneration) return true;
      const localCleared = await clearStore(runtime);
      if (localCleared) runtime.signInTokenGeneration = null;
      return localCleared;
    });
    if (!cleared) throw storageError();
  };

  const withRefresh = async <T>(operation: () => Promise<T>): Promise<T> => {
    try {
      return await operation();
    } catch (error) {
      if (!isUnauthorized(error)) throw error;
      let refreshed: boolean;
      try {
        refreshed = await refresh();
      } catch (refreshError) {
        if (isUnauthorized(refreshError)) {
          if (!(await invalidateLocal())) throw storageError();
        }
        if (isCloudError(refreshError) && refreshError.code === 'secure_store') {
          await markStorageUnavailable();
        }
        throw refreshError;
      }
      if (!refreshed) {
        if (!(await invalidateLocal())) throw storageError();
        throw error;
      }
      return operation();
    }
  };

  const logout = async (signal?: AbortSignal): Promise<NativeSessionLogoutResult> => {
    runtime.activeLogoutCount += 1;
    runtime.generation += 1;
    abortActiveWork();
    if (runtime.activeRefresh) {
      try {
        await runtime.activeRefresh;
      } catch {
        // Logout still clears local state after a refresh race.
      }
    }

    let serverConfirmed = false;
    try {
      let refreshToken: string | null;
      try {
        refreshToken = await runtime.store.readRefresh();
      } catch {
        refreshToken = null;
      }
      if (refreshToken) {
        try {
          await runtime.client.logout(refreshToken, runtime.accessToken ?? undefined, signal);
          serverConfirmed = true;
        } catch {
          serverConfirmed = false;
        }
      }
    } catch {
      serverConfirmed = false;
    } finally {
      const localCleared = await enqueueStorage(runtime, async () => {
        const cleared = await clearStore(runtime);
        if (cleared) runtime.signInTokenGeneration = null;
        return cleared;
      });
      runtime.activeLogoutCount -= 1;
      return { status: 'signed-out', serverConfirmed, localCleared };
    }
  };

  return {
    restore,
    completeSignIn,
    cancelSignIn,
    refresh,
    withRefresh,
    logout,
    clearLocal: clearAndInvalidate,
    getAccessToken: () => runtime.accessToken,
  };
}
