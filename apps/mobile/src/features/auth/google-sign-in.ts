import {
  isCloudError,
  type NativeAuthClient,
  type NativeGoogleCodeExchangeInput,
} from '@allies/cloud-client';

import { registerNativeAuthReturnListener } from './native-auth-return';
import type { PkceAttempt } from './pkce-attempt';
import { parseNativeAuthReturn } from './pkce';

type NativeSignInSessionState =
  | { status: 'checking' }
  | { status: 'refreshing' }
  | { status: 'signed-out'; reason: 'missing-refresh' | 'session-invalid' | 'canceled' }
  | { status: 'signed-in'; account: unknown }
  | { status: 'offline-with-session' }
  | { status: 'unavailable'; reason: 'storage' | 'auth' };

export type GoogleSignInCompletionMode = 'redirect' | 'manual_code';

export type GoogleSignInFlowStatus =
  | 'idle'
  | 'opening-browser'
  | 'waiting-for-return'
  | 'waiting-for-code'
  | 'exchanging';

export type GoogleSignInOutcome =
  | { status: 'signed-in' }
  | { status: 'canceled' }
  | { status: 'failed'; reason: 'invalid-return' | 'flow-failed' | 'unavailable' | 'already-in-progress' };

export interface GoogleSignInFlow {
  start(): Promise<GoogleSignInOutcome>;
  submitManualCode(rawCode: string): Promise<GoogleSignInOutcome | null>;
  cancel(outcome?: GoogleSignInOutcome): Promise<void>;
}

type OpenAuthSession = (
  authorizationUrl: string,
  redirectUri: string,
) => Promise<{ type: string; url?: string }>;

type OpenExternalUrl = (authorizationUrl: string) => Promise<unknown>;

export interface GoogleSignInFlowOptions {
  client: Pick<NativeAuthClient, 'beginGoogleSignIn'>;
  redirectUri: string;
  completionMode?: GoogleSignInCompletionMode;
  completeSignIn: (
    input: NativeGoogleCodeExchangeInput,
    signal?: AbortSignal,
  ) => Promise<NativeSignInSessionState>;
  openAuthSession?: OpenAuthSession;
  openURL?: OpenExternalUrl;
  dismissBrowser?: () => void | Promise<unknown>;
  cancelSignIn?: () => void | Promise<unknown>;
  createAttempt: () => Promise<PkceAttempt>;
  onStatusChange?: (status: GoogleSignInFlowStatus) => void;
  onManualCodeError?: () => void;
}

const manualCodePattern = /^[A-Za-z0-9_-]{43}$/u;

function failureFor(error: unknown): GoogleSignInOutcome {
  if (isCloudError(error) && error.kind === 'aborted') return { status: 'canceled' };
  if (isCloudError(error) && ['network', 'timeout', 'server', 'throttled'].includes(error.kind)) {
    return { status: 'failed', reason: 'unavailable' };
  }
  return { status: 'failed', reason: 'flow-failed' };
}

function outcomeForSession(state: NativeSignInSessionState): GoogleSignInOutcome {
  if (state.status === 'signed-in') return { status: 'signed-in' };
  if (state.status === 'signed-out' && state.reason === 'canceled') return { status: 'canceled' };
  if (state.status === 'offline-with-session' || state.status === 'unavailable') {
    return { status: 'failed', reason: 'unavailable' };
  }
  return { status: 'failed', reason: 'flow-failed' };
}

