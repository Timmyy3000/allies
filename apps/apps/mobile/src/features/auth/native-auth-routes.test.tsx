// @vitest-environment jsdom
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ReturnRoute from '../../app/auth/return';
import CallbackRoute from '../../app/auth/callback';
import {
  deliverNativeAuthReturn,
  registerNativeAuthReturnListener,
} from './native-auth-return';

const mocks = vi.hoisted(() => ({
  router: { replace: vi.fn() },
  session: {
    clearGoogleSignInReturnTo: vi.fn(),
    googleSignInOutcome: null,
    googleSignInReturnTo: '/allies/new/complete',
    googleSignInStatus: 'waiting-for-return',
    status: 'signed-out',
  },
  url: null as string | null,
}));

vi.mock('expo-linking', () => ({ useURL: () => mocks.url }));
vi.mock('expo-router', () => ({ useRouter: () => mocks.router }));
vi.mock('@/hooks/use-theme', () => ({
  useTheme: () => ({ appBackground: '#fff', primaryText: '#111', supportingText: '#666' }),
}));
vi.mock('@/lib/session/session-context', () => ({ useNativeSession: () => mocks.session }));
vi.mock('@/components/ui/primary-button', async () => {
  const React = await import('react');
  return {
    PrimaryButton: ({ label, onPress }: { label: string; onPress: () => void }) => (
      React.createElement('button', { onClick: onPress }, label)
    ),
  };
});
vi.mock('react-native-safe-area-context', async () => {
  const React = await import('react');
  return { SafeAreaView: ({ children }: { children: import('react').ReactNode }) => React.createElement('div', null, children) };
});
vi.mock('react-native', async () => {
  const React = await import('react');
  const Primitive = ({ children, ...props }: { children?: import('react').ReactNode; [key: string]: unknown }) => (
    React.createElement('div', props, children)
  );
  return {
    StyleSheet: { create: <T,>(styles: T) => styles },
    Text: Primitive,
    View: Primitive,
  };
});

describe('native auth callback routes', () => {
  beforeEach(() => {
    mocks.router.replace.mockReset();
    mocks.session.clearGoogleSignInReturnTo.mockReset();
    mocks.session.googleSignInOutcome = null;
    mocks.session.googleSignInReturnTo = '/allies/new/complete';
    mocks.session.googleSignInStatus = 'waiting-for-return';
    mocks.session.status = 'signed-out';
    mocks.url = null;
  });

  it('mounts the callback alias and delivers the app link to the active flow', async () => {
    const listener = vi.fn();
    const dispose = registerNativeAuthReturnListener(listener);
    mocks.url = 'https://mobile.example/auth/callback?code=code&state=state';

    const view = render(<CallbackRoute />);
    await waitFor(() => expect(listener).toHaveBeenCalledWith(mocks.url));

    expect(deliverNativeAuthReturn(mocks.url)).toBe(true);
    view.unmount();
    dispose();
  });

  it.each([
    ['return', ReturnRoute],
    ['callback', CallbackRoute],
  ] as const)('mounts the %s alias and resumes the provider return target', async (_name, Route) => {
    mocks.session.status = 'signed-in';
    mocks.session.googleSignInStatus = 'idle';

    const view = render(<Route />);
    await waitFor(() => expect(mocks.router.replace).toHaveBeenCalledWith('/allies/new/complete'));

    expect(mocks.session.clearGoogleSignInReturnTo).toHaveBeenCalledOnce();
    view.unmount();
  });
});
