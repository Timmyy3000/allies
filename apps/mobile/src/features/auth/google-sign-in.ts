import * as WebBrowser from 'expo-web-browser';

import {
  isCloudError,
  type NativeAuthClient,
  type NativeGoogleCodeExchangeInput,
} from '@allies/cloud-client';

import type { NativeSessionState } from '@/lib/session/native-session-adapter';

import { createPkceAttempt, type PkceAttempt } from './pkce-attempt';
import { registerNativeAuthReturnListener } from './native-auth-return';
import { parseNativeAuthReturn } from './pkce';

export type GoogleSignInFlowStatus =
  | 'idle'
  | 'opening-browser'
  | 'waiting-for-return'
  | 'exchanging';

export type GoogleSignInOutcome =
  | { status: 'signed-in' }
  | { status: 'canceled' }
  | { status: 'failed'; reason: 'invalid-return' | 'flow-failed' | 'unavailable' | 'already-in-progress' };

type OpenAuthSession = (
  authorizationUrl: string,
  redirectUri: string,
) => Promise<WebBrowser.WebBrowserAuthSessionResult>;

export interface GoogleSignInFlowOptions {
  client: Pick<NativeAuthClient, 'beginGoogleSignIn'>;
  redirectUri: string;
  completeSignIn: (input: NativeGoogleCodeExchangeInput) => Promise<NativeSessionState>;
  openAuthSession?: OpenAuthSession;
  createAttempt?: () => Promise<PkceAttempt>;
  onStatusChange?: (status: GoogleSignInFlowStatus) => void;
}

function failureFor(error: unknown): GoogleSignInOutcome {
  if (isCloudError(error) && ['network', 'timeout', 'server', 'throttled'].includes(error.kind)) {
    return { status: 'failed', reason: 'unavailable' };
  }
  return { status: 'failed', reason: 'flow-failed' };
}

function outcomeForSession(state: NativeSessionState): GoogleSignInOutcome {
  if (state.status === 'signed-in') return { status: 'signed-in' };
  if (state.status === 'signed-out' && state.reason === 'canceled') return { status: 'canceled' };
  if (state.status === 'offline-with-session' || state.status === 'unavailable') {
    return { status: 'failed', reason: 'unavailable' };
  }
  return { status: 'failed', reason: 'flow-failed' };
}

export function createGoogleSignInFlow(options: GoogleSignInFlowOptions) {
  const openAuthSession = options.openAuthSession ?? WebBrowser.openAuthSessionAsync;
  const createAttempt = options.createAttempt ?? createPkceAttempt;
  let active = false;

  const setStatus = (status: GoogleSignInFlowStatus) => options.onStatusChange?.(status);

  return {
    async start(): Promise<GoogleSignInOutcome> {
      if (active) return { status: 'failed', reason: 'already-in-progress' };
      active = true;
      setStatus('opening-browser');

      try {
        const attempt = await createAttempt();
        const start = await options.client.beginGoogleSignIn({
          redirectUri: options.redirectUri,
          codeChallenge: attempt.codeChallenge,
          state: attempt.state,
        });

        setStatus('waiting-for-return');
        let resolveNativeReturn: ((url: string) => void) | undefined;
        const nativeReturn = new Promise<string>((resolve) => {
          resolveNativeReturn = resolve;
        });
        const disposeNativeReturn = registerNativeAuthReturnListener((url) => resolveNativeReturn?.(url));
        let callbackUrl: string;
        try {
          const browserResult = await Promise.race([
            openAuthSession(start.authorizationUrl, options.redirectUri).then((result) => ({
              source: 'browser' as const,
              result,
            })),
            nativeReturn.then((url) => ({ source: 'app-link' as const, url })),
          ]);
          if (browserResult.source === 'app-link') {
            void WebBrowser.dismissBrowser();
            callbackUrl = browserResult.url;
          } else {
            if (browserResult.result.type !== 'success') return { status: 'canceled' };
            callbackUrl = browserResult.result.url;
          }
        } finally {
          disposeNativeReturn();
        }

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
        const session = await options.completeSignIn({
          code: authReturn.code,
          codeVerifier: attempt.codeVerifier,
          redirectUri: options.redirectUri,
        });
        return outcomeForSession(session);
      } catch (error) {
        return failureFor(error);
      } finally {
        active = false;
        setStatus('idle');
      }
    },
  };
}
