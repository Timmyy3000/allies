import { describe, expect, it } from 'vitest';

import {
  activityStateForMessage,
  findLatestConversationUserMessage,
  hasPermanentMobileActivityGap,
  hasMobileActivityReplayGap,
  insertAcceptedMessage,
  getMobileActivityPollingInterval,
  isMobileActivityPollErrorRecoverable,
  isMobileActivityTerminalForMessage,
  isMessageExecutionActive,
  isMobileActivityPollingAllowed,
  loadMobileActivityReplay,
  mergeConversationAssistantReplies,
  mergeConversationMessages,
  projectMobileActivity,
  projectMobileActivityForMessage,
  queuedConversationMessages,
  refreshMobileConversationHistory,
  replaceNewestConversationPage,
  selectMobileConversationReplies,
  shouldContinueMobileActivityPolling,
  shouldRetryMobileActivityReplay,
} from './conversation-state';
import { EMPTY_ACTIVITY_PROJECTION, type AssistantReplyViewModel, type ConversationViewModel, type MessageViewModel } from '@allies/cloud-client';

const message = (overrides: Partial<{
  id: string;
  sender: 'user' | 'assistant';
  content: string;
  sequence: number;
  status: 'queued' | 'in_progress' | 'awaiting_action' | 'completed' | 'failed' | 'stopped';
}> = {}) => ({
  id: overrides.id ?? 'message-1',
  sender: overrides.sender ?? 'assistant',
  content: overrides.content ?? 'Hello',
  sequence: overrides.sequence ?? 1,
  status: overrides.status ?? 'completed',
  createdAt: '2026-01-01T00:00:00Z',
  retryable: false,
});

const activity = (sequence: number, text: string, state: 'running' | 'completed' = 'running') => ({
  id: `activity-${sequence}`,
  messageId: 'message-2',
  sequence,
  conversationTurnOrdinal: 1,
  kind: 'assistant_delta' as const,
  text,
  state,
  createdAt: '2026-01-01T00:00:00Z',
});

