// @vitest-environment jsdom

import { act, fireEvent, render } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import AllyConversationRoute from '@/app/allies/[allyId]/index';
import { createMobileCloudClient } from '@/lib/cloud/native-cloud-client';
import { createQueryClient } from '@/lib/query/create-query-client';
import { NativeLifecycleBridge } from '@/lib/providers/native-lifecycle';

const ids = {
  ally: '00000000-0000-4000-8000-000000000002',
  assistantMessage: '00000000-0000-4000-8000-000000000006',
  conversation: '00000000-0000-4000-8000-000000000005',
  user: '00000000-0000-4000-8000-000000000007',
  workspace: '00000000-0000-4000-8000-000000000001',
} as const;

const harness = vi.hoisted(() => {
  type AppStateValue = 'active' | 'background' | 'inactive';
  let appState: AppStateValue = 'active';
  const listeners = new Set<(nextState: AppStateValue) => void>();
  const session = { value: null as unknown };
  const pendingStore = {
    deleteMessage: vi.fn(async () => undefined),
    readMessage: vi.fn(async () => null),
    saveMessage: vi.fn(async () => undefined),
  };
  const router = { replace: vi.fn(), push: vi.fn() };

  return {
    appState: {
      get currentState() {
        return appState;
      },
      addEventListener: (_event: 'change', listener: (nextState: AppStateValue) => void) => {
        listeners.add(listener);
        return { remove: () => listeners.delete(listener) };
      },
    },
    setAppState(nextState: AppStateValue) {
      appState = nextState;
      for (const listener of listeners) listener(nextState);
    },
    resetAppState() {
      appState = 'active';
      listeners.clear();
    },
    router,
    session,
    pendingStore,
    params: { allyId: '00000000-0000-4000-8000-000000000002' },
  };
});

function primitive(tag: 'div' | 'span' | 'button' | 'input') {
  const Primitive = ({ children, accessibilityLabel, accessibilityRole, onPress, style, ...props }: any) => createElement(
    tag,
    {
      ...props,
      ...(accessibilityLabel ? { 'aria-label': accessibilityLabel } : {}),
      ...(accessibilityRole ? { role: accessibilityRole } : {}),
      ...(onPress ? { onClick: onPress } : {}),
      ...(style ? {} : {}),
    },
    children,
  );
  Primitive.displayName = `Mock${tag}`;
  return Primitive;
}

vi.mock('react-native', () => ({
  ActivityIndicator: primitive('span'),
  AppState: harness.appState,
  Pressable: primitive('button'),
  ScrollView: primitive('div'),
  StyleSheet: { absoluteFill: {}, create: (styles: unknown) => styles },
  Text: primitive('span'),
  View: primitive('div'),
}));
vi.mock('react-native-reanimated', () => ({
  default: { View: primitive('div') },
  LinearTransition: { duration: () => ({ easing: () => ({}) }) },
  useReducedMotion: () => false,
}));
vi.mock('react-native-safe-area-context', () => ({ SafeAreaView: primitive('div') }));
vi.mock('expo-crypto', () => ({ randomUUID: () => '00000000-0000-4000-8000-000000000009' }));
vi.mock('expo-router', () => ({
  useIsFocused: () => true,
  useLocalSearchParams: () => harness.params,
  useRouter: () => harness.router,
}));
vi.mock('@/components/ui/primary-button', () => ({
  PrimaryButton: ({ label, onPress }: { label: string; onPress: () => void }) => createElement('button', { onClick: onPress }, label),
}));
vi.mock('@/hooks/use-theme', () => ({
  useTheme: () => ({
    appBackground: '#fff',
    buttonText: '#fff',
    chatInput: '#eee',
    inactiveButton: '#aaa',
    neutralButtonSurface: '#ddd',
    neutralButtonText: '#111',
    placeholderText: '#777',
    primaryText: '#111',
    supportingText: '#666',
  }),
}));
vi.mock('@/lib/pending-command-store', () => ({
  pendingCommandStore: harness.pendingStore,
}));
vi.mock('@/lib/session/session-context', () => ({
  useNativeSession: () => harness.session.value,
}));
vi.mock('@/features/conversation/conversation-layout', () => ({
  ConversationLayout: ({ ally, canSend, children, draft, onChangeDraft, onSend }: any) => createElement(
    'section',
    null,
    createElement('input', {
      'aria-label': `Message ${ally.name}`,
      value: draft,
      onChange: (event: { currentTarget: { value: string } }) => onChangeDraft(event.currentTarget.value),
    }),
    createElement('button', { 'aria-label': 'Send message', disabled: !canSend, onClick: onSend }, 'Send'),
    children,
  ),
  ConversationMessage: ({ message }: { message: { content: string } }) => createElement('span', null, message.content),
  ConversationThinkingRow: () => null,
}));
vi.mock('@/features/onboarding/onboarding-ally-preview', () => ({ OnboardingAllyPreview: primitive('div') }));

