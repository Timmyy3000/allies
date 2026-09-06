import {
  isCloudError,
  mergeConversationMessageCopies,
  type ActivityProjection,
  type ActivitySnapshotViewModel,
  type ConversationViewModel,
  type MessageViewModel,
} from '@allies/cloud-client';

const ACTIVE_ACTIVITY_STATES = new Set(['queued', 'in_progress', 'running', 'awaiting_action']);
const AMBIGUOUS_MESSAGE_ERROR_KINDS = new Set(['network', 'timeout', 'server', 'throttled', 'contract', 'aborted']);
const ACTIVITY_POLL_WINDOW_MS = 2 * 60 * 1000;

function sameMessage(left: MessageViewModel, right: MessageViewModel): boolean {
  return left.id === right.id
    && left.sender === right.sender
    && (left.content === right.content || Boolean(left.deletedAt) || Boolean(right.deletedAt))
    && left.sequence === right.sequence;
}

export function mergeConversationMessages(pages: readonly ConversationViewModel[]): MessageViewModel[] {
  const messages = new Map<string, MessageViewModel>();

  for (const page of pages) {
    for (const message of page.messages) {
      const existing = messages.get(message.id);
      if (existing && !sameMessage(existing, message)) throw new Error('Conflicting message copies');
      if (!existing) messages.set(message.id, message);
    }
  }

  const queue = pages[0]?.queue;
  const queueIds = queue && new Set(queue.map((item) => item.id));
  return mergeConversationMessageCopies(...[...pages].reverse().map((page) => page.messages), queue ?? [])
    .filter((item) => !item.deletedAt && !(queueIds && item.status === 'queued' && !queueIds.has(item.id)));
}

export function queuedConversationMessages(
  pages: readonly ConversationViewModel[],
  projection: ActivityProjection,
): MessageViewModel[] {
  const candidates = pages[0]?.queue ?? mergeConversationMessageCopies(...pages.map((page) => page.messages));
  return candidates.filter((item) => {
    if (item.sender !== 'user' || item.deletedAt || item.status !== 'queued') return false;
    const turn = projection.turns.find((value) => value.messageId === item.id && value.turnOrdinal === item.sequence);
    if (turn && (turn.state !== 'queued' || turn.assistantText.trim())) return false;
    if (pages.some((page) => page.assistantReplies.some((reply) =>
      reply.sourceMessageId === item.id && reply.conversationTurnOrdinal === item.sequence && reply.content.trim()))) return false;
    return !(projection.activeMessageId === item.id && projection.state !== 'queued');
  });
}

export function replaceNewestConversationPage(
  pages: readonly ConversationViewModel[],
  newest: ConversationViewModel,
): ConversationViewModel[] {
  if (!pages.length) return [newest];
  const existing = mergeConversationMessageCopies(...pages.map((page) => page.messages), pages[0].queue ?? []);
  const incomingIds = new Set([...newest.messages, ...newest.queue ?? []].map((item) => item.id));
  const resolved = mergeConversationMessageCopies(existing.filter((item) => incomingIds.has(item.id)), newest.messages, newest.queue ?? []);
  const messageIds = new Set(newest.messages.map((item) => item.id));
  const queueIds = new Set(newest.queue?.map((item) => item.id));
  return [{
    ...newest,
    messages: resolved.filter((item) => messageIds.has(item.id)),
    ...(newest.queue === undefined ? {} : {
      queue: resolved.filter((item) => queueIds.has(item.id) && !item.deletedAt && !isMessageTerminal(item.status)),
    }),
  }, ...pages.slice(1).map((page) => ({
    ...page,
    messages: mergeConversationMessageCopies(page.messages, resolved.filter((item) => item.deletedAt))
      .filter((item) => !item.deletedAt),
  }))];
}

export function insertAcceptedMessage(
  pages: readonly ConversationViewModel[],
  message: MessageViewModel,
): ConversationViewModel[] {
  if (!pages.length) return [];
  const newest = pages[0];
  const existing = mergeConversationMessageCopies(...pages.map((page) => page.messages), newest.queue ?? [])
    .find((current) => current.id === message.id);
  if (existing && !sameMessage(existing, message)) throw new Error('Conflicting message copies');
  const resolved = mergeConversationMessageCopies(existing ? [existing] : [], [message])[0];
  const queue = newest.queue === undefined ? undefined
    : mergeConversationMessageCopies(newest.queue.filter((item) => item.id !== message.id), [resolved])
      .filter((item) => !item.deletedAt && !isMessageTerminal(item.status));
  return [
    {
      ...newest,
      messages: [resolved, ...newest.messages.filter((current) => current.id !== message.id)],
      ...(queue === undefined ? {} : { queue }),
    },
    ...pages.slice(1).map((page) => ({
      ...page,
      messages: page.messages.filter((current) => current.id !== message.id),
    })),
  ];
}

export function isMessageTerminal(status: string): boolean {
  return status === 'completed' || status === 'failed' || status === 'stopped';
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

export function shouldKeepPendingMessage(error: unknown): boolean {
  return !isCloudError(error) || AMBIGUOUS_MESSAGE_ERROR_KINDS.has(error.kind);
}

export function createConversationScrollIntent() {
  let latestRequested = true;

  return {
    consumeLatest() {
      const requested = latestRequested;
      latestRequested = false;
      return requested;
    },
    preservePosition() {
      latestRequested = false;
    },
    requestLatest() {
      latestRequested = true;
    },
  };
}
