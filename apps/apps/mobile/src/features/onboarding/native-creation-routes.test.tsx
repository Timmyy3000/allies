// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import CompleteRoute from '../../app/allies/new/complete';
import PostSetupRoute from '../../app/allies/new/post-setup';

const mocks = vi.hoisted(() => {
  const account = {
    userId: 'usr-create',
    workspace: { id: 'wsp-create' },
  };
  const ally = { id: 'ally-created', name: 'Moss', appearance: { key: 'round:abcdef' } };
  const command = {
    kind: 'create' as const,
    name: 'Moss',
    job: 'Keep plans clear',
    personality: 'Warm',
    appearance: { catalogVersion: 'v1', key: 'round:abcdef' },
    onboardingAttempt: 'attempt-1',
    reply: 'Create Moss',
    idempotencyKey: '00000000-0000-4000-8000-000000000001',
    createdAt: '2026-09-05T10:00:00.000Z',
    expiresAt: '2026-09-12T10:00:00.000Z',
  };
  const accountClient = { createAlly: vi.fn(async () => ally) };
  const adapter = { withRefresh: vi.fn((operation: () => Promise<unknown>) => operation()) };
  return {
    account,
    accountClient,
    adapter,
    ally,
    command,
    pendingCommandStore: {
      bindCreate: vi.fn(async () => command),
      deleteCreate: vi.fn(async () => undefined),
    },
    queryClient: {
      invalidateQueries: vi.fn(async () => undefined),
      setQueryData: vi.fn(),
    },
    router: { replace: vi.fn() },
    allyId: undefined as string | undefined,
    allyQuery: {
      data: undefined,
      isError: false,
      isPending: false,
      refetch: vi.fn(async () => undefined),
    },
    session: {
      account,
      accountClient,
      adapter,
      status: 'signed-in',
    },
  };
});

vi.mock('expo-router', () => ({
  useLocalSearchParams: () => ({ allyId: mocks.allyId }),
  useRouter: () => mocks.router,
}));
vi.mock('@tanstack/react-query', () => ({ useQueryClient: () => mocks.queryClient }));
vi.mock('@/features/allies/queries', () => ({
  allyKeys: {
    all: (workspaceId: string) => ['allies', workspaceId],
    detail: (workspaceId: string, allyId: string) => ['allies', workspaceId, allyId],
  },
  useAlly: () => mocks.allyQuery,
}));
vi.mock('@/lib/pending-command-store', () => ({
  pendingCommandStore: mocks.pendingCommandStore,
  toCloudCreateAllyInput: (command: typeof mocks.command) => ({
    name: command.name,
    job: command.job,
    personality: command.personality,
    appearanceCatalogVersion: command.appearance.catalogVersion,
    appearanceKey: command.appearance.key,
    onboardingAttempt: command.onboardingAttempt,
    reply: command.reply,
  }),
}));
vi.mock('@/lib/session/session-context', () => ({ useNativeSession: () => mocks.session }));
vi.mock('@/features/onboarding/allies-logo', async () => {
  const React = await import('react');
  return { AlliesLogo: () => React.createElement('div') };
});
vi.mock('@/features/onboarding/onboarding-ally-preview', async () => {
  const React = await import('react');
  return { OnboardingAllyPreview: () => React.createElement('div') };
});
vi.mock('@/features/onboarding/onboarding-post-setup', async () => {
  const React = await import('react');
  return {
    OnboardingBasicsScreen: ({ onComplete }: { onComplete: () => void }) => (
      React.createElement('button', { onClick: onComplete }, 'Complete basics')
    ),
    OnboardingNotificationsScreen: ({ onSkip }: { onSkip: () => void }) => (
      React.createElement('button', { onClick: onSkip }, 'Skip notifications')
    ),
  };
});
vi.mock('@/features/allies/ally-appearance', () => ({
  getAllyAppearance: () => ({ color: '#abcdef', shape: 'round' }),
}));
vi.mock('@/lib/notifications/notification-permission', () => ({
  requestNotificationPermission: vi.fn(async () => undefined),
}));
vi.mock('@/hooks/use-theme', () => ({
  useTheme: () => ({ appBackground: '#fff', primaryText: '#111', supportingText: '#666' }),
}));
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
    ActivityIndicator: Primitive,
    Pressable: ({ accessibilityRole: _accessibilityRole, children, onPress, ...props }: { accessibilityRole?: string; children?: import('react').ReactNode; onPress?: () => void; [key: string]: unknown }) => (
      React.createElement('button', { ...props, onClick: onPress }, children)
    ),
    StyleSheet: { create: (styles: unknown) => styles },
    Text: Primitive,
    View: Primitive,
  };
});

