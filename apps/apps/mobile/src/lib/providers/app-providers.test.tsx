// @vitest-environment jsdom

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { version as reactVersion } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useNativeSession } from '../session/session-context';
import { AppProviders } from './app-providers';
import { useGoogleSignIn } from '../../features/auth/use-google-sign-in';

const appStateMock = vi.hoisted(() => ({
  currentState: 'active' as const,
  addEventListener: vi.fn(() => ({ remove: vi.fn() })),
}));

vi.mock('react-native', () => ({ AppState: appStateMock }));
vi.mock('expo-linking', () => ({ openURL: vi.fn(async () => true) }));
vi.mock('expo-web-browser', () => ({ dismissBrowser: vi.fn(), openAuthSessionAsync: vi.fn() }));
vi.mock('expo-router', async () => {
  const { useEffect } = await import('react');
  return { useFocusEffect: (effect: () => (() => void) | undefined) => useEffect(effect, [effect]) };
});
vi.mock('../../features/auth/pkce-attempt', () => ({ createPkceAttempt: vi.fn(async () => ({ codeVerifier: 'v'.repeat(43), codeChallenge: 'a'.repeat(43), state: 'state' })) }));

vi.mock('expo-secure-store', () => ({
  getItemAsync: vi.fn(async () => null),
  setItemAsync: vi.fn(async () => undefined),
  deleteItemAsync: vi.fn(async () => undefined),
}));

function SessionProbe() {
  const session = useNativeSession();
  return <span>{`${session.status}:${session.reason}`}</span>;
}

describe('AppProviders', () => {
  afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

  it('keeps a manual sign-in attempt alive across root re-renders', async () => {
    vi.stubEnv('EXPO_PUBLIC_CLOUD_API_URL', 'https://cloud.example.com');
    vi.stubEnv('EXPO_PUBLIC_NATIVE_AUTH_REDIRECT_URI', 'https://mobile.example/auth/return');
    vi.stubEnv('EXPO_PUBLIC_NATIVE_AUTH_COMPLETION_MODE', 'manual_code');
    const fetch = vi.fn(async () => Response.json({ status: 'success', message: 'Started', data: {
      authorization_url: 'https://accounts.google.com/auth', expires_at: new Date(Date.now() + 300_000).toISOString(),
    } }));
    vi.stubGlobal('fetch', fetch);
    function ManualProbe() {
      const signIn = useGoogleSignIn();
      return <>
        <span data-testid="manual-status">{signIn.status}</span>
        <button disabled={!signIn.isAvailable} onClick={() => void signIn.start()}>start manual</button>
        <button onClick={() => void signIn.cancel()}>cancel manual</button>
      </>;
    }
    const { rerender, unmount } = render(<AppProviders><ManualProbe /></AppProviders>);
    await waitFor(() => expect((screen.getByRole('button', { name: 'start manual' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'start manual' }));
    await waitFor(() => expect(screen.getByTestId('manual-status').textContent).toBe('waiting-for-code'));
    await act(async () => { rerender(<AppProviders><ManualProbe /></AppProviders>); });
    expect(screen.getByTestId('manual-status').textContent).toBe('waiting-for-code');
    expect(fetch).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole('button', { name: 'cancel manual' }));
    await waitFor(() => expect(screen.getByTestId('manual-status').textContent).toBe('idle'));
    unmount();
  });

  it('uses the React version pinned by the mobile app', () => {
    expect(reactVersion).toBe('19.2.3');
  });

  it('composes the mobile Query and unavailable native-session boundaries', () => {
    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    expect(screen.getByText('unavailable:native-session-contract-pending')).toBeTruthy();
  });

  it('initializes the configured Cloud-backed mobile session', async () => {
    vi.stubEnv('EXPO_PUBLIC_CLOUD_API_URL', 'https://cloud.example.com');
    vi.stubEnv('EXPO_PUBLIC_NATIVE_AUTH_REDIRECT_URI', 'https://mobile.example/auth/return');

    render(
      <AppProviders>
        <SessionProbe />
      </AppProviders>,
    );

    await waitFor(() => expect(screen.getByText('signed-out:missing-refresh')).toBeTruthy());
  });
});
