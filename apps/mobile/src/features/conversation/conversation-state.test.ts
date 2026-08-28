import { describe, expect, it } from 'vitest';

import {
  createConversationScrollIntent,
  insertAcceptedMessage,
  isActivityPollingAllowed,
  mergeConversationMessages,
  replaceNewestConversationPage,
  shouldKeepPendingMessage,
} from './conversation-state';

const message = (id: string, sequence: number, content = id) => ({
  id,
  sender: id === 'ally-message' ? 'ally' : 'user',
  content,
  sequence,
  status: 'accepted',
  createdAt: '2026-08-28T00:00:00.000Z',
});

describe('conversation state', () => {
  it('deduplicates immutable messages and sorts them by sequence', () => {
    const messages = mergeConversationMessages([
      { id: 'conversation', allyId: 'ally-1', messages: [message('ally-message', 2), message('user-message', 1)], nextCursor: 'older' },
      { id: 'conversation', allyId: 'ally-1', messages: [message('user-message', 1)], nextCursor: null },
    ]);

    expect(messages.map(({ id }) => id)).toEqual(['user-message', 'ally-message']);
  });

  it('rejects conflicting copies of one immutable message ID', () => {
    expect(() => mergeConversationMessages([
      { id: 'conversation', allyId: 'ally-1', messages: [message('same', 1, 'first')], nextCursor: null },
      { id: 'conversation', allyId: 'ally-1', messages: [message('same', 1, 'different')], nextCursor: null },
    ])).toThrow('Conflicting message copies');
  });

  it('keeps the newest-page copy when mutable message status differs', () => {
    const newest = { ...message('same', 1), status: 'completed' };
    const older = { ...message('same', 1), status: 'accepted' };

    expect(mergeConversationMessages([
      { id: 'conversation', allyId: 'ally-1', messages: [newest], nextCursor: 'older' },
      { id: 'conversation', allyId: 'ally-1', messages: [older], nextCursor: null },
    ])).toEqual([newest]);
  });

  it('updates only the newest page while preserving manually loaded history', () => {
    const newest = { id: 'conversation', allyId: 'ally-1', messages: [message('new', 3)], nextCursor: 'older' };
    const oldNewest = { id: 'conversation', allyId: 'ally-1', messages: [message('old-new', 2)], nextCursor: 'older' };
    const older = { id: 'conversation', allyId: 'ally-1', messages: [message('old', 1)], nextCursor: null };

    expect(replaceNewestConversationPage([oldNewest, older], newest)).toEqual([newest, older]);
    expect(insertAcceptedMessage([oldNewest, older], message('accepted', 3))).toEqual([
      { ...oldNewest, messages: [message('accepted', 3), ...oldNewest.messages] },
      older,
    ]);
  });

  it('rejects a conflicting accepted-message collision', () => {
    const page = { id: 'conversation', allyId: 'ally-1', messages: [message('same', 1, 'old')], nextCursor: null };

    expect(() => insertAcceptedMessage([page], message('same', 1, 'new'))).toThrow('Conflicting message copies');
  });

  it.each([
    ['queued', true],
    ['in_progress', true],
    ['running', true],
    ['awaiting_action', false],
    ['completed', false],
    ['failed', false],
    ['stopped', false],
    ['unknown', false],
  ] as const)('allows polling only for active state %s', (state, expected) => {
    expect(isActivityPollingAllowed({ focused: true, state, startedAt: 0, now: 1_000 })).toBe(expected);
  });

  it('stops polling after ten minutes or when the screen is blurred', () => {
    expect(isActivityPollingAllowed({ focused: true, state: 'running', startedAt: 0, now: 600_000 })).toBe(false);
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