const allyResponse = {
  id: ids.ally,
  binding_id: '00000000-0000-4000-8000-000000000003',
  operation_id: '00000000-0000-4000-8000-000000000004',
  name: 'Mira',
  job: 'Study partner',
  personality: 'Calm and specific.',
  appearance: { catalog_version: 'v1', key: 'sunrise' },
  provisioning_state: 'bound',
  retryable: false,
};

const emptyConversation = {
  id: ids.conversation,
  ally_id: ids.ally,
  messages: [],
  assistant_replies: [],
  next_cursor: null,
};

const acceptedMessage = {
  id: ids.user,
  sender: 'user',
  content: 'Help me plan tomorrow.',
  sequence: 1,
  status: 'completed',
  retryable: false,
  created_at: '2026-09-05T10:01:00Z',
};

function activityResponse() {
  return {
    status: 'success',
    message: 'Activities loaded',
    data: {
      conversation_id: ids.conversation,
      activities: [],
      state: 'completed',
      last_contiguous_sequence: 0,
      last_contiguous_activity_sequence: 0,
      oldest_sequence: null,
      latest_sequence: null,
      resume_cursor: null,
      next_cursor: null,
      retention_gap: false,
    },
  };
}

function account(userId = '00000000-0000-4000-8000-000000000010') {
  return {
    userId,
    displayName: 'Mira User',
    avatarUrl: null,
    workspace: { id: ids.workspace, name: 'Personal Workspace', role: 'owner', capabilities: [] },
  };
}

function renderRoute() {
  const queryClient = createQueryClient();
  const element = () => (
    <QueryClientProvider client={queryClient}>
      <NativeLifecycleBridge>
        <AllyConversationRoute />
      </NativeLifecycleBridge>
    </QueryClientProvider>
  );
  const rendered = render(element());
  return {
    queryClient,
    ...rendered,
    rerenderRoute: () => rendered.rerender(element()),
  };
}

const settleRoute = () => new Promise((resolve) => setTimeout(resolve, 250));

