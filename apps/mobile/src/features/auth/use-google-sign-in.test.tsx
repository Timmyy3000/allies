// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useGoogleSignIn } from './use-google-sign-in';

const mocks = vi.hoisted(() => ({
  cancel: vi.fn(async () => undefined),
  start: vi.fn(async () => ({ status: 'signed-in' as const })),
  submit: vi.fn(async () => ({ status: 'signed-in' as const })),
}));

vi.mock('../../lib/session/session-context', () => ({
  useNativeSession: () => ({
    account: null,
    accountClient: null,
    adapter: {},
    cancelGoogleSignIn: mocks.cancel,
    cancelSignIn: vi.fn(async () => undefined),
    clearGoogleSignInReturnTo: vi.fn(),
    clearLocal: vi.fn(async () => undefined),
    client: { beginGoogleSignIn: vi.fn() },
    completeSignIn: vi.fn(async () => ({ status: 'signed-in', account: {} })),
    googleSignInManualCodeError: false,
    googleSignInOutcome: null,
    googleSignInReturnTo: null,
    googleSignInStatus: 'idle',
    logout: vi.fn(async () => ({ status: 'signed-out', serverConfirmed: false, localCleared: true })),
    nativeAuthCompletionMode: 'manual_code',
    nativeAuthRedirectUri: 'https://mobile.example/auth/callback',
    reason: undefined,
    refresh: vi.fn(async () => true),
    restore: vi.fn(async () => ({ status: 'signed-out', reason: 'missing-refresh' })),
    startGoogleSignIn: mocks.start,
    status: 'signed-out',
    submitGoogleSignInCode: mocks.submit,
    state: { status: 'signed-out', reason: 'missing-refresh' },
  }),
}));

describe('useGoogleSignIn provider bridge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps the return target in the provider-owned start call after the screen unmounts', async () => {
    const { result, unmount } = renderHook(useGoogleSignIn);

    await act(async () => {
      await result.current.start('/allies/new/complete');
    });

    expect(mocks.start).toHaveBeenCalledWith('/allies/new/complete');
    unmount();
    expect(mocks.cancel).not.toHaveBeenCalled();
  });

  it('delegates manual code submission and explicit cancellation to the provider', async () => {
    const { result } = renderHook(useGoogleSignIn);

    await act(async () => {
      await result.current.submitManualCode('a'.repeat(43));
      await result.current.cancel();
    });

    expect(mocks.submit).toHaveBeenCalledWith('a'.repeat(43));
    expect(mocks.cancel).toHaveBeenCalledOnce();
    expect(result.current.isManual).toBe(true);
    expect(result.current.isAvailable).toBe(true);
  });
});
