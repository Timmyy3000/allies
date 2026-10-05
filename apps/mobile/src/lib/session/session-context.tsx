import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { isCloudError, type AccountViewModel, type CloudClient, type NativeGoogleCodeExchangeInput } from '@allies/cloud-client';

import type { NativeAuthCompletionMode } from '../env';
import { selectMobileReturnTo } from './session-route';
import {
  createGoogleSignInFlow,
  type GoogleSignInFlow,
  type GoogleSignInFlowStatus,
  type GoogleSignInOutcome,
} from '../../features/auth/google-sign-in';

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
  nativeAuthCompletionMode: NativeAuthCompletionMode;
  adapter: NativeSessionAdapter | null;
  restore(signal?: AbortSignal): Promise<SessionActionState>;
  completeSignIn(input: NativeGoogleCodeExchangeInput, signal?: AbortSignal): Promise<NativeSessionState>;
  cancelSignIn(): Promise<void>;
  googleSignInStatus: GoogleSignInFlowStatus;
  googleSignInOutcome: GoogleSignInOutcome | null;
  googleSignInManualCodeError: boolean;
  googleSignInReturnTo: string | null;
  startGoogleSignIn(returnTo?: unknown): Promise<GoogleSignInOutcome>;
  submitGoogleSignInCode(rawCode: string): Promise<GoogleSignInOutcome | null>;
  cancelGoogleSignIn(): Promise<void>;
  clearGoogleSignInReturnTo(): void;
  refresh(signal?: AbortSignal): Promise<boolean>;
  logout(signal?: AbortSignal): Promise<NativeSessionLogoutResult>;
  clearLocal(): Promise<void>;
}