export function createGoogleSignInFlow(options: GoogleSignInFlowOptions): GoogleSignInFlow {
  const completionMode = options.completionMode ?? 'redirect';
  let active = false;
  let attempt: PkceAttempt | null = null;
  let beginController: AbortController | null = null;
  let exchangeController: AbortController | null = null;
  let manualSubmitPromise: Promise<GoogleSignInOutcome> | null = null;
  let resolvePendingOutcome: ((outcome: GoogleSignInOutcome) => void) | null = null;
  let cancellationCleanup: Promise<unknown> | null = null;
  let expiryTimer: ReturnType<typeof setTimeout> | null = null;

  const setStatus = (status: GoogleSignInFlowStatus) => options.onStatusChange?.(status);

  const cancel = async (outcome: GoogleSignInOutcome = { status: 'canceled' }): Promise<void> => {
    if (!active) return;
    beginController?.abort();
    exchangeController?.abort();
    if (completionMode === 'redirect') {
      void Promise.resolve().then(() => options.dismissBrowser?.()).catch(() => undefined);
    }
    cancellationCleanup = Promise.resolve(options.cancelSignIn?.()).catch(() => undefined);
    resolvePendingOutcome?.(outcome);
    await cancellationCleanup;
  };

  const submitManualCode = async (rawCode: string): Promise<GoogleSignInOutcome | null> => {
    if (!active || beginController?.signal.aborted || completionMode !== 'manual_code' || !attempt || manualSubmitPromise) return null;
    if (typeof rawCode !== 'string' || !manualCodePattern.test(rawCode.trim())) {
      options.onManualCodeError?.();
      return null;
    }

    const code = rawCode.trim();
    setStatus('exchanging');
    const controller = new AbortController();
    const resolveOutcome = resolvePendingOutcome;
    exchangeController = controller;
    const exchangeInput = {
      code,
      codeVerifier: attempt.codeVerifier,
      redirectUri: options.redirectUri,
    };
    const exchange = options.completeSignIn(exchangeInput, controller.signal);
    manualSubmitPromise = exchange
      .then(outcomeForSession, failureFor)
      .then((outcome) => {
        if (controller.signal.aborted) return { status: 'canceled' } as const;
        resolveOutcome?.(outcome);
        return outcome;
      });
    try {
      return await manualSubmitPromise;
    } finally {
      if (exchangeController === controller) {
        manualSubmitPromise = null;
        exchangeController = null;
      }
    }
  };

  const start = async (): Promise<GoogleSignInOutcome> => {
    if (active) return { status: 'failed', reason: 'already-in-progress' };
    active = true;
    attempt = null;
    beginController = new AbortController();
    setStatus('opening-browser');

    try {
      attempt = await options.createAttempt();
      if (beginController.signal.aborted) return { status: 'canceled' };
      const input = {
        redirectUri: options.redirectUri,
        codeChallenge: attempt.codeChallenge,
        state: attempt.state,
        ...(completionMode === 'manual_code' ? { completionMode } : {}),
      };
      const startResult = await options.client.beginGoogleSignIn(input, beginController.signal);
      if (beginController.signal.aborted) return { status: 'canceled' };

      if (completionMode === 'manual_code') {
        if (!options.openURL) return { status: 'failed', reason: 'unavailable' };
        try {
          await options.openURL(startResult.authorizationUrl);
        } catch {
          return { status: 'failed', reason: 'unavailable' };
        }
        if (beginController.signal.aborted) return { status: 'canceled' };
        setStatus('waiting-for-code');
        return await new Promise<GoogleSignInOutcome>((resolve) => {
          resolvePendingOutcome = resolve;
          expiryTimer = setTimeout(() => {
            void cancel({ status: 'failed', reason: 'invalid-return' });
          }, Math.max(0, Date.parse(startResult.expiresAt) - Date.now()));
        });
      }

      setStatus('waiting-for-return');
      let resolveNativeReturn: ((url: string) => void) | undefined;
      const nativeReturn = new Promise<string>((resolve) => {
        resolveNativeReturn = resolve;
      });
      const disposeNativeReturn = registerNativeAuthReturnListener((url) => resolveNativeReturn?.(url));
      const canceled = new Promise<GoogleSignInOutcome>((resolve) => {
        resolvePendingOutcome = resolve;
      });
      let callbackUrl: string;
      try {
        if (!options.openAuthSession) return { status: 'failed', reason: 'unavailable' };
        const browserResult = await Promise.race([
          options.openAuthSession(startResult.authorizationUrl, options.redirectUri).then((result) => ({
            source: 'browser' as const,
            result,
          })),
          nativeReturn.then((url) => ({ source: 'app-link' as const, url })),
          canceled.then((outcome) => ({ source: 'canceled' as const, outcome })),
        ]);
        if (browserResult.source === 'canceled') return browserResult.outcome;
        if (browserResult.source === 'app-link') {
          void Promise.resolve().then(() => options.dismissBrowser?.()).catch(() => undefined);
          callbackUrl = browserResult.url;
        } else {
          if (browserResult.result.type !== 'success' || !browserResult.result.url) {
            return { status: 'canceled' };
          }
          callbackUrl = browserResult.result.url;
        }
      } finally {
        disposeNativeReturn();
      }

      if (beginController.signal.aborted) return { status: 'canceled' };
      const authReturn = parseNativeAuthReturn(callbackUrl, attempt.state, options.redirectUri);
      if (authReturn.status === 'canceled') return authReturn;
      if (authReturn.status === 'error') {
        return {
          status: 'failed',
          reason: authReturn.reason === 'state-mismatch' || authReturn.reason === 'invalid-return'
            ? 'invalid-return'
            : 'flow-failed',
        };
      }

      setStatus('exchanging');
      exchangeController = new AbortController();
      const exchangeInput = {
        code: authReturn.code,
        codeVerifier: attempt.codeVerifier,
        redirectUri: options.redirectUri,
      };
      const session = await options.completeSignIn(exchangeInput, exchangeController.signal);
      return outcomeForSession(session);
    } catch (error) {
      if (beginController?.signal.aborted) return { status: 'canceled' };
      return failureFor(error);
    } finally {
      if (expiryTimer !== null) clearTimeout(expiryTimer);
      expiryTimer = null;
      await cancellationCleanup;
      active = false;
      attempt = null;
      beginController = null;
      exchangeController = null;
      manualSubmitPromise = null;
      resolvePendingOutcome = null;
      cancellationCleanup = null;
      setStatus('idle');
    }
  };

  return {
    start,
    submitManualCode,
    cancel,
  };
}