describe('mounted Ally conversation route', () => {
  afterEach(() => {
    harness.resetAppState();
    vi.clearAllMocks();
  });

  it('uses the real route/client wiring for first edit, send, and foreground history recovery', async () => {
    let foregroundReady = false;
    const requests: Request[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      requests.push(request.clone());
      const url = new URL(request.url);
      const path = url.pathname;

      if (path === `/api/v1/workspaces/${ids.workspace}/allies/${ids.ally}`) {
        return Response.json({ status: 'success', message: 'Ally loaded', data: allyResponse });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/allies/${ids.ally}/conversation`) {
        return Response.json({ status: 'success', message: 'Conversation loaded', data: emptyConversation });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}`) {
        const messages = foregroundReady
          ? [
            acceptedMessage,
            {
              id: ids.assistantMessage,
              sender: 'assistant',
              content: 'Recovered while away.',
              sequence: 2,
              status: 'completed',
              retryable: false,
              created_at: '2026-09-05T10:02:00Z',
            },
          ]
          : [acceptedMessage];
        return Response.json({ status: 'success', message: 'Conversation loaded', data: { ...emptyConversation, messages } });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}/activities`) {
        return Response.json(activityResponse());
      }
      if (path === `/api/v1/allies/${ids.ally}/runtime-intents`) {
        expect(request.headers.get('authorization')).toBe('Bearer access-example');
        expect(await request.clone().json()).toEqual({
          intent: 'composing_started',
          occurred_at: expect.any(String),
        });
        expect(request.headers.get('Idempotency-Key')).toBe('00000000-0000-4000-8000-000000000009');
        return Response.json({ status: 'success', message: 'Runtime intent accepted', data: { status: 'waking' } }, { status: 202 });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}/messages`) {
        expect(request.headers.get('authorization')).toBe('Bearer access-example');
        expect(await request.clone().json()).toMatchObject({ content: 'Help me plan tomorrow.' });
        return Response.json({
          status: 'success',
          message: 'Message accepted',
          data: { conversation_id: ids.conversation, message: acceptedMessage, execution: null, replayed: false },
        }, { status: 201 });
      }
      throw new Error(`Unexpected request: ${request.method} ${path}`);
    });
    const client = createMobileCloudClient({
      cloudApiUrl: 'https://cloud.example.com',
      nativeAuthRedirectUri: 'https://mobile.example/auth/return',
      fetch,
    });
    client.setAccessToken('access-example');
    harness.session.value = {
      account: account(),
      accountClient: client.account,
      adapter: { withRefresh: (operation: () => Promise<unknown>) => operation() },
      restore: vi.fn(async () => undefined),
      status: 'signed-in',
    };

    const { unmount } = renderRoute();
    await settleRoute();
    const input = document.querySelector('input[aria-label="Message Mira"]') as HTMLInputElement | null;
    const send = document.querySelector('button[aria-label="Send message"]') as HTMLButtonElement | null;
    expect(input).not.toBeNull();
    expect(send).not.toBeNull();

    fireEvent.change(input!, { target: { value: 'hello' } });
    await settleRoute();
    expect(requests.filter((request) => request.url.endsWith('/runtime-intents'))).toHaveLength(1);
    expect(send!.disabled).toBe(false);

    fireEvent.change(input!, { target: { value: 'Help me plan tomorrow.' } });
    fireEvent.click(send!);
    await settleRoute();
    expect(requests.filter((request) => request.url.endsWith('/runtime-intents'))).toHaveLength(1);

    foregroundReady = true;
    act(() => harness.setAppState('background'));
    await settleRoute();
    act(() => harness.setAppState('active'));
    await settleRoute();
    expect(document.body.textContent).toContain('Recovered while away.');

    const refreshedConversationReads = requests.filter((request) => new URL(request.url).pathname.endsWith(`/conversations/${ids.conversation}`));
    const replayOrTailReads = requests.filter((request) => request.url.includes(`/conversations/${ids.conversation}/activities`));
    expect(refreshedConversationReads.length).toBeGreaterThan(0);
    expect(replayOrTailReads.length).toBeGreaterThanOrEqual(3);
    expect(requests.some((request) => request.url.endsWith('/runtime-intents') && request.method === 'POST')).toBe(true);
    unmount();
  });

  it('offers a Delete in chat prefill only after a saved unsent message is retried', async () => {
    const userId = '00000000-0000-4000-8000-000000000010';
    const prefill = 'Please delete the “Morning check” routine.';
    harness.params = { allyId: ids.ally, prefill } as typeof harness.params;
    (harness.pendingStore.readMessage as unknown as { mockResolvedValue: (value: unknown) => void }).mockResolvedValue({
      kind: 'message',
      conversationId: ids.conversation,
      content: 'Help me plan tomorrow.',
      idempotencyKey: '00000000-0000-4000-8000-000000000031',
      createdAt: '2026-09-05T10:00:00Z',
      boundUserId: userId,
      boundWorkspaceId: ids.workspace,
    });
    const sent: unknown[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const path = new URL(request.url).pathname;
      if (path === `/api/v1/workspaces/${ids.workspace}/allies/${ids.ally}`) {
        return Response.json({ status: 'success', message: 'Ally loaded', data: allyResponse });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/allies/${ids.ally}/conversation`) {
        return Response.json({ status: 'success', message: 'Conversation loaded', data: emptyConversation });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}`) {
        return Response.json({ status: 'success', message: 'Conversation loaded', data: { ...emptyConversation, messages: sent.length ? [acceptedMessage] : [] } });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}/activities`) {
        return Response.json(activityResponse());
      }
      if (path === `/api/v1/allies/${ids.ally}/runtime-intents`) {
        return Response.json({ status: 'success', message: 'Runtime intent accepted', data: { status: 'waking' } }, { status: 202 });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}/messages`) {
        sent.push(await request.clone().json());
        return Response.json({
          status: 'success',
          message: 'Message accepted',
          data: { conversation_id: ids.conversation, message: acceptedMessage, execution: null, replayed: false },
        }, { status: 201 });
      }
      throw new Error(`Unexpected request: ${request.method} ${path}`);
    });
    const client = createMobileCloudClient({
      cloudApiUrl: 'https://cloud.example.com',
      nativeAuthRedirectUri: 'https://mobile.example/auth/return',
      fetch,
    });
    client.setAccessToken('access-example');
    harness.session.value = {
      account: account(userId),
      accountClient: client.account,
      adapter: { withRefresh: (operation: () => Promise<unknown>) => operation() },
      restore: vi.fn(async () => undefined),
      status: 'signed-in',
    };

    const { unmount } = renderRoute();
    await settleRoute();
    const input = document.querySelector('input[aria-label="Message Mira"]') as HTMLInputElement;
    expect(input.value).toBe('Help me plan tomorrow.');

    fireEvent.click(document.querySelector('button[aria-label="Send message"]')!);
    await settleRoute();
    expect(sent).toEqual([expect.objectContaining({ content: 'Help me plan tomorrow.' })]);
    expect(input.value).toBe(prefill);
    unmount();
    harness.params = { allyId: ids.ally };
    (harness.pendingStore.readMessage as unknown as { mockResolvedValue: (value: unknown) => void }).mockResolvedValue(null);
  });

  it('leaves a late send acceptance pending when the account identity changes', async () => {
    let resolveSend: ((response: Response) => void) | null = null;
    let sendRequest: Request | null = null;
    const delayedSend = new Promise<Response>((resolve) => {
      resolveSend = resolve;
    });
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const path = new URL(request.url).pathname;

      if (path === `/api/v1/workspaces/${ids.workspace}/allies/${ids.ally}`) {
        return Response.json({ status: 'success', message: 'Ally loaded', data: allyResponse });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/allies/${ids.ally}/conversation`) {
        return Response.json({ status: 'success', message: 'Conversation loaded', data: emptyConversation });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}/activities`) {
        return Response.json(activityResponse());
      }
      if (path === `/api/v1/allies/${ids.ally}/runtime-intents`) {
        return Response.json({ status: 'success', message: 'Runtime intent accepted', data: { status: 'waking' } }, { status: 202 });
      }
      if (path === `/api/v1/workspaces/${ids.workspace}/conversations/${ids.conversation}/messages`) {
        sendRequest = request;
        return delayedSend;
      }
      throw new Error(`Unexpected request: ${request.method} ${path}`);
    });
    const client = createMobileCloudClient({
      cloudApiUrl: 'https://cloud.example.com',
      nativeAuthRedirectUri: 'https://mobile.example/auth/return',
      fetch,
    });
    client.setAccessToken('access-example');
    const adapter = { withRefresh: (operation: () => Promise<unknown>) => operation() };
    harness.session.value = {
      account: account(),
      accountClient: client.account,
      adapter,
      restore: vi.fn(async () => undefined),
      status: 'signed-in',
    };

    const route = renderRoute();
    await settleRoute();
    const input = document.querySelector('input[aria-label="Message Mira"]') as HTMLInputElement | null;
    const send = document.querySelector('button[aria-label="Send message"]') as HTMLButtonElement | null;
    expect(input).not.toBeNull();
    expect(send).not.toBeNull();

    fireEvent.change(input!, { target: { value: 'Late message' } });
    await settleRoute();
    fireEvent.click(send!);
    await settleRoute();
    expect(harness.pendingStore.saveMessage).toHaveBeenCalledTimes(1);
    expect(resolveSend).not.toBeNull();

    act(() => {
      harness.session.value = {
        account: account('00000000-0000-4000-8000-000000000011'),
        accountClient: client.account,
        adapter,
        restore: vi.fn(async () => undefined),
        status: 'signed-in',
      };
      route.rerenderRoute();
    });
    await settleRoute();
    expect(sendRequest).not.toBeNull();
    expect((sendRequest as unknown as Request).signal.aborted).toBe(true);

    const newAccountInput = document.querySelector('input[aria-label="Message Mira"]') as HTMLInputElement | null;
    expect(newAccountInput).not.toBeNull();
    expect(newAccountInput!.value).toBe('');
    fireEvent.change(newAccountInput!, { target: { value: 'New account draft' } });
    await settleRoute();

    resolveSend!(Response.json({
      status: 'success',
      message: 'Message accepted',
      data: { conversation_id: ids.conversation, message: acceptedMessage, execution: null, replayed: false },
    }, { status: 201 }));
    await settleRoute();

    expect(harness.pendingStore.deleteMessage).not.toHaveBeenCalled();
    expect(newAccountInput!.value).toBe('New account draft');
    const cachedConversation = route.queryClient.getQueryData<{
      pages?: { messages?: { id?: string }[] }[];
    }>(['allies', 'conversation', ids.workspace, ids.ally]);
    expect(cachedConversation?.pages?.flatMap((page) => page.messages ?? []) ?? [])
      .not.toEqual(expect.arrayContaining([expect.objectContaining({ id: ids.user })]));
    route.unmount();
  });
});