interface NativeSessionProviderProps {
  children: ReactNode;
  client?: NativeSessionClient;
  accountClient?: CloudClient;
  nativeAuthRedirectUri?: string | null;
  nativeAuthCompletionMode?: NativeAuthCompletionMode;
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
  nativeAuthCompletionMode = 'redirect',
  nativeAuthRedirectUri = null,
  store,
  onSessionCleared,
}: NativeSessionProviderProps) {
  const [state, setState] = useState<SessionActionState>(
    client && store ? { status: 'checking' } : unavailableSession,
  );
  const operationRef = useRef(0);

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

  const [googleSignInStatus, setGoogleSignInStatus] = useState<GoogleSignInFlowStatus>('idle');
  const [googleSignInOutcome, setGoogleSignInOutcome] = useState<GoogleSignInOutcome | null>(null);
  const [googleSignInManualCodeError, setGoogleSignInManualCodeError] = useState(false);
  const [googleSignInReturnTo, setGoogleSignInReturnTo] = useState<string | null>(null);
  const googleFlowRef = useRef<GoogleSignInFlow | null>(null);
  const googleFlowConfigRef = useRef<{
    client: NativeSessionClient;
    redirectUri: string;
    completionMode: NativeAuthCompletionMode;
  } | null>(null);
  const googleFlowLoadRef = useRef(0);
  const providerAliveRef = useRef(true);

  useEffect(() => {
    if (!adapter) return undefined;

    const operation = ++operationRef.current;
    const controller = new AbortController();
    void adapter.restore(controller.signal).then((next) => {
      if (!controller.signal.aborted && operation === operationRef.current) applyState(next);
    });

    return () => controller.abort();
  }, [adapter, applyState]);

  const restore = useCallback(
    async (signal?: AbortSignal) => {
      if (!adapter) return unavailableSession;
      const operation = ++operationRef.current;
      const next = await adapter.restore(signal);
      if (!signal?.aborted && operation === operationRef.current) applyState(next);
      return next;
    },
    [adapter, applyState],
  );

  const completeSignIn = useCallback(
    async (input: NativeGoogleCodeExchangeInput, signal?: AbortSignal) => {
      if (!adapter) return { status: 'unavailable', reason: 'auth' } as const;
      const operation = ++operationRef.current;
      setState({ status: 'refreshing' });
      const next = await adapter.completeSignIn(input, signal);
      if (!signal?.aborted && operation === operationRef.current) applyState(next);
      return next;
    },
    [adapter, applyState],
  );

  const cancelSignIn = useCallback(async () => {
    const operation = ++operationRef.current;
    try {
      await adapter?.cancelSignIn();
      if (operation === operationRef.current) applyState({ status: 'signed-out', reason: 'canceled' });
    } catch {
      if (operation === operationRef.current) applyState({ status: 'unavailable', reason: 'storage' });
    }
  }, [adapter, applyState]);

  const getGoogleSignInFlow = useCallback(async (): Promise<GoogleSignInFlow | null> => {
    if (!providerAliveRef.current || !client || !nativeAuthRedirectUri) return null;

    const existingConfig = googleFlowConfigRef.current;
    if (
      googleFlowRef.current
      && existingConfig?.client === client
      && existingConfig.redirectUri === nativeAuthRedirectUri
      && existingConfig.completionMode === nativeAuthCompletionMode
    ) {
      return googleFlowRef.current;
    }

    const load = ++googleFlowLoadRef.current;
    void googleFlowRef.current?.cancel();
    let linking: typeof import('expo-linking');
    let webBrowser: typeof import('expo-web-browser');
    let pkce: typeof import('../../features/auth/pkce-attempt');
    try {
      [linking, webBrowser, pkce] = await Promise.all([
        import('expo-linking'),
        import('expo-web-browser'),
        import('../../features/auth/pkce-attempt'),
      ]);
    } catch {
      return null;
    }
    if (!providerAliveRef.current || load !== googleFlowLoadRef.current) return null;
    const flow = createGoogleSignInFlow({
      cancelSignIn,
      client,
      completionMode: nativeAuthCompletionMode,
      completeSignIn,
      createAttempt: pkce.createPkceAttempt,
      dismissBrowser: webBrowser.dismissBrowser,
      onManualCodeError: () => {
        if (providerAliveRef.current) setGoogleSignInManualCodeError(true);
      },
      onStatusChange: (status) => {
        if (providerAliveRef.current) setGoogleSignInStatus(status);
      },
      openAuthSession: webBrowser.openAuthSessionAsync,
      openURL: linking.openURL,
      redirectUri: nativeAuthRedirectUri,
    });
    googleFlowRef.current = flow;
    googleFlowConfigRef.current = {
      client,
      completionMode: nativeAuthCompletionMode,
      redirectUri: nativeAuthRedirectUri,
    };
    return flow;
  }, [cancelSignIn, client, completeSignIn, nativeAuthCompletionMode, nativeAuthRedirectUri]);

  const startGoogleSignIn = useCallback(async (returnTo?: unknown): Promise<GoogleSignInOutcome> => {
    const target = selectMobileReturnTo(returnTo);
    if (!providerAliveRef.current) return { status: 'canceled' };
    setGoogleSignInReturnTo(target);
    setGoogleSignInOutcome(null);
    setGoogleSignInManualCodeError(false);
    setGoogleSignInStatus('opening-browser');
    const flow = await getGoogleSignInFlow();
    if (!providerAliveRef.current) return { status: 'canceled' };
    if (!flow) {
      setGoogleSignInStatus('idle');
      const unavailable: GoogleSignInOutcome = { status: 'failed', reason: 'unavailable' };
      setGoogleSignInOutcome(unavailable);
      return unavailable;
    }

    const outcome = await flow.start();
    if (providerAliveRef.current) setGoogleSignInOutcome(outcome);
    return outcome;
  }, [getGoogleSignInFlow]);

  const submitGoogleSignInCode = useCallback(async (rawCode: string): Promise<GoogleSignInOutcome | null> => {
    if (!providerAliveRef.current) return null;
    setGoogleSignInManualCodeError(false);
    const outcome = await googleFlowRef.current?.submitManualCode(rawCode);
    if (outcome && providerAliveRef.current) setGoogleSignInOutcome(outcome);
    return outcome ?? null;
  }, []);

  const cancelGoogleSignIn = useCallback(async () => {
    await googleFlowRef.current?.cancel();
  }, []);

  const clearGoogleSignInReturnTo = useCallback(() => {
    setGoogleSignInReturnTo(null);
  }, []);

  useEffect(() => {
    providerAliveRef.current = true;
    return () => {
      providerAliveRef.current = false;
      googleFlowLoadRef.current += 1;
      const flow = googleFlowRef.current;
      googleFlowRef.current = null;
      googleFlowConfigRef.current = null;
      void flow?.cancel();
    };
  }, []);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!adapter) return false;
      const operation = ++operationRef.current;
      try {
        const refreshed = await adapter.refresh(signal);
        if (!signal?.aborted && operation === operationRef.current && !refreshed) {
          applyState({ status: 'signed-out', reason: 'missing-refresh' });
        }
        return refreshed;
      } catch (error) {
        if (isCloudError(error) && error.code === 'secure_store') {
          await adapter.clearLocal();
          if (!signal?.aborted && operation === operationRef.current) applyState({ status: 'unavailable', reason: 'storage' });
          return false;
        }
        if (isCloudError(error) && error.kind === 'unauthorized') {
          const localCleared = await adapter.clearLocal();
          if (!signal?.aborted && operation === operationRef.current) {
            applyState(localCleared
              ? { status: 'signed-out', reason: 'session-invalid' }
              : { status: 'unavailable', reason: 'storage' });
          }
          return false;
        }
        throw error;
      }
    },
    [adapter, applyState],
  );

  const logout = useCallback(
    async (signal?: AbortSignal) => {
      operationRef.current += 1;
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
    operationRef.current += 1;
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
      nativeAuthCompletionMode,
      nativeAuthRedirectUri,
      googleSignInManualCodeError,
      googleSignInOutcome,
      googleSignInReturnTo,
      googleSignInStatus,
      startGoogleSignIn,
      submitGoogleSignInCode,
      cancelGoogleSignIn,
      clearGoogleSignInReturnTo,
      adapter,
      cancelSignIn,
      restore,
      completeSignIn,
      refresh,
      logout,
      clearLocal,
    }),
    [
      accountClient,
      cancelSignIn,
      adapter,
      clearLocal,
      client,
      completeSignIn,
      logout,
      nativeAuthRedirectUri,
      nativeAuthCompletionMode,
      cancelGoogleSignIn,
      clearGoogleSignInReturnTo,
      googleSignInManualCodeError,
      googleSignInOutcome,
      googleSignInReturnTo,
      googleSignInStatus,
      refresh,
      restore,
      state,
      startGoogleSignIn,
      submitGoogleSignInCode,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useNativeSession(): NativeSessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error('useNativeSession must be used within NativeSessionProvider');
  return value;
}
