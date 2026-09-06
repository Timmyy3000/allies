import { describe, expect, it } from 'vitest';
import type { MessageViewModel } from '@allies/cloud-client';

import {
  createConversationScrollIntent,
  insertAcceptedMessage,
  isActivityPollingAllowed,
  isMessageTerminal,
  mergeConversationMessages,
  queuedConversationMessages,
  replaceNewestConversationPage,
  shouldKeepPendingMessage,
} from './conversation-state';

const message = (id: string, sequence: number, content = id) => ({
  id,
  sender: (id === 'ally-message' ? 'assistant' : 'user') as MessageViewModel['sender'],
  content,
  sequence,
  status: 'completed' as MessageViewModel['status'],
  createdAt: '2026-08-28T00:00:00.000Z',
}) satisfies MessageViewModel;

describe('conversation state', () => {
  it('uses the complete Cloud queue even beyond the history page and releases only correlated progress', () => {
    const head: MessageViewModel = { ...message('head', 2), status: 'queued', queueState: 'claimed' };
    const tail: MessageViewModel = { ...message('tail', 3), status: 'queued', queueState: 'unclaimed' };
    const page = { id: 'conversation', allyId: 'ally', assistantReplies: [], messages: [tail], queue: [head, tail], nextCursor: 'older' };
    const projection = { turns: [], seenSequences: [], lastContiguousSequence: 0, state: 'queued' as const };
    expect(queuedConversationMessages([page], projection)).toEqual([head, tail]);
    expect(queuedConversationMessages([page], { ...projection, state: 'running', activeMessageId: head.id })).toEqual([tail]);
    expect(queuedConversationMessages([page], { ...projection, state: 'running', activeMessageId: 'foreign-head' })).toEqual([head, tail]);
    expect(mergeConversationMessages([page])).toEqual([head, tail]);
  });

  it('removes a Cloud-deleted tail from queue and every cached copy without resurrecting its content', () => {
    const tail: MessageViewModel = { ...message('tail', 3, 'Private queued text'), status: 'queued', queueState: 'unclaimed' };
    const page = { id: 'conversation', allyId: 'ally', assistantReplies: [], messages: [tail], queue: [tail], nextCursor: 'older' };
    const deleted: MessageViewModel = { ...tail, content: '', status: 'stopped', queueState: null, deletedAt: '2026-09-06T12:00:00Z' };
    const pages = insertAcceptedMessage([page, page], deleted);
    expect(pages[0].queue).toEqual([]);
    expect(mergeConversationMessages(pages)).toEqual([]);
    expect(mergeConversationMessages(insertAcceptedMessage(pages, tail))).toEqual([]);
    const staleRefresh = replaceNewestConversationPage(pages, page);
    expect(staleRefresh[0].queue).toEqual([]);
    expect(mergeConversationMessages(staleRefresh)).toEqual([]);
    const remoteDeleted = replaceNewestConversationPage([page, page], { ...page, messages: [deleted], queue: [] });
    const afterEviction = replaceNewestConversationPage(remoteDeleted, {
      ...page, messages: [message('later', 60)], queue: [],
    });
    expect(mergeConversationMessages(afterEviction)).toEqual([message('later', 60)]);
    expect(mergeConversationMessages([{ ...page, messages: [], queue: [] }, page])).toEqual([]);
  });

  it('deduplicates immutable messages and sorts them by sequence', () => {
    const messages = mergeConversationMessages([
      { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('ally-message', 2), message('user-message', 1)], nextCursor: 'older' },
      { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('user-message', 1)], nextCursor: null },
    ]);

    expect(messages.map(({ id }) => id)).toEqual(['user-message', 'ally-message']);
  });

  it('rejects conflicting copies of one immutable message ID', () => {
    expect(() => mergeConversationMessages([
      { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('same', 1, 'first')], nextCursor: null },
      { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('same', 1, 'different')], nextCursor: null },
    ])).toThrow('Conflicting message copies');
  });

  it('keeps the newest-page copy when mutable message status differs', () => {
    const newest: MessageViewModel = { ...message('same', 1), status: 'completed' };
    const older: MessageViewModel = { ...message('same', 1), status: 'queued' };

    expect(mergeConversationMessages([
      { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [newest], nextCursor: 'older' },
      { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [older], nextCursor: null },
    ])).toEqual([newest]);
  });

  it('updates only the newest page while preserving manually loaded history', () => {
    const newest = { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('new', 3)], nextCursor: 'older' };
    const oldNewest = { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('old-new', 2)], nextCursor: 'older' };
    const older = { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('old', 1)], nextCursor: null };

    expect(replaceNewestConversationPage([oldNewest, older], newest)).toEqual([newest, older]);
    expect(insertAcceptedMessage([oldNewest, older], message('accepted', 3))).toEqual([
      { ...oldNewest, messages: [message('accepted', 3), ...oldNewest.messages] },
      older,
    ]);
  });

  it('rejects a conflicting accepted-message collision', () => {
    const page = { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('same', 1, 'old')], nextCursor: null };

    expect(() => insertAcceptedMessage([page], message('same', 1, 'new'))).toThrow('Conflicting message copies');
  });

  it('does not duplicate a replayed acceptance already present in the newest page', () => {
    const page = { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('same', 1)], nextCursor: null };

    expect(insertAcceptedMessage([page], message('same', 1))).toEqual([page]);
  });

  it('moves a replayed acceptance out of an older page without dropping that page', () => {
    const newest = { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('new', 3)], nextCursor: 'older' };
    const older = { id: 'conversation', allyId: 'ally-1', assistantReplies: [], messages: [message('same', 1)], nextCursor: null };

    expect(insertAcceptedMessage([newest, older], message('same', 1))).toEqual([
      { ...newest, messages: [message('same', 1), message('new', 3)] },
      { ...older, messages: [] },
    ]);
  });

  it.each([
    ['queued', true],
    ['in_progress', true],
    ['running', true],
    ['awaiting_action', true],
    ['completed', false],
    ['failed', false],
    ['stopped', false],
    ['unknown', false],
  ] as const)('allows polling only for active state %s', (state, expected) => {
    expect(isActivityPollingAllowed({ focused: true, state, startedAt: 0, now: 1_000 })).toBe(expected);
  });

  it.each([
    ['queued', false],
    ['in_progress', false],
    ['awaiting_action', false],
    ['completed', true],
    ['failed', true],
    ['stopped', true],
  ] as const)('identifies terminal accepted message state %s', (status, expected) => {
    expect(isMessageTerminal(status)).toBe(expected);
  });

  it('stops polling after two minutes or when the screen is blurred', () => {
    expect(isActivityPollingAllowed({ focused: true, state: 'running', startedAt: 0, now: 120_000 })).toBe(false);
    expect(isActivityPollingAllowed({ focused: false, state: 'running', startedAt: 0, now: 1_000 })).toBe(false);
  });

  it.each([
    ['network', true],
    ['timeout', true],
    ['server', true],
    ['throttled', true],
    ['contract', true],
    ['validation', false],
    ['unauthorized', false],
  ] as const)('keeps a pending message after a %s outcome: %s', (kind, expected) => {
    expect(shouldKeepPendingMessage({ kind })).toBe(expected);
  });

  it('scrolls to latest content initially and after new activity, but preserves position for older history', () => {
    const intent = createConversationScrollIntent();

    expect(intent.consumeLatest()).toBe(true);
    expect(intent.consumeLatest()).toBe(false);

    intent.requestLatest();
    expect(intent.consumeLatest()).toBe(true);

    intent.requestLatest();
    intent.preservePosition();
    expect(intent.consumeLatest()).toBe(false);
  });
});