describe('mobile conversation state', () => {
  it('keeps newer pages and older pages in one ordered set without duplicates', () => {
    const pages = [
      { id: 'conversation', allyId: 'ally', messages: [message({ id: 'message-2', sequence: 2, content: 'new' })], assistantReplies: [], nextCursor: 'older' },
      { id: 'conversation', allyId: 'ally', messages: [message({ id: 'message-1', sequence: 1 }), message({ id: 'message-2', sequence: 2, content: 'new' })], assistantReplies: [], nextCursor: null },
    ];

    expect(mergeConversationMessages(pages).map((item) => item.id)).toEqual(['message-1', 'message-2']);
  });

  it('inserts accepted messages into the newest page without losing history', () => {
    const pages = [{ id: 'conversation', allyId: 'ally', messages: [message()], assistantReplies: [], nextCursor: 'older' }];

    expect(insertAcceptedMessage(pages, message({ id: 'message-2', sequence: 2, sender: 'user', content: 'Question' }))[0].messages)
      .toEqual([
        message(),
        message({ id: 'message-2', sequence: 2, sender: 'user', content: 'Question' }),
      ]);
  });

  it('correlates the terminal refresh with a newly accepted highest-sequence user turn', () => {
    const previousUser = message({ id: 'previous-user', sequence: 1, sender: 'user', content: 'Earlier' });
    const acceptedUser = message({ id: 'accepted-user', sequence: 2, sender: 'user', content: 'Latest' });
    const pages = [{
      id: 'conversation',
      allyId: 'ally',
      messages: [previousUser],
      assistantReplies: [],
      nextCursor: 'older',
    }];
    const cachedPages = insertAcceptedMessage(pages, acceptedUser);
    const latest = findLatestConversationUserMessage(cachedPages[0].messages);
    const terminalSnapshot = {
      conversationId: 'conversation',
      activities: [{ ...activity(2, 'done', 'completed'), messageId: acceptedUser.id }],
      assistantReply: null,
      state: 'completed' as const,
      lastContiguousSequence: 2,
      latestSequence: 2,
    };

    expect(latest?.id).toBe(acceptedUser.id);
    expect(isMobileActivityTerminalForMessage(terminalSnapshot, latest?.id)).toBe(true);
  });

  it('uses the authoritative newest page when a refetch supersedes local message copies', () => {
    const pages = [{ id: 'conversation', allyId: 'ally', messages: [message({ id: 'message-2', sequence: 2, sender: 'user' })], assistantReplies: [], nextCursor: 'older' }];
    const newest = { id: 'conversation', allyId: 'ally', messages: [message({ id: 'message-1', sequence: 1 })], assistantReplies: [], nextCursor: 'older' };

    expect(replaceNewestConversationPage(pages, newest)[0]?.messages.map((item) => item.id))
      .toEqual(['message-1']);
  });

  it('uses the complete Cloud queue and releases only the correlated active message', () => {
    const head = { ...message({ id: 'head', sequence: 2, sender: 'user', status: 'queued' }), queueState: 'claimed' as const } satisfies MessageViewModel;
    const tail = { ...message({ id: 'tail', sequence: 3, sender: 'user', status: 'queued' }), queueState: 'unclaimed' as const } satisfies MessageViewModel;
    const page = { id: 'conversation', allyId: 'ally', assistantReplies: [], messages: [tail], queue: [head, tail], nextCursor: 'older' };
    const projection = { ...EMPTY_ACTIVITY_PROJECTION, state: 'queued' as const };

    expect(queuedConversationMessages([page], projection)).toEqual([head, tail]);
    expect(queuedConversationMessages([page], { ...projection, state: 'running', activeMessageId: head.id })).toEqual([tail]);
    expect(mergeConversationMessages([page])).toEqual([head, tail]);
  });

  it('keeps a Cloud deletion tombstone from resurrecting queued text', () => {
    const tail = { ...message({ id: 'tail', sequence: 3, sender: 'user', content: 'Private text', status: 'queued' }), queueState: 'unclaimed' as const } satisfies MessageViewModel;
    const page = { id: 'conversation', allyId: 'ally', assistantReplies: [], messages: [tail], queue: [tail], nextCursor: null };
    const deleted = { ...tail, content: '', status: 'stopped' as const, queueState: null, deletedAt: '2026-09-06T12:00:00Z' } satisfies MessageViewModel;
    const pages = insertAcceptedMessage([page], deleted);

    expect(pages[0].queue).toEqual([]);
    expect(mergeConversationMessages(pages)).toEqual([]);
    expect(mergeConversationMessages(insertAcceptedMessage(pages, tail))).toEqual([]);
  });

  it('projects out-of-order activities and exposes a permanent terminal gap', () => {
    const running = projectMobileActivity(EMPTY_ACTIVITY_PROJECTION, {
      conversationId: 'conversation',
      activities: [activity(2, 'world')],
      state: 'running',
      lastContiguousSequence: 0,
      lastContiguousActivitySequence: 0,
    });
    const terminal = projectMobileActivity(running, {
      conversationId: 'conversation',
      activities: [activity(1, 'Hello', 'completed')],
      state: 'completed',
      lastContiguousSequence: 1,
      lastContiguousActivitySequence: 1,
    });

    expect(terminal.turns[0]?.assistantText).toBe('Helloworld');
    expect(hasPermanentMobileActivityGap(terminal)).toBe(false);
    expect(isMobileActivityPollingAllowed({ focused: true, state: 'running', startedAt: 0, now: 1 })).toBe(true);
    expect(isMobileActivityPollingAllowed({ focused: true, state: 'completed', startedAt: 0, now: 1 })).toBe(false);
    expect(isMobileActivityPollingAllowed({ focused: true, state: 'running', startedAt: 0, now: 119_999 })).toBe(true);
    expect(isMobileActivityPollingAllowed({ focused: true, state: 'running', startedAt: 0, now: 120_000 })).toBe(true);
    expect(getMobileActivityPollingInterval({ focused: true, state: 'running', startedAt: 0, now: 120_001 })).toBe(6_000);
    expect(getMobileActivityPollingInterval({ focused: true, state: 'running', startedAt: 0, now: 240_001 })).toBe(12_000);
    expect(getMobileActivityPollingInterval({ focused: true, state: 'running', startedAt: 0, now: 600_000 })).toBe(15_000);
    expect(isMobileActivityPollErrorRecoverable({ kind: 'network' })).toBe(true);
    expect(isMobileActivityPollErrorRecoverable({ kind: 'contract' })).toBe(false);
    expect(isMobileActivityPollErrorRecoverable(null)).toBe(true);
    expect(shouldContinueMobileActivityPolling({ focused: true, state: null, knownExecutionActive: true })).toBe(true);
    expect(shouldContinueMobileActivityPolling({ focused: true, state: null, knownExecutionActive: false })).toBe(false);
  });

  it('maps accepted message statuses to the activity polling state', () => {
    expect(activityStateForMessage('queued')).toBe('queued');
    expect(activityStateForMessage('in_progress')).toBe('running');
    expect(activityStateForMessage('completed')).toBe('completed');
    expect(isMessageExecutionActive('queued')).toBe(true);
    expect(isMessageExecutionActive('completed')).toBe(false);
  });

  it('treats a terminal snapshot as authoritative only for its latest user turn', async () => {
    const previousUserId = 'previous-user';
    const latestUserId = 'latest-user';
    const terminalSnapshot = {
      conversationId: 'conversation',
      activities: [{ ...activity(2, 'done', 'completed'), messageId: previousUserId }],
      assistantReply: null,
      state: 'completed' as const,
      lastContiguousSequence: 2,
      latestSequence: 2,
    };

    expect(isMobileActivityTerminalForMessage(terminalSnapshot, previousUserId)).toBe(true);
    expect(isMobileActivityTerminalForMessage(terminalSnapshot, latestUserId)).toBe(false);
    expect(shouldContinueMobileActivityPolling({
      focused: true,
      state: isMobileActivityTerminalForMessage(terminalSnapshot, latestUserId) ? terminalSnapshot.state : 'running',
      knownExecutionActive: true,
    })).toBe(true);
  });

  it('ignores a previous turn terminal snapshot after accepting a newer turn', () => {
    const previousUserId = 'previous-user';
    const latestUserId = 'latest-user';
    const staleFailed = {
      conversationId: 'conversation',
      activities: [{ ...activity(1, 'failed'), messageId: previousUserId, state: 'failed' as const }],
      assistantReply: null,
      state: 'failed' as const,
      lastContiguousSequence: 1,
    };
    const acceptedProjection = {
      ...projectMobileActivity(EMPTY_ACTIVITY_PROJECTION, staleFailed),
      state: 'running' as const,
    };

    const afterStale = projectMobileActivityForMessage(acceptedProjection, staleFailed, latestUserId);
    expect(afterStale.state).toBe('running');
    expect(hasPermanentMobileActivityGap(afterStale)).toBe(false);
    expect(afterStale.turns[0]?.assistantText).toBe('failed');

    const latestCompleted = {
      conversationId: 'conversation',
      activities: [{ ...activity(2, 'done', 'completed'), messageId: latestUserId, conversationTurnOrdinal: 2 }],
      assistantReply: null,
      state: 'completed' as const,
      lastContiguousSequence: 2,
    };
    const afterLatest = projectMobileActivityForMessage(afterStale, latestCompleted, latestUserId);
    expect(afterLatest.state).toBe('completed');
    expect(afterLatest.turns.map((turn) => turn.messageId)).toEqual([previousUserId, latestUserId]);
  });

  it('falls back to a history refetch when terminal convergence refresh fails', async () => {
    const calls: string[] = [];
    await refreshMobileConversationHistory(
      async () => {
        calls.push('newest');
        throw new Error('temporary failure');
      },
      async () => {
        calls.push('history');
      },
    );

    expect(calls).toEqual(['newest', 'history']);
  });

  it('does not skip a cold replay prefix when Cloud metadata points at a high water mark', () => {
    const tail = projectMobileActivity(EMPTY_ACTIVITY_PROJECTION, {
      conversationId: 'conversation',
      activities: [activity(2, 'world')],
      state: 'running',
      lastContiguousSequence: 762,
      lastContiguousActivitySequence: 762,
      oldestSequence: 2,
      latestSequence: 762,
    });
    const origin = projectMobileActivity(tail, {
      conversationId: 'conversation',
      activities: [activity(1, 'Hello', 'completed')],
      state: 'completed',
      lastContiguousSequence: 762,
      lastContiguousActivitySequence: 762,
    });

    expect(origin.turns[0]?.assistantText).toBe('Helloworld');
    expect(hasPermanentMobileActivityGap(origin)).toBe(false);
  });

  it('keeps projecting more than 200 events received after cold hydration', () => {
    const hydrated = projectMobileActivity(EMPTY_ACTIVITY_PROJECTION, {
      conversationId: 'conversation',
      activities: [activity(1, 'a')],
      state: 'running',
      lastContiguousSequence: 1,
      lastContiguousActivitySequence: 1,
      oldestSequence: 1,
      latestSequence: 1,
    });
    const followup = Array.from({ length: 201 }, (_, index) => activity(index + 2, 'b'));
    const projected = projectMobileActivity(hydrated, {
      conversationId: 'conversation',
      activities: followup,
      state: 'running',
      lastContiguousSequence: 999,
      lastContiguousActivitySequence: 999,
      oldestSequence: 2,
      latestSequence: 202,
    });

    expect(projected.lastContiguousSequence).toBe(202);
    expect(projected.turns[0]?.assistantText).toBe(`a${'b'.repeat(201)}`);
  });

  it('loads every signed replay page beyond the 200 row live tail', async () => {
    const requests: { limit: number; cursor?: string; replay: true }[] = [];
    const pages = [
      { conversationId: 'conversation', activities: [], state: 'running' as const, lastContiguousSequence: 0, nextCursor: 'cursor-2' },
      { conversationId: 'conversation', activities: [], state: 'completed' as const, lastContiguousSequence: 201, nextCursor: null },
    ];
    const loaded = await loadMobileActivityReplay(async (options) => {
      requests.push(options);
      return pages.shift()!;
    });

    expect(loaded).toHaveLength(2);
    expect(requests).toEqual([
      { limit: 200, replay: true },
      { limit: 200, cursor: 'cursor-2', replay: true },
    ]);
  });

  it('starts a replay catch-up from the prior signed resume cursor', async () => {
    const requests: { limit: number; cursor?: string; replay: true }[] = [];
    const loaded = await loadMobileActivityReplay(async (options) => {
      requests.push(options);
      return {
        conversationId: 'conversation',
        activities: [],
        state: 'running' as const,
        lastContiguousSequence: 202,
        resumeCursor: 'cursor-next',
        nextCursor: null,
      };
    }, undefined, 'cursor-origin');

    expect(loaded).toHaveLength(1);
    expect(requests).toEqual([{ limit: 200, cursor: 'cursor-origin', replay: true }]);
  });

  it('rehydrates from origin once when a catch-up cursor expires', async () => {
    const requests: { limit: number; cursor?: string; replay: true }[] = [];
    let callCount = 0;
    await expect(loadMobileActivityReplay(async (options) => {
      requests.push(options);
      callCount += 1;
      if (callCount === 1) throw { kind: 'activity-cursor-expired' };
      return {
        conversationId: 'conversation',
        activities: [],
        state: 'completed' as const,
        lastContiguousSequence: 202,
        resumeCursor: 'cursor-origin-new',
        nextCursor: null,
      };
    }, undefined, 'cursor-origin')).resolves.toHaveLength(1);

    expect(requests).toEqual([
      { limit: 200, cursor: 'cursor-origin', replay: true },
      { limit: 200, replay: true },
    ]);
  });

  it('retries an expired replay cursor once and surfaces retention gaps', () => {
    expect(shouldRetryMobileActivityReplay(0, { kind: 'activity-cursor-expired' })).toBe(true);
    expect(shouldRetryMobileActivityReplay(1, { kind: 'activity-cursor-expired' })).toBe(false);
    expect(shouldRetryMobileActivityReplay(0, { kind: 'activity-cursor-gap' })).toBe(false);
    expect(hasMobileActivityReplayGap([{
      conversationId: 'conversation',
      activities: [],
      state: 'completed',
      lastContiguousSequence: 0,
      oldestSequence: 4,
      retentionGap: true,
    }])).toBe(true);
  });

  it('renders one durable reply or one activity turn for each user source', () => {
    const user = message({ id: 'user-2', sender: 'user', sequence: 2, content: 'Question' });
    const legacyAssistant = message({ id: 'assistant-2', sender: 'assistant', sequence: 3, content: 'Legacy response' });
    const page: ConversationViewModel = {
      id: 'conversation',
      allyId: 'ally',
      messages: [user, legacyAssistant],
      assistantReplies: [],
      nextCursor: null,
    };
    const turn = { assistantText: 'Live response', messageId: user.id, state: 'completed' as const, turnOrdinal: 2 };
    const reply: AssistantReplyViewModel = {
      id: 'reply-2',
      sourceMessageId: user.id,
      conversationTurnOrdinal: 2,
      content: 'Durable response',
      status: 'completed',
      hasFullPrefix: true,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:01Z',
    };

    const durable = selectMobileConversationReplies(
      page.messages,
      [turn],
      mergeConversationAssistantReplies([{ ...page, assistantReplies: [reply] }]),
    );
    expect(durable.inlineBySourceMessageId.get(user.id)).toMatchObject({ kind: 'durable' });
    expect(durable.remainingTurns).toEqual([]);
    expect(durable.suppressedAssistantMessageIds).toContain(legacyAssistant.id);

    const activityOnly = selectMobileConversationReplies(
      [user],
      [turn],
      [],
    );
    expect(activityOnly.inlineBySourceMessageId.get(user.id)).toMatchObject({ kind: 'activity' });
    expect(activityOnly.remainingTurns).toEqual([]);
  });

  it('preserves a truncated durable prefix and terminal status in the durable render selection', () => {
    const reply: AssistantReplyViewModel = {
      id: 'reply-truncated',
      sourceMessageId: 'user-truncated',
      conversationTurnOrdinal: 5,
      content: 'Durable prefix',
      status: 'completed',
      hasFullPrefix: true,
      isTruncated: true,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:01Z',
    };
    const selection = selectMobileConversationReplies([
      message({ id: 'user-truncated', sender: 'user', sequence: 5, content: 'Question' }),
    ], [], [reply]);
    const selected = selection.inlineBySourceMessageId.get(reply.sourceMessageId);

    expect(selected).toMatchObject({
      kind: 'durable',
      reply: { content: reply.content, status: reply.status, isTruncated: true },
    });
    expect(selection.remainingReplies).toEqual([]);
    expect(selection.remainingTurns).toEqual([]);
    for (const copies of [[reply, { ...reply, isTruncated: false }], [{ ...reply, isTruncated: false }, reply]]) {
      expect(mergeConversationAssistantReplies([], copies)[0]?.isTruncated).toBe(true);
    }
  });

  it('keeps a terminal durable reply ahead of a delayed running snapshot at the same timestamp', () => {
    const user = message({ id: 'user-3', sender: 'user', sequence: 3, content: 'Question' });
    const terminal: AssistantReplyViewModel = {
      id: 'reply-terminal',
      sourceMessageId: user.id,
      conversationTurnOrdinal: 3,
      content: 'Done',
      status: 'completed',
      hasFullPrefix: true,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:02Z',
    };
    const delayedRunning: AssistantReplyViewModel = {
      ...terminal,
      id: 'reply-running',
      content: 'Delayed running prefix with more text',
      status: 'in_progress',
    };

    expect(mergeConversationAssistantReplies([
      { id: 'conversation', allyId: 'ally', messages: [user], assistantReplies: [terminal], nextCursor: null },
    ], delayedRunning)).toEqual([terminal]);
  });

  it('keeps rollout suffix replies as a fallback behind activity text', () => {
    const user = message({ id: 'user-4', sender: 'user', sequence: 4, content: 'Question' });
    const turn = { assistantText: 'Activity prefix', messageId: user.id, state: 'completed' as const, turnOrdinal: 4 };
    const suffix: AssistantReplyViewModel = {
      id: 'reply-suffix',
      sourceMessageId: user.id,
      conversationTurnOrdinal: 4,
      content: 'Suffix only',
      status: 'completed',
      hasFullPrefix: false,
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:01Z',
    };

    const selection = selectMobileConversationReplies([user], [turn], [suffix]);
    expect(selection.inlineBySourceMessageId.get(user.id)).toMatchObject({ kind: 'activity' });
    expect(selection.remainingReplies).toEqual([]);

    const fullPrefix = { ...suffix, id: 'reply-full', content: 'Full prefix', hasFullPrefix: true };
    expect(mergeConversationAssistantReplies([
      { id: 'conversation', allyId: 'ally', messages: [user], assistantReplies: [suffix], nextCursor: null },
    ], fullPrefix)).toEqual([fullPrefix]);
  });
});
