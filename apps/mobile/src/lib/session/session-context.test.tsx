// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { AccountViewModel, NativeSessionTokens } from '@allies/cloud-client';

import { NativeSessionProvider, useNativeSession } from './session-context';
import type { NativeSessionClient } from './native-session-adapter';
import type { NativeSessionStore } from './secure-session-store';

function SessionProbe() {
  const session = useNativeSession();
  return <span>{`${session.status}:${session.reason}`}</span>;
}

describe('NativeSessionProvider', () => {
  it('makes the missing native contract explicit', () => {
    render(
      <NativeSessionProvider>
        <SessionProbe />
      </NativeSessionProvider>,
    );

    expect(screen.getByText('unavailable:native-session-contract-pending')).toBeTruthy();
  });

  it('restores a configured session and exposes the validated account', async () => {
    const account: AccountViewModel = {
      userId: 'usr_example',
      displayName: 'Example User',
      avatarUrl: null,
      session: { id: 'ses_example', expiresAt: '2026-08-21T12:00:00Z' },
      workspace: { id: 'wsp_example', name: 'Personal Workspace', role: 'owner', capabilities: [] },
    };
    const tokens: NativeSessionTokens = {
      tokenType: 'Bearer',
      accessToken: 'access-example',
      expiresIn: 600,
      refreshToken: 'refresh-next',
      refreshExpiresIn: 1209600,
      sessionId: 'ses_example',
    };
    const client: NativeSessionClient = {
      beginGoogleSignIn: vi.fn(),
      exchangeGoogleCode: vi.fn(),
      refreshSession: vi.fn(async () => tokens),
      logout: vi.fn(),
      setAccessToken: vi.fn(),
      getCurrentAccount: vi.fn(async () => account),
    };
    const store: NativeSessionStore = {
      readRefresh: vi.fn(async () => 'refresh-old'),
      writeRefresh: vi.fn(async () => undefined),
      clear: vi.fn(async () => undefined),
    };

    function AccountProbe() {
      const session = useNativeSession();
      return <span>{session.account?.displayName ?? session.status}</span>;
    }

    render(
      <NativeSessionProvider client={client} store={store}>
        <AccountProbe />
      </NativeSessionProvider>,
    );

    await waitFor(() => expect(screen.getByText('Example User')).toBeTruthy());
    expect(client.getCurrentAccount).toHaveBeenCalledOnce();
  });

  it('publishes cancellation and lets a retry win over the canceled completion', async () => {
    let resolveOldExchange: ((tokens: NativeSessionTokens) => void) | undefined;
    const oldExchange = new Promise<NativeSessionTokens>((resolve) => {
      resolveOldExchange = resolve;
    });
    const tokens: NativeSessionTokens = {
      tokenType: 'Bearer',
      accessToken: 'access-retry',
      expiresIn: 600,
      refreshToken: 'refresh-retry',
      refreshExpiresIn: 1209600,
      sessionId: 'ses-retry',
    };
    const account: AccountViewModel = {
      userId: 'usr_retry',
      displayName: 'Retry User',
      avatarUrl: null,
      session: { id: 'ses-retry', expiresAt: '2026-08-21T12:00:00Z' },
      workspace: { id: 'wsp_retry', name: 'Retry Workspace', role: 'owner', capabilities: [] },
    };
    const client: NativeSessionClient = {
      beginGoogleSignIn: vi.fn(),
      exchangeGoogleCode: vi.fn(async (input) => input.code === 'old' ? oldExchange : tokens),
      refreshSession: vi.fn(),
      logout: vi.fn(),
      setAccessToken: vi.fn(),
      getCurrentAccount: vi.fn(async () => account),
    };
    const store: NativeSessionStore = {
      readRefresh: vi.fn(async () => null),
      writeRefresh: vi.fn(async () => undefined),
      clear: vi.fn(async () => undefined),
    };

    function ActionProbe() {
      const session = useNativeSession();
      return (
        <>
          <span data-testid="session-state">{`${session.status}:${session.reason}`}</span>
          <button onClick={() => void session.completeSignIn({ code: 'old', codeVerifier: 'verifier-old', redirectUri: 'https://mobile.example/auth/return' })}>
            start
          </button>
          <button onClick={() => void session.cancelSignIn()}>cancel</button>
          <button onClick={() => void session.completeSignIn({ code: 'new', codeVerifier: 'verifier-new', redirectUri: 'https://mobile.example/auth/return' })}>
            retry
          </button>
        </>
      );
    }

    render(
      <NativeSessionProvider client={client} store={store}>
        <ActionProbe />
      </NativeSessionProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('session-state').textContent).toBe('signed-out:missing-refresh'));
    fireEvent.click(screen.getByRole('button', { name: 'start' }));
    await waitFor(() => expect(screen.getByTestId('session-state').textContent).toBe('refreshing:undefined'));
    fireEvent.click(screen.getByRole('button', { name: 'cancel' }));
    await waitFor(() => expect(screen.getByTestId('session-state').textContent).toBe('signed-out:canceled'));
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    await waitFor(() => expect(screen.getByTestId('session-state').textContent).toBe('signed-in:undefined'));

    resolveOldExchange?.(tokens);
    await Promise.resolve();
    expect(screen.getByTestId('session-state').textContent).toBe('signed-in:undefined');
  });
});
