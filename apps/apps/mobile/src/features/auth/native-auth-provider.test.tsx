// @vitest-environment jsdom
import { act, fireEvent, render, waitFor } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AccountViewModel, NativeSessionTokens } from '@allies/cloud-client';

import { deliverNativeAuthReturn } from './native-auth-return';
import { NativeSessionProvider, useNativeSession } from '../../lib/session/session-context';
import type { NativeSessionClient } from '../../lib/session/native-session-adapter';
import type { NativeSessionStore } from '../../lib/session/secure-session-store';

const mocks = vi.hoisted(() => ({
  dismissBrowser: vi.fn(),
  openAuthSessionAsync: vi.fn(() => new Promise<never>(() => undefined)),
}));

vi.mock('expo-linking', () => ({ openURL: vi.fn(async () => true) }));
vi.mock('expo-web-browser', () => ({
  dismissBrowser: mocks.dismissBrowser,
  openAuthSessionAsync: mocks.openAuthSessionAsync,
}));
vi.mock('./pkce-attempt', () => ({
  createPkceAttempt: vi.fn(async () => ({
    codeChallenge: 'challenge-example',
    codeVerifier: 'verifier-example',
    state: 'state-example',
  })),
}));

const account: AccountViewModel = {
  userId: 'usr-auth',
  displayName: 'Auth User',
  avatarUrl: null,
  session: { id: 'ses-auth', expiresAt: '2026-09-05T12:00:00Z' },
  workspace: { id: 'wsp-auth', name: 'Auth Workspace', role: 'owner', capabilities: [] },
};
const tokens: NativeSessionTokens = {
  tokenType: 'Bearer',
  accessToken: 'access-auth',
  expiresIn: 600,
  refreshToken: 'refresh-auth',
  refreshExpiresIn: 1209600,
  sessionId: 'ses-auth',
};

function createClient(): NativeSessionClient {
  return {
    beginGoogleSignIn: vi.fn(async () => ({
      authorizationUrl: 'https://accounts.google.com/auth',
      expiresAt: new Date(Date.now() + 300_000).toISOString(),
    })),
    exchangeGoogleCode: vi.fn(async () => tokens),
    getCurrentAccount: vi.fn(async () => account),
    logout: vi.fn(async () => undefined),
    refreshSession: vi.fn(async () => tokens),
    setAccessToken: vi.fn(),
  };
}

function createStore(): NativeSessionStore {
  return {
    clear: vi.fn(async () => undefined),
    readRefresh: vi.fn(async () => null),
    writeRefresh: vi.fn(async () => undefined),
  };
}

function SignInRoute({ onStarted }: { onStarted: (promise: Promise<unknown>) => void }) {
  const session = useNativeSession();
  return (
    <button onClick={() => onStarted(session.startGoogleSignIn('/allies/new/complete'))}>
      start
    </button>
  );
}

describe('provider-owned native auth lifetime', () => {
  afterEach(() => {
    mocks.dismissBrowser.mockClear();
    mocks.openAuthSessionAsync.mockClear();
  });

  it('keeps the in-memory PKCE flow alive when the sign-in route unmounts', async () => {
    const client = createClient();
    const store = createStore();
    let started: Promise<unknown> | undefined;
    const hideRoute = vi.fn();
    function Host() {
      const [showRoute, setShowRoute] = useState(true);
      useEffect(() => {
        hideRoute.mockImplementation(() => setShowRoute(false));
        return () => {
          hideRoute.mockReset();
        };
      }, []);
      return (
        <NativeSessionProvider
          client={client}
          nativeAuthRedirectUri="https://mobile.example/auth/return"
          store={store}
        >
          {showRoute ? <SignInRoute onStarted={(promise) => { started = promise; }} /> : null}
        </NativeSessionProvider>
      );
    }

    const view = render(<Host />);
    fireEvent.click(view.getByRole('button', { name: 'start' }));
    await waitFor(() => expect(started).toBeTruthy());
    await waitFor(() => expect(mocks.openAuthSessionAsync).toHaveBeenCalledOnce());
    act(() => hideRoute());

    await act(async () => {
      expect(deliverNativeAuthReturn('https://mobile.example/auth/return?code=code&state=state-example')).toBe(true);
      await expect(started).resolves.toEqual({ status: 'signed-in' });
    });

    expect(client.exchangeGoogleCode).toHaveBeenCalledOnce();
    expect(mocks.dismissBrowser).toHaveBeenCalledOnce();
    view.unmount();
  });

  it('cancels the flow when the provider itself tears down', async () => {
    const client = createClient();
    const store = createStore();
    let started: Promise<unknown> | undefined;
    const view = render(
      <NativeSessionProvider
        client={client}
        nativeAuthRedirectUri="https://mobile.example/auth/return"
        store={store}
      >
        <SignInRoute onStarted={(promise) => { started = promise; }} />
      </NativeSessionProvider>,
    );

    fireEvent.click(view.getByRole('button', { name: 'start' }));
    await waitFor(() => expect(mocks.openAuthSessionAsync).toHaveBeenCalledOnce());
    view.unmount();

    await expect(started).resolves.toEqual({ status: 'canceled' });
    expect(mocks.dismissBrowser).toHaveBeenCalledOnce();
  });
});
