import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import {
  getOnboardingGreeting,
  getRosterPreview,
} from '../onboarding/onboarding-preview';
import type { AllyColorValue, AllyShape } from '../onboarding/onboarding-state';

export const MOCK_MODE = true;

export type MockAlly = {
  color: AllyColorValue;
  id: string;
  job: string;
  name: string;
  online: boolean;
  personality: string;
  preview: string;
  shape: AllyShape;
  time: string;
};

export type MockAttachment = {
  kind: 'file' | 'folder';
  name: string;
  uri: string;
};

export type MockMessage = {
  attachments?: MockAttachment[];
  content: string;
  id: string;
  sender: 'assistant' | 'user';
};

type MockAppContextValue = {
  allies: MockAlly[];
  cancelReply: (allyId: string) => void;
  getConversation: (allyId: string) => MockMessage[];
  isMock: true;
  isReplying: (allyId: string) => boolean;
  registerAlly: (ally: Omit<MockAlly, 'id' | 'online' | 'preview' | 'time'>) => string;
  sendMessage: (allyId: string, message: string, attachments?: MockAttachment[]) => boolean;
};

export const DEFAULT_MOCK_ALLIES: MockAlly[] = [
  {
    color: '#3446E9',
    id: 'timi',
    job: 'Keep my plans moving and make the next step clear.',
    name: 'timi',
    online: true,
    personality: 'Practical and focused.',
    preview: 'Think of me as your always-available part…',
    shape: 'ghosty',
    time: '12:20 PM',
  },
  {
    color: '#FD304F',
    id: 'mock-ally',
    job: 'Help me make my day easier, more productive, and fun.',
    name: 'Sally',
    online: true,
    personality: 'Warm, clear, and helpful.',
    preview: 'Welcome! I am your ally, and I am thrilled t…',
    shape: 'rolly',
    time: '9:40 AM',
  },
];

const DEFAULT_CONVERSATIONS: Record<string, MockMessage[]> = {
  'mock-ally': [
    { content: getOnboardingGreeting(''), id: 'mock-ally-welcome', sender: 'assistant' },
  ],
  timi: [
    {
      content: 'Think of me as your always-available partner for planning, organising, and getting things done.',
      id: 'timi-welcome',
      sender: 'assistant',
    },
  ],
};

const MockAppContext = createContext<MockAppContextValue | null>(null);

export function getMockGreeting(): string {
  return getOnboardingGreeting('');
}

export function getMockPreviewText(message: string, attachments: MockAttachment[] = []): string {
  const content = message.trim();
  return content || (attachments.length === 1
    ? attachments[0].name
    : `${attachments.length} attachments`);
}

export function getMockReply(message: string): string {
  const subject = message.trim().replace(/[.!?]+$/u, '').toLowerCase();
  if (subject.includes('tomorrow')) {
    return 'Absolutely. For tomorrow, let’s choose your three most important outcomes, put the hardest one first, and leave a little room for the unexpected.';
  }
  return `I’ve got it. I’ll help you with ${subject || 'that'}, keep the important details close, and make the next step easy to act on.`;
}

export function MockAppProvider({ children }: { children: ReactNode }) {
  const [allies, setAllies] = useState(DEFAULT_MOCK_ALLIES);
  const [conversations, setConversations] = useState(DEFAULT_CONVERSATIONS);
  const [replyingAllyIds, setReplyingAllyIds] = useState<string[]>([]);
  const replyingIdsRef = useRef(new Set<string>());
  const replyTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const syncReplyingIds = useCallback(() => {
    setReplyingAllyIds([...replyingIdsRef.current]);
  }, []);

  const cancelReply = useCallback((allyId: string) => {
    const timer = replyTimersRef.current.get(allyId);
    if (timer) clearTimeout(timer);
    replyTimersRef.current.delete(allyId);
    replyingIdsRef.current.delete(allyId);
    syncReplyingIds();
  }, [syncReplyingIds]);

  useEffect(() => () => {
    replyTimersRef.current.forEach((timer) => clearTimeout(timer));
    replyTimersRef.current.clear();
    replyingIdsRef.current.clear();
  }, []);

  const registerAlly = useCallback((ally: Omit<MockAlly, 'id' | 'online' | 'preview' | 'time'>) => {
    const id = `mock-${Date.now()}`;
    const nextAlly: MockAlly = {
      ...ally,
      id,
      online: true,
      preview: getRosterPreview(getMockGreeting()),
      time: '9:40 AM',
    };
    setAllies((current) => [nextAlly, ...current]);
    setConversations((current) => ({
      ...current,
      [id]: [{ content: getMockGreeting(), id: `${id}-welcome`, sender: 'assistant' }],
    }));
    return id;
  }, []);

  const sendMessage = useCallback((allyId: string, message: string, attachments: MockAttachment[] = []) => {
    const content = message.trim();
    if ((!content && attachments.length === 0) || replyingIdsRef.current.has(allyId)) return false;
    const previewText = getMockPreviewText(content, attachments);

    replyingIdsRef.current.add(allyId);
    syncReplyingIds();
    setConversations((current) => ({
      ...current,
      [allyId]: [
        ...(current[allyId] ?? []),
        {
          attachments: attachments.length > 0 ? attachments : undefined,
          content,
          id: `${allyId}-user-${Date.now()}`,
          sender: 'user',
        },
      ],
    }));
    setAllies((current) => current.map((ally) => ally.id === allyId
      ? { ...ally, preview: getRosterPreview(previewText), time: 'Now' }
      : ally));

    let timer: ReturnType<typeof setTimeout>;
    timer = setTimeout(() => {
      if (replyTimersRef.current.get(allyId) !== timer) return;
      replyTimersRef.current.delete(allyId);
      replyingIdsRef.current.delete(allyId);
      const reply = getMockReply(content);
      setConversations((current) => ({
        ...current,
        [allyId]: [
          ...(current[allyId] ?? []),
          { content: reply, id: `${allyId}-assistant-${Date.now()}`, sender: 'assistant' },
        ],
      }));
      setAllies((current) => current.map((ally) => ally.id === allyId
        ? { ...ally, preview: getRosterPreview(reply), time: 'Now' }
        : ally));
      syncReplyingIds();
    }, 850);
    replyTimersRef.current.set(allyId, timer);
    return true;
  }, [syncReplyingIds]);

  const getConversation = useCallback(
    (allyId: string) => conversations[allyId] ?? [],
    [conversations],
  );
  const isReplying = useCallback(
    (allyId: string) => replyingAllyIds.includes(allyId),
    [replyingAllyIds],
  );
  const value = useMemo<MockAppContextValue>(() => ({
    allies,
    cancelReply,
    getConversation,
    isMock: MOCK_MODE,
    isReplying,
    registerAlly,
    sendMessage,
  }), [allies, cancelReply, getConversation, isReplying, registerAlly, sendMessage]);

  return <MockAppContext.Provider value={value}>{children}</MockAppContext.Provider>;
}

export function useMockApp(): MockAppContextValue {
  const context = useContext(MockAppContext);
  if (!context) throw new Error('useMockApp must be used inside MockAppProvider.');
  return context;
}