describe('mounted native creation route', () => {
  beforeEach(() => {
    mocks.accountClient.createAlly.mockReset();
    mocks.accountClient.createAlly.mockImplementation(async () => mocks.ally);
    mocks.adapter.withRefresh.mockClear();
    mocks.pendingCommandStore.bindCreate.mockReset();
    mocks.pendingCommandStore.bindCreate.mockImplementation(async () => mocks.command);
    mocks.pendingCommandStore.deleteCreate.mockReset();
    mocks.pendingCommandStore.deleteCreate.mockImplementation(async () => undefined);
    mocks.queryClient.invalidateQueries.mockReset();
    mocks.queryClient.invalidateQueries.mockImplementation(async () => undefined);
    mocks.queryClient.setQueryData.mockReset();
    mocks.router.replace.mockReset();
    mocks.session.account = mocks.account;
    mocks.session.status = 'signed-in';
    mocks.allyId = undefined;
    mocks.allyQuery.data = undefined;
    mocks.allyQuery.isError = false;
    mocks.allyQuery.isPending = false;
    mocks.allyQuery.refetch.mockReset();
    mocks.allyQuery.refetch.mockImplementation(async () => undefined);
  });

  it('creates through the shared account client and invalidates the workspace roster', async () => {
    const view = render(<CompleteRoute />);

    await waitFor(() => expect(mocks.router.replace).toHaveBeenCalledWith(
      '/allies/new/post-setup?allyId=ally-created',
    ));
    expect(mocks.accountClient.createAlly).toHaveBeenCalledWith(
      'wsp-create',
      expect.objectContaining({ name: 'Moss', reply: 'Create Moss' }),
      mocks.command.idempotencyKey,
      expect.any(AbortSignal),
    );
    expect(mocks.queryClient.setQueryData).toHaveBeenCalledWith(
      ['allies', 'wsp-create', 'ally-created'],
      mocks.ally,
    );
    expect(mocks.queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['allies', 'wsp-create'] });
    view.unmount();
  });

  it('turns pending storage failure into an actionable mounted state', async () => {
    mocks.pendingCommandStore.bindCreate.mockRejectedValue(new Error('secure store unavailable'));

    const view = render(<CompleteRoute />);

    expect(await screen.findByText('We could not finish creating your Ally. Try again.')).toBeTruthy();
    expect(mocks.accountClient.createAlly).not.toHaveBeenCalled();
    expect(mocks.router.replace).not.toHaveBeenCalled();
    view.unmount();
  });

  it('ignores a late create result after the signed-in identity changes', async () => {
    let resolveCreate: ((ally: typeof mocks.ally) => void) | undefined;
    mocks.accountClient.createAlly.mockImplementation(() => new Promise((resolve) => {
      resolveCreate = resolve;
    }));
    const view = render(<CompleteRoute />);
    await waitFor(() => expect(mocks.accountClient.createAlly).toHaveBeenCalledOnce());

    mocks.session.account = { userId: 'usr-other', workspace: { id: 'wsp-other' } };
    view.rerender(<CompleteRoute />);
    resolveCreate?.(mocks.ally);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mocks.router.replace).not.toHaveBeenCalled();
    expect(mocks.queryClient.setQueryData).not.toHaveBeenCalled();
    view.unmount();
  });

  it('renders actionable post-setup states for missing IDs and query errors', async () => {
    const view = render(<PostSetupRoute />);

    expect(await screen.findByText('We could not find the Ally you just created.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Open Allies' }));
    expect(mocks.router.replace).toHaveBeenCalledWith('/allies');

    mocks.router.replace.mockReset();
    mocks.allyId = 'ally-created';
    mocks.allyQuery.isError = true;
    view.rerender(<PostSetupRoute />);
    expect(await screen.findByText('We could not load your new Ally yet.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(mocks.allyQuery.refetch).toHaveBeenCalledOnce();
  });
});
