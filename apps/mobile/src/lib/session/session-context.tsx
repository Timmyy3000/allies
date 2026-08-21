import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { isCloudError, type AccountViewModel, type CloudClient, type NativeGoogleCodeExchangeInput } from '@allies/cloud-client';

import {
  createNativeSessionAdapter,
  type NativeSessionAdapterOptions,
  type NativeSessionAdapter,
  type NativeSessionClient,
  type NativeSessionLogoutResult,
  type NativeSessionState,
} from './native-session-adapter';
import type { NativeSessionStore } from './secure-session-store';

export type { NativeSessionState } from './native-session-adapter';

type SessionActionState = NativeSessionState | { status: 'unavailable'; reason: 'native-session-contract-pending' };

export interface NativeSessionContextValue {
  state: SessionActionState;
  status: SessionActionState['status'];
  reason?: string;
  account: AccountViewModel | null;
  client: NativeSessionClient | null;
  accountClient: CloudClient | null;
  nativeAuthRedirectUri: string | null;
  adapter: NativeSessionAdapter | null;
  restore(signal?: AbortSignal): Promise<SessionActionState>;
  completeSignIn(input: NativeGoogleCodeExchangeInput): Promise<NativeSessionState>;
  refresh(signal?: AbortSignal): Promise<boolean>;
  logout(signal?: AbortSignal): Promise<NativeSessionLogoutResult>;
  clearLocal(): Promise<void>;
}

interface NativeSessionProviderProps {
  children: ReactNode;
  client?: NativeSessionClient;
  accountClient?: CloudClient;
  nativeAuthRedirectUri?: string | null;
  store?: NativeSessionStore;
  onSessionCleared?: () => void;
}

const unavailableSession: SessionActionState = {
  status: 'unavailable',
  reason: 'native-session-contract-pending',
};

const SessionContext = createContext<NativeSessionContextValue | null>(null);

export function NativeSessionProvider({
  children,
  client,
  accountClient,
  nativeAuthRedirectUri = null,
  store,
  onSessionCleared,
}: NativeSessionProviderProps) {
  const [state, setState] = useState<SessionActionState>(
    client && store ? { status: 'checking' } : unavailableSession,
  );

  const applyState = useCallback(
    (next: SessionActionState) => {
      setState(next);
      if (next.status === 'signed-out' || next.status === 'unavailable') onSessionCleared?.();
    },
    [onSessionCleared],
  );

  const adapterOptions: NativeSessionAdapterOptions = useMemo(
    () => ({
      onSessionInvalidated: () => applyState({ status: 'signed-out', reason: 'session-invalid' }),
      onStorageUnavailable: () => applyState({ status: 'unavailable', reason: 'storage' }),
    }),
    [applyState],
  );
  const [adapter] = useState<NativeSessionAdapter | null>(() =>
    client && store ? createNativeSessionAdapter(client, store, adapterOptions) : null,
  );

  useEffect(() => {
    if (!adapter) return undefined;

    const controller = new AbortController();
    void adapter.restore(controller.signal).then((next) => {
      if (!controller.signal.aborted) applyState(next);
    });

    return () => controller.abort();
  }, [adapter, applyState]);

  const restore = useCallback(
    async (signal?: AbortSignal) => {
      if (!adapter) return unavailableSession;
      const next = await adapter.restore(signal);
      applyState(next);
      return next;
    },
    [adapter, applyState],
  );

  const completeSignIn = useCallback(
    async (input: NativeGoogleCodeExchangeInput) => {
      if (!adapter) return { status: 'unavailable', reason: 'auth' } as const;
      setState({ status: 'refreshing' });
      const next = await adapter.completeSignIn(input);
      applyState(next);
      return next;
    },
    [adapter, applyState],
  );

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!adapter) return false;
      try {
        const refreshed = await adapter.refresh(signal);
        if (!refreshed) applyState({ status: 'signed-out', reason: 'missing-refresh' });
        return refreshed;
      } catch (error) {
        if (isCloudError(error) && error.code === 'secure_store') {
          await adapter.clearLocal();
          applyState({ status: 'unavailable', reason: 'storage' });
          return false;
        }
        if (isCloudError(error) && error.kind === 'unauthorized') {
          const localCleared = await adapter.clearLocal();
          applyState(localCleared
            ? { status: 'signed-out', reason: 'session-invalid' }
            : { status: 'unavailable', reason: 'storage' });
          return false;
        }
        throw error;
      }
    },
    [adapter, applyState],
  );

  const logout = useCallback(
    async (signal?: AbortSignal) => {
      if (!adapter) {
        applyState({ status: 'signed-out', reason: 'session-invalid' });
        return { status: 'signed-out', serverConfirmed: false, localCleared: true } as const;
      }
      const result = await adapter.logout(signal);
      applyState(result.localCleared
        ? { status: 'signed-out', reason: 'session-invalid' }
        : { status: 'unavailable', reason: 'storage' });
      return result;
    },
    [adapter, applyState],
  );

  const clearLocal = useCallback(async () => {
    const localCleared = (await adapter?.clearLocal()) ?? true;
    applyState(localCleared
      ? { status: 'signed-out', reason: 'session-invalid' }
      : { status: 'unavailable', reason: 'storage' });
  }, [adapter, applyState]);

  const value = useMemo<NativeSessionContextValue>(
    () => ({
      state,
      status: state.status,
      reason: 'reason' in state ? state.reason : undefined,
      account: state.status === 'signed-in' ? state.account : null,
      client: client ?? null,
      accountClient: accountClient ?? null,
      nativeAuthRedirectUri,
      adapter,
      restore,
      completeSignIn,
      refresh,
      logout,
      clearLocal,
    }),
    [
      accountClient,
      adapter,
      clearLocal,
      client,
      completeSignIn,
      logout,
      nativeAuthRedirectUri,
      refresh,
      restore,
      state,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useNativeSession(): NativeSessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useNativeSession must be used within NativeSessionProvider');
  return value;
}
