import { describe, expect, it, vi } from 'vitest';

import type { NativeAuthClient } from '@allies/cloud-client';

import { createGoogleSignInFlow, type GoogleSignInFlowOptions } from './google-sign-in';
import { deliverNativeAuthReturn } from './native-auth-return';

vi.mock('expo-web-browser', () => ({
  dismissBrowser: vi.fn(),
  openAuthSessionAsync: vi.fn(),
}));

vi.mock('./pkce-attempt', () => ({
  createPkceAttempt: vi.fn(async () => ({
    codeVerifier: 'verifier-example',
    codeChallenge: 'challenge-example',
    state: 'state-example',
  })),
}));

function createOptions(overrides: Partial<GoogleSignInFlowOptions> = {}): GoogleSignInFlowOptions {
  const client: Pick<NativeAuthClient, 'beginGoogleSignIn'> = {
    beginGoogleSignIn: vi.fn(async () => ({
      authorizationUrl: 'https://accounts.google.com/o/oauth2/auth',
      expiresAt: '2026-08-21T12:00:00Z',
    })),
  };

  return {
    client,
    redirectUri: 'https://mobile.example/auth/return',
    completeSignIn: vi.fn(async () => ({
      status: 'signed-in' as const,
      account: {
        userId: 'usr_example',
        displayName: 'Example User',
        avatarUrl: null,
        session: { id: 'ses_example', expiresAt: '2026-08-21T12:00:00Z' },
        workspace: { id: 'wsp_example', name: 'Personal Workspace', role: 'owner', capabilities: [] },
      },
    })),
    openAuthSession: vi.fn(async () => ({
      type: 'success' as const,
      url: 'https://mobile.example/auth/return?code=cloud-code&state=state-example',
    })),
    ...overrides,
  };
}

describe('createGoogleSignInFlow', () => {
  it('starts one PKCE attempt and exchanges only the matching callback', async () => {
    const options = createOptions();
    const flow = createGoogleSignInFlow(options);

    await expect(flow.start()).resolves.toEqual({ status: 'signed-in' });
    expect(options.client.beginGoogleSignIn).toHaveBeenCalledWith({
      redirectUri: 'https://mobile.example/auth/return',
      codeChallenge: 'challenge-example',
      state: 'state-example',
    });
    expect(options.openAuthSession).toHaveBeenCalledWith(
      'https://accounts.google.com/o/oauth2/auth',
      'https://mobile.example/auth/return',
    );
    expect(options.completeSignIn).toHaveBeenCalledWith({
      code: 'cloud-code',
      codeVerifier: 'verifier-example',
      redirectUri: 'https://mobile.example/auth/return',
    });
  });

  it('does not exchange a canceled browser session', async () => {
    const options = createOptions({
      openAuthSession: vi.fn(async () => ({ type: 'cancel' as const })) as unknown as NonNullable<GoogleSignInFlowOptions['openAuthSession']>,
    });
    const flow = createGoogleSignInFlow(options);

    await expect(flow.start()).resolves.toEqual({ status: 'canceled' });
    expect(options.completeSignIn).not.toHaveBeenCalled();
  });

  it('discards a callback with a mismatched state', async () => {
    const options = createOptions({
      openAuthSession: vi.fn(async () => ({
        type: 'success' as const,
        url: 'https://mobile.example/auth/return?code=cloud-code&state=wrong-state',
      })),
    });
    const flow = createGoogleSignInFlow(options);

    await expect(flow.start()).resolves.toEqual({ status: 'failed', reason: 'invalid-return' });
    expect(options.completeSignIn).not.toHaveBeenCalled();
  });

  it('accepts a return delivered through the native app-link route', async () => {
    const options = createOptions({
      openAuthSession: vi.fn(() => new Promise<never>(() => undefined)),
    });
    const flow = createGoogleSignInFlow(options);
    const result = flow.start();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(deliverNativeAuthReturn('https://mobile.example/auth/return?code=cloud-code&state=state-example')).toBe(true);
    await expect(result).resolves.toEqual({ status: 'signed-in' });
    expect(options.completeSignIn).toHaveBeenCalledWith({
      code: 'cloud-code',
      codeVerifier: 'verifier-example',
      redirectUri: 'https://mobile.example/auth/return',
    });
  });
});
