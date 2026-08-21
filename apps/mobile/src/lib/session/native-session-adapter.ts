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
  completeSignIn(input: NativeGoogleCodeExchangeInput): Promise<NativeSessionState>;
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

export function createNativeSessionAdapter(
  client: NativeSessionClient,
  store: NativeSessionStore,
  options: NativeSessionAdapterOptions = {},
): NativeSessionAdapter {
  let accessToken: string | null = null;
  let generation = 0;
  let activeRefresh: Promise<boolean> | null = null;
  let activeRefreshController: AbortController | null = null;
  let activeLogoutCount = 0;
  const activeRestorations = new Set<AbortController>();

  const setAccessToken = (token: string | null) => {
    accessToken = token;
    client.setAccessToken(token);
  };

  const clearLocalStorage = async (): Promise<boolean> => {
    setAccessToken(null);
    try {
      await store.clear();
      return true;
    } catch {
      return false;
    }
  };

  const clearAndInvalidate = async () => {
    generation += 1;
    for (const controller of activeRestorations) controller.abort();
    activeRefreshController?.abort();
    return clearLocalStorage();
  };

  const invalidateLocal = async () => {
    const localCleared = await clearAndInvalidate();
    if (localCleared) options.onSessionInvalidated?.();
    else options.onStorageUnavailable?.();
    return localCleared;
  };

  const markStorageUnavailable = async () => {
    const localCleared = await clearAndInvalidate();
    options.onStorageUnavailable?.();
    return localCleared;
  };

  const commitTokens = async (tokens: NativeSessionTokens) => {
    try {
      await store.writeRefresh(tokens.refreshToken);
    } catch {
      await clearLocalStorage();
      throw storageError();
    }
    setAccessToken(tokens.accessToken);
  };

  const refresh = (signal?: AbortSignal): Promise<boolean> => {
    if (activeRefresh) return activeRefresh;

    const controller = new AbortController();
    activeRefreshController = controller;
    const combined = combineAbortSignals(signal, controller.signal);
    const operation = (async () => {
      let refreshToken: string | null;
      try {
        refreshToken = await store.readRefresh();
      } catch {
        throw storageError();
      }
      if (!refreshToken) {
        setAccessToken(null);
        return false;
      }
      const tokens = await client.refreshSession(refreshToken, combined.signal);
      await commitTokens(tokens);
      return true;
    })();
    activeRefresh = operation;
    void operation.then(
      () => {
        if (activeRefresh === operation) activeRefresh = null;
        if (activeRefreshController === controller) activeRefreshController = null;
      },
      () => {
        if (activeRefresh === operation) activeRefresh = null;
        if (activeRefreshController === controller) activeRefreshController = null;
      },
    );
    return operation.finally(combined.cleanup);
  };

  const restore = async (signal?: AbortSignal): Promise<NativeSessionState> => {
    if (activeLogoutCount > 0) return { status: 'signed-out', reason: 'canceled' };
    const restoreGeneration = generation;
    const controller = new AbortController();
    activeRestorations.add(controller);
    const combined = combineAbortSignals(signal, controller.signal);
    try {
      let refreshToken: string | null;
      try {
        refreshToken = await store.readRefresh();
      } catch {
        throw storageError();
      }
      if (restoreGeneration !== generation) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      if (!refreshToken) {
        setAccessToken(null);
        return { status: 'signed-out', reason: 'missing-refresh' };
      }
      const refreshed = await refresh(combined.signal);
      if (!refreshed || restoreGeneration !== generation) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      const account = await client.getCurrentAccount(combined.signal);
      return restoreGeneration === generation
        ? { status: 'signed-in', account }
        : { status: 'signed-out', reason: 'canceled' };
    } catch (error) {
      if (restoreGeneration !== generation || combined.signal.aborted) {
        return { status: 'signed-out', reason: 'canceled' };
      }
      if (isUnauthorized(error)) {
        const localCleared = await clearLocalStorage();
        return localCleared
          ? { status: 'signed-out', reason: 'session-invalid' }
          : { status: 'unavailable', reason: 'storage' };
      }
      if (isCloudError(error) && error.code === 'secure_store') {
        await clearLocalStorage();
        return { status: 'unavailable', reason: 'storage' };
      }
      if (isTransient(error)) return { status: 'offline-with-session' };
      return { status: 'unavailable', reason: 'auth' };
    } finally {
      combined.cleanup();
      activeRestorations.delete(controller);
    }
  };

  const completeSignIn = async (input: NativeGoogleCodeExchangeInput): Promise<NativeSessionState> => {
    const signInGeneration = ++generation;
    for (const controller of activeRestorations) controller.abort();
    activeRefreshController?.abort();
    try {
      const tokens = await client.exchangeGoogleCode(input);
      await commitTokens(tokens);
      const account = await client.getCurrentAccount();
      return signInGeneration === generation
        ? { status: 'signed-in', account }
        : { status: 'signed-out', reason: 'canceled' };
    } catch (error) {
      if (isUnauthorized(error)) {
        const localCleared = await clearLocalStorage();
        return localCleared
          ? { status: 'signed-out', reason: 'session-invalid' }
          : { status: 'unavailable', reason: 'storage' };
      }
      if (isCloudError(error) && error.code === 'secure_store') {
        return { status: 'unavailable', reason: 'storage' };
      }
      if (isTransient(error)) return { status: 'offline-with-session' };
      return { status: 'unavailable', reason: 'auth' };
    }
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
    activeLogoutCount += 1;
    generation += 1;
    for (const controller of activeRestorations) controller.abort();
    activeRefreshController?.abort();
    if (activeRefresh) {
      try {
        await activeRefresh;
      } catch {
        // Logout still clears local state after a refresh race.
      }
    }

    let serverConfirmed = false;
    try {
      let refreshToken: string | null;
      try {
        refreshToken = await store.readRefresh();
      } catch {
        refreshToken = null;
      }
      if (refreshToken) {
        try {
          await client.logout(refreshToken, accessToken ?? undefined, signal);
          serverConfirmed = true;
        } catch {
          serverConfirmed = false;
        }
      }
    } catch {
      serverConfirmed = false;
    } finally {
      const localCleared = await clearLocalStorage();
      activeLogoutCount -= 1;
      return { status: 'signed-out', serverConfirmed, localCleared };
    }
  };

  return {
    restore,
    completeSignIn,
    refresh,
    withRefresh,
    logout,
    clearLocal: clearAndInvalidate,
    getAccessToken: () => accessToken,
  };
}
