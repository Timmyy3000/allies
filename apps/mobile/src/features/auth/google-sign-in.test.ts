import { describe, expect, it, vi } from 'vitest';

import type { NativeAuthClient } from '@allies/cloud-client';

import { deliverNativeAuthReturn } from './native-auth-return';
import { createGoogleSignInFlow, type GoogleSignInFlowOptions } from './google-sign-in';

function createOptions(overrides: Partial<GoogleSignInFlowOptions> = {}): GoogleSignInFlowOptions {
  const client: Pick<NativeAuthClient, 'beginGoogleSignIn'> = {
    beginGoogleSignIn: vi.fn(async () => ({
      authorizationUrl: 'https://accounts.google.com/o/oauth2/auth',
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
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
    createAttempt: vi.fn(async () => ({
      codeVerifier: 'verifier-example',
      codeChallenge: 'challenge-example',
      state: 'state-example',
    })),
    openAuthSession: vi.fn(async () => ({
      type: 'success' as const,
      url: 'https://mobile.example/auth/return?code=cloud-code&state=state-example',
    })),
    ...overrides,
  };
}

describe('createGoogleSignInFlow', () => {
  it('reports a browser dispatch failure as unavailable', async () => {
    const options = createOptions({ completionMode: 'manual_code', openURL: vi.fn().mockRejectedValue(new Error('dispatch failed')) });
    await expect(createGoogleSignInFlow(options).start()).resolves.toEqual({ status: 'failed', reason: 'unavailable' });
  });

  it('expires a manual attempt and releases it for retry', async () => {
    vi.useFakeTimers();
    try {
      const options = createOptions({ completionMode: 'manual_code', openURL: vi.fn(async () => true), cancelSignIn: vi.fn(async () => undefined) });
      const flow = createGoogleSignInFlow(options);
      const started = flow.start();
      await vi.advanceTimersByTimeAsync(300_001);
      await expect(started).resolves.toEqual({ status: 'failed', reason: 'invalid-return' });
      expect(options.cancelSignIn).toHaveBeenCalledOnce();
      await expect(flow.submitManualCode('a'.repeat(43))).resolves.toBeNull();
      const retry = flow.start();
      await vi.advanceTimersByTimeAsync(0);
      await flow.cancel();
      await expect(retry).resolves.toEqual({ status: 'canceled' });
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('starts one PKCE attempt and exchanges only the matching callback', async () => {
    const options = createOptions();
    const flow = createGoogleSignInFlow(options);

    await expect(flow.start()).resolves.toEqual({ status: 'signed-in' });
    expect(options.client.beginGoogleSignIn).toHaveBeenCalledWith({
      redirectUri: 'https://mobile.example/auth/return',
      codeChallenge: 'challenge-example',
      state: 'state-example',
    }, expect.any(AbortSignal));
    expect(options.completeSignIn).toHaveBeenCalledWith({
      code: 'cloud-code',
      codeVerifier: 'verifier-example',
      redirectUri: 'https://mobile.example/auth/return',
    }, expect.any(AbortSignal));
  });

  it('does not exchange a canceled browser session', async () => {
    const options = createOptions({
      openAuthSession: vi.fn(async () => ({ type: 'cancel' as const })),
    });
    const flow = createGoogleSignInFlow(options);

    await expect(flow.start()).resolves.toEqual({ status: 'canceled' });
    expect(options.completeSignIn).not.toHaveBeenCalled();
  });

  it('rejects a callback with mismatched state', async () => {
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
  });

  it('does not allow a second start while the first browser flow is active', async () => {
    let resolveBrowser: ((value: { type: 'cancel' }) => void) | undefined;
    const options = createOptions({
      openAuthSession: vi.fn(() => new Promise<{ type: 'cancel' }>((resolve) => { resolveBrowser = resolve; })),
    });
    const flow = createGoogleSignInFlow(options);

    const first = flow.start();
    await new Promise((resolve) => setTimeout(resolve, 0));
    await expect(flow.start()).resolves.toEqual({ status: 'failed', reason: 'already-in-progress' });
    resolveBrowser?.({ type: 'cancel' });
    await expect(first).resolves.toEqual({ status: 'canceled' });
  });

  it('keeps manual mode waiting after the external browser opens', async () => {
    const statuses: string[] = [];
    const options = createOptions({
      completionMode: 'manual_code',
      onStatusChange: (status) => statuses.push(status),
      openURL: vi.fn(async () => true),
    });
    const flow = createGoogleSignInFlow(options);
    const started = flow.start();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(statuses).toContain('waiting-for-code');
    expect(options.client.beginGoogleSignIn).toHaveBeenCalledWith({
      redirectUri: 'https://mobile.example/auth/return',
      codeChallenge: 'challenge-example',
      state: 'state-example',
      completionMode: 'manual_code',
    }, expect.any(AbortSignal));
    expect(options.openURL).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/auth');
    expect(options.completeSignIn).not.toHaveBeenCalled();

    await expect(flow.submitManualCode('a'.repeat(43))).resolves.toEqual({ status: 'signed-in' });
    await expect(started).resolves.toEqual({ status: 'signed-in' });
  });

  it('keeps malformed pasted codes recoverable and submits only once', async () => {
    let resolveComplete: ((state: { status: 'signed-in'; account: unknown }) => void) | undefined;
    const options = createOptions({
      completionMode: 'manual_code',
      openURL: vi.fn(async () => true),
      completeSignIn: vi.fn(() => new Promise<{ status: 'signed-in'; account: unknown }>((resolve) => { resolveComplete = resolve; })),
    });
    const flow = createGoogleSignInFlow(options);
    const started = flow.start();
    await new Promise((resolve) => setTimeout(resolve, 0));

    await expect(flow.submitManualCode('bad code')).resolves.toBeNull();
    expect(options.completeSignIn).not.toHaveBeenCalled();

    const first = flow.submitManualCode('b'.repeat(43));
    const second = flow.submitManualCode('c'.repeat(43));
    expect(await second).toBeNull();
    resolveComplete?.({ status: 'signed-in', account: {} });
    await expect(first).resolves.toEqual({ status: 'signed-in' });
    await expect(started).resolves.toEqual({ status: 'signed-in' });
    expect(options.completeSignIn).toHaveBeenCalledOnce();
  });

  it('cancels a waiting manual attempt and asks the session authority to invalidate it', async () => {
    const cancelSignIn = vi.fn(async () => undefined);
    const options = createOptions({
      cancelSignIn,
      completionMode: 'manual_code',
      openURL: vi.fn(async () => true),
    });
    const flow = createGoogleSignInFlow(options);
    const started = flow.start();
    await new Promise((resolve) => setTimeout(resolve, 0));

    await flow.cancel();
    await expect(started).resolves.toEqual({ status: 'canceled' });
    expect(cancelSignIn).toHaveBeenCalledOnce();
  });

  it('does not let a late canceled exchange finish or block a fresh manual attempt', async () => {
    let resolveOld: ((state: { status: 'signed-in'; account: unknown }) => void) | undefined;
    const options = createOptions({
      completionMode: 'manual_code',
      openURL: vi.fn(async () => true),
      completeSignIn: vi.fn()
        .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
        .mockResolvedValue({ status: 'signed-in', account: {} }),
    });
    const flow = createGoogleSignInFlow(options);
    const first = flow.start();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const oldSubmission = flow.submitManualCode('a'.repeat(43));
    await flow.cancel();
    await expect(first).resolves.toEqual({ status: 'canceled' });
    const retry = flow.start();
    await new Promise((resolve) => setTimeout(resolve, 0));
    resolveOld?.({ status: 'signed-in', account: {} });
    await expect(oldSubmission).resolves.toEqual({ status: 'canceled' });
    await expect(flow.submitManualCode('b'.repeat(43))).resolves.toEqual({ status: 'signed-in' });
    await expect(retry).resolves.toEqual({ status: 'signed-in' });
  });
});
