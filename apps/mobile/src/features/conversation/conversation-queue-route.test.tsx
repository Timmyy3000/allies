// @vitest-environment jsdom

import Module from 'node:module';
import { createElement, type ReactNode } from 'react';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MessageViewModel, ConversationViewModel } from '@allies/cloud-client';
import type { PendingMessageCommand } from '@/lib/pending-command-store';
import AllyConversationScreen from '@/app/allies/[allyId]/index';

const harness = vi.hoisted(() => ({
  session: null as unknown,
  pending: {
    readMessage: vi.fn<() => Promise<PendingMessageCommand | null>>(async () => null),
    saveMessage: vi.fn(async () => undefined),
    deleteMessage: vi.fn(async () => undefined),
  },
  appState: { currentState: 'active', addEventListener: () => ({ remove: () => undefined }) },
}));

type NativeProps = {
  children?: ReactNode; accessibilityLabel?: string; accessibilityRole?: string;
  onPress?: () => void; onChangeText?: (text: string) => void;
  value?: string; editable?: boolean; disabled?: boolean;
};
function primitive(tag: string) {
  return function Primitive(props: NativeProps) {
    return createElement(tag, {
      'aria-label': props.accessibilityLabel, role: props.accessibilityRole,
      onClick: props.onPress, value: props.value,
      disabled: props.disabled || props.editable === false,
      onChange: props.onChangeText ? (event: { target: { value: string } }) => props.onChangeText!(event.target.value) : undefined,
    }, props.children);
  };
}
vi.mock('react-native', () => ({
  ActivityIndicator: primitive('span'), AppState: harness.appState,
  KeyboardAvoidingView: primitive('div'), Platform: { OS: 'ios' },
  Pressable: primitive('button'), ScrollView: primitive('div'), Text: primitive('span'),
  TextInput: primitive('textarea'), View: primitive('div'), StyleSheet: { create: (styles: unknown) => styles },
}));
vi.mock('react-native-safe-area-context', () => ({
  SafeAreaView: primitive('div'), useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
vi.mock('expo-image', () => ({ Image: () => null }));
vi.mock('expo-status-bar', () => ({ StatusBar: () => null }));
vi.mock('expo-crypto', () => ({ randomUUID: () => '00000000-0000-4000-8000-000000000099' }));
vi.mock('expo-router', () => ({
  useIsFocused: () => true,
  useLocalSearchParams: () => ({ allyId: 'ally' }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock('@/features/onboarding/onboarding-ally-preview', () => ({ OnboardingAllyPreview: () => null }));
vi.mock('@/features/allies/ally-session-index', () => ({ useAllySessionIndex: () => ({ addReachableAllyId: vi.fn() }) }));
vi.mock('@/features/allies/ally-appearance', () => ({ getAllyAppearance: () => ({ color: '#eee', shape: 'orb' }) }));
vi.mock('@/features/mock/mock-app', () => ({ useMockApp: () => ({ isMock: false }) }));
vi.mock('@/features/mock/mock-screens', () => ({ MockConversationScreen: () => null }));
vi.mock('@/lib/session/session-context', () => ({ useNativeSession: () => harness.session }));
vi.mock('@/lib/pending-command-store', () => ({ pendingCommandStore: harness.pending }));

const head: MessageViewModel = {
  id: 'head', sequence: 2, sender: 'user', content: 'First task',
  status: 'queued', queueState: 'claimed', createdAt: '2026-09-06T12:00:00Z',
};
const tail: MessageViewModel = { ...head, id: 'tail', sequence: 3, content: 'Later task', queueState: 'unclaimed' };
const originalRequire = Module.prototype.require;

beforeEach(() => {
  vi.spyOn(Module.prototype, 'require').mockImplementation(function (this: Module, id: string) {
    if (id === '@/assets/allies/icons/send.svg') return 1;
    return originalRequire.call(this, id);
  });
  harness.pending.readMessage.mockResolvedValue(null);
  harness.pending.saveMessage.mockResolvedValue(undefined);
  harness.pending.deleteMessage.mockResolvedValue(undefined);
});
afterEach(cleanup);

function mount() {
  let conversation: ConversationViewModel = {
    id: 'conversation', allyId: 'ally', messages: [head, tail], queue: [head, tail],
    assistantReplies: [], nextCursor: null,
  };
  const client = {
    getAlly: vi.fn(async () => ({
      id: 'ally', name: 'Mira', appearance: { key: 'orb' }, provisioningState: 'bound',
    })),
    getAllyConversation: vi.fn(async () => structuredClone(conversation)),
    getActivities: vi.fn(async () => ({
      conversationId: 'conversation', activities: [], state: 'queued',
      activeMessageId: 'head', lastContiguousSequence: 0,
    })),
    sendMessage: vi.fn(async () => {
      const next: MessageViewModel = { ...tail, id: 'third', sequence: 4, content: 'Another task' };
      conversation = { ...conversation, messages: [...conversation.messages, next], queue: [...conversation.queue!, next] };
      return { conversationId: 'conversation', message: next, replayed: false, execution: null };
    }),
    deleteQueuedMessage: vi.fn(async () => {
      const deleted: MessageViewModel = { ...tail, content: '', status: 'stopped', deletedAt: '2026-09-06T12:01:00Z', queueState: null };
      conversation = { ...conversation, messages: [head, deleted], queue: [head] };
      return deleted;
    }),
  };
  harness.session = {
    status: 'signed-in', account: { userId: 'user', workspace: { id: 'workspace' } },
    accountClient: client, adapter: { withRefresh: (operation: () => Promise<unknown>) => operation() },
  };
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(createElement(QueryClientProvider, { client: queryClient }, createElement(AllyConversationScreen)));
  return { ...view, client, queryClient, replaceQueue: (queue: MessageViewModel[]) => {
    conversation = { ...conversation, messages: queue, queue };
  } };
}

describe('native durable message queue route', () => {
  it('restores the encrypted unknown command after reopening and reuses its identity', async () => {
    harness.pending.readMessage.mockResolvedValueOnce({
      kind: 'message', conversationId: 'conversation', content: 'Another task',
      idempotencyKey: 'saved-key', createdAt: '2026-09-06T12:00:00Z',
      boundUserId: 'user', boundWorkspaceId: 'workspace',
    });
    const view = mount();
    fireEvent.click(await view.findByLabelText('Retry message'));
    await waitFor(() => expect(view.client.sendMessage).toHaveBeenCalledWith(
      'workspace', 'conversation', 'Another task', 'saved-key', expect.any(AbortSignal),
    ));
    expect(harness.pending.saveMessage).not.toHaveBeenCalled();
    view.unmount();
    view.queryClient.clear();
  });

  it('does not overwrite unknown saved work when encrypted storage cannot be read', async () => {
    harness.pending.readMessage.mockRejectedValueOnce(new Error('Storage unavailable'));
    const view = mount();
    await view.findByText('We could not read your saved message. Reopen this conversation to retry.');
    fireEvent.change(view.getByLabelText('Message your Ally'), { target: { value: 'Another task' } });
    fireEvent.click(view.getByLabelText('Send message'));
    expect(view.client.sendMessage).not.toHaveBeenCalled();
    expect(harness.pending.saveMessage).not.toHaveBeenCalled();
    view.unmount();
    view.queryClient.clear();
  });

  it('submits another durable message while the claimed head wakes and only permits tail removal', async () => {
    const view = mount();
    await view.findByLabelText('Queued messages');
    expect(view.queryByLabelText('Remove queued message: First task')).toBeNull();
    expect(view.getByLabelText('Remove queued message: Later task')).toBeTruthy();
    await waitFor(() => expect(harness.pending.readMessage).toHaveBeenCalled());
    fireEvent.change(view.getByLabelText('Message your Ally'), { target: { value: 'Another task' } });
    fireEvent.click(view.getByLabelText('Send message'));
    await waitFor(() => expect(view.client.sendMessage).toHaveBeenCalledTimes(1));
    expect(harness.pending.saveMessage).toHaveBeenCalledWith(expect.objectContaining({ content: 'Another task' }));
    await view.findByText('Another task');
    expect(view.client.sendMessage.mock.calls[0]).toEqual([
      'workspace', 'conversation', 'Another task', '00000000-0000-4000-8000-000000000099', expect.any(AbortSignal),
    ]);
    view.queryClient.clear();
  });

  it('applies a Cloud tombstone and reconciles another device queue change on refresh', async () => {
    const view = mount();
    fireEvent.click(await view.findByLabelText('Remove queued message: Later task'));
    await waitFor(() => expect(view.queryByText('Later task')).toBeNull());
    expect(view.client.deleteQueuedMessage).toHaveBeenCalledWith('workspace', 'conversation', 'tail', expect.any(AbortSignal));
    view.replaceQueue([head, { ...tail, id: 'remote', content: 'From web' }]);
    fireEvent.click(view.getByText('Refresh'));
    await view.findByText('From web');
    view.queryClient.clear();
  });

  it('keeps a send receipt when a pre-send refresh arrives late', async () => {
    const view = mount();
    await view.findByLabelText('Queued messages');
    await waitFor(() => expect(view.client.getAllyConversation.mock.calls.length).toBeGreaterThan(1));
    let resolveRead!: (value: ConversationViewModel) => void;
    view.client.getAllyConversation.mockImplementationOnce(() => new Promise((resolve) => { resolveRead = resolve; }));
    fireEvent.click(view.getByText('Refresh'));
    await waitFor(() => expect(resolveRead).toBeDefined());
    fireEvent.change(view.getByLabelText('Message your Ally'), { target: { value: 'Another task' } });
    fireEvent.click(view.getByLabelText('Send message'));
    await view.findByText('Another task');
    await act(async () => {
      resolveRead({ id: 'conversation', allyId: 'ally', messages: [head, tail], queue: [head, tail], assistantReplies: [], nextCursor: null });
    });
    expect(view.getByText('Another task')).toBeTruthy();
    expect(view.getByLabelText('Remove queued message: Another task')).toBeTruthy();
    view.unmount();
    view.queryClient.clear();
  });

  it('retains an ambiguous send with the same key for retry and preserves a failed delete', async () => {
    const view = mount();
    await view.findByLabelText('Queued messages');
    view.client.deleteQueuedMessage.mockRejectedValueOnce({ kind: 'conflict' });
    fireEvent.click(view.getByLabelText('Remove queued message: Later task'));
    await view.findByText('We could not confirm removal. The message may have started; refresh or try again.');
    expect(view.getByText('Later task')).toBeTruthy();
    view.client.sendMessage.mockRejectedValueOnce({ kind: 'timeout' });
    fireEvent.change(view.getByLabelText('Message your Ally'), { target: { value: 'Another task' } });
    fireEvent.click(view.getByLabelText('Send message'));
    await view.findByText('We could not confirm your message. Retry the saved message.');
    fireEvent.click(view.getByLabelText('Retry message'));
    await waitFor(() => expect(view.client.sendMessage).toHaveBeenCalledTimes(2));
    expect(view.client.sendMessage.mock.calls[0].slice(0, 4)).toEqual(view.client.sendMessage.mock.calls[1].slice(0, 4));
    await act(async () => { await Promise.resolve(); });
    view.queryClient.clear();
  });
});
