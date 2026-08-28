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

import type { AllyColorValue, AllyShape } from '@/features/onboarding/onboarding-state';

export const MOCK_MODE = true;

export type MockAlly = {
  color: AllyColorValue;
  id: string;
  job: string;
  name: string;
  personality: string;
  shape: AllyShape;
};

export type MockMessage = {
  content: string;
  id: string;
  sender: 'assistant' | 'user';
};

type MockAppContextValue = {
  account: { displayName: string; email: string; username: string; workspaceName: string };
  activeAlly: MockAlly;
  allies: MockAlly[];
  createAlly: (ally: Omit<MockAlly, 'id'>, firstMessage: string) => void;
  isMock: true;
  isReplying: boolean;
  messages: MockMessage[];
  sendMessage: (message: string) => void;
  signIn: () => void;
};

const DEFAULT_ALLY: MockAlly = {
  color: '#FD304F',
  id: 'mock-ally',
  job: 'Help me plan my work, stay organised, and follow through.',
  name: 'Sally Morano',
  personality: 'Concise, warm, and clear.',
  shape: 'rolly',
};

const MockAppContext = createContext<MockAppContextValue | null>(null);

export function getMockGreeting(name: string, job: string): string {
  return `Hi, I’m ${name}. Here’s what I’m here to do: ${job}\n\nTell me what you want to tackle first, and we’ll turn it into a clear next step together.`;
}

export function getMockReply(message: string): string {
  const subject = message.trim().replace(/[.!?]+$/, '').toLowerCase();
  if (subject.includes('tomorrow')) {
    return 'Absolutely. For tomorrow, let’s choose your three most important outcomes, put the hardest one first, and leave a little room for the unexpected.';
  }
  return `I’ve got it. I’ll help you with ${subject || 'that'}, keep the important details close, and make the next step easy to act on.`;
}

export function MockAppProvider({ children }: { children: ReactNode }) {
  const [activeAlly, setActiveAlly] = useState(DEFAULT_ALLY);
  const [allies, setAllies] = useState<MockAlly[]>([DEFAULT_ALLY]);
  const [messages, setMessages] = useState<MockMessage[]>([
    { content: getMockGreeting(DEFAULT_ALLY.name, DEFAULT_ALLY.job), id: 'welcome', sender: 'assistant' },
  ]);
  const [isReplying, setIsReplying] = useState(false);
  const replyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (replyTimer.current) clearTimeout(replyTimer.current);
  }, []);

  const queueReply = useCallback((message: string) => {
    if (replyTimer.current) clearTimeout(replyTimer.current);
    setIsReplying(true);
    replyTimer.current = setTimeout(() => {
      setMessages((current) => [
        ...current,
        { content: getMockReply(message), id: `assistant-${Date.now()}`, sender: 'assistant' },
      ]);
      setIsReplying(false);
    }, 900);
  }, []);

  const createAlly = useCallback((ally: Omit<MockAlly, 'id'>, firstMessage: string) => {
    const nextAlly = { ...ally, id: 'mock-ally' };
    const greeting = getMockGreeting(nextAlly.name, nextAlly.job);
    setActiveAlly(nextAlly);
    setAllies((current) => [nextAlly, ...current.filter((item) => item.id !== nextAlly.id)]);
    setMessages([
      { content: greeting, id: 'welcome', sender: 'assistant' },
      { content: firstMessage, id: `user-${Date.now()}`, sender: 'user' },
    ]);
    queueReply(firstMessage);
  }, [queueReply]);

  const sendMessage = useCallback((message: string) => {
    const content = message.trim();
    if (!content || isReplying) return;
    setMessages((current) => [
      ...current,
      { content, id: `user-${Date.now()}`, sender: 'user' },
    ]);
    queueReply(content);
  }, [isReplying, queueReply]);

  const value = useMemo<MockAppContextValue>(() => ({
    account: {
      displayName: 'David',
      email: 'david@allies.app',
      username: 'daviddll',
      workspaceName: 'David’s Workspace',
    },
    activeAlly,
    allies,
    createAlly,
    isMock: MOCK_MODE,
    isReplying,
    messages,
    sendMessage,
    signIn: () => undefined,
  }), [activeAlly, allies, createAlly, isReplying, messages, sendMessage]);

  return <MockAppContext.Provider value={value}>{children}</MockAppContext.Provider>;
}

export function useMockApp(): MockAppContextValue {
  const context = useContext(MockAppContext);
  if (!context) throw new Error('useMockApp must be used inside MockAppProvider.');
  return context;
}
