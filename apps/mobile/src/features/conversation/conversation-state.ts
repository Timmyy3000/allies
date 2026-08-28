import type { ActivitySnapshotViewModel, ConversationPageViewModel, MessageViewModel } from '@allies/cloud-client';

const ACTIVE_ACTIVITY_STATES = new Set(['queued', 'in_progress', 'running']);
const ACTIVITY_POLL_WINDOW_MS = 10 * 60 * 1000;

function sameMessage(left: MessageViewModel, right: MessageViewModel): boolean {
  return left.id === right.id
    && left.sender === right.sender
    && left.content === right.content
    && left.sequence === right.sequence;
}

export function mergeConversationMessages(pages: readonly ConversationPageViewModel[]): MessageViewModel[] {
  const messages = new Map<string, MessageViewModel>();

  for (const page of pages) {
    for (const message of page.messages) {
      const existing = messages.get(message.id);
      if (existing && !sameMessage(existing, message)) throw new Error('Conflicting message copies');
      if (!existing) messages.set(message.id, message);
    }
  }

  return [...messages.values()].sort((left, right) => left.sequence - right.sequence || left.id.localeCompare(right.id));
}

export function replaceNewestConversationPage(
  pages: readonly ConversationPageViewModel[],
  newest: ConversationPageViewModel,
): ConversationPageViewModel[] {
  return pages.length ? [newest, ...pages.slice(1)] : [newest];
}

export function insertAcceptedMessage(
  pages: readonly ConversationPageViewModel[],
  message: MessageViewModel,
): ConversationPageViewModel[] {
  if (!pages.length) return [];
  const newest = pages[0];
  const existing = newest.messages.find((current) => current.id === message.id);
  if (existing && !sameMessage(existing, message)) throw new Error('Conflicting message copies');
  return [
    {
      ...newest,
      messages: [message, ...newest.messages.filter((current) => current.id !== message.id)],
    },
    ...pages.slice(1),
  ];
}

export function isActivityPollingAllowed(input: {
  focused: boolean;
  state: ActivitySnapshotViewModel['state'] | string;
  startedAt: number;
  now: number;
}): boolean {
  return input.focused
    && ACTIVE_ACTIVITY_STATES.has(input.state)
    && input.now - input.startedAt < ACTIVITY_POLL_WINDOW_MS;
}
