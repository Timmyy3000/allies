import {
  ACTIVE_ACTIVITY_STATES,
  EMPTY_ACTIVITY_PROJECTION,
  hasPermanentActivityGap,
  isCloudError,
  mergeConversationMessageCopies,
  projectActivitySnapshot,
  type ActivityProjection,
  type ActivitySnapshotViewModel,
  type AssistantReplyViewModel,
  type AssistantTurnProjection,
  type ConversationViewModel,
  type MessageStatus,
  type MessageViewModel,
} from '@allies/cloud-client';

export { EMPTY_ACTIVITY_PROJECTION };

function sameMessage(left: MessageViewModel, right: MessageViewModel): boolean {
  return left.id === right.id
    && left.sender === right.sender
    && (left.content === right.content || Boolean(left.deletedAt) || Boolean(right.deletedAt))
    && left.sequence === right.sequence;
}

function compareMessageOrder(left: MessageViewModel, right: MessageViewModel): number {
  return left.sequence - right.sequence || left.id.localeCompare(right.id);
}

export function mergeConversationMessages(
  pages: readonly ConversationViewModel[],
): MessageViewModel[] {
  const queue = pages[0]?.queue;
  const queueIds = queue && new Set(queue.map((message) => message.id));
  return mergeConversationMessageCopies(
    ...[...pages].reverse().map((page) => page.messages),
    queue ?? [],
  ).filter((message) => !message.deletedAt && !(queueIds && message.status === 'queued' && !queueIds.has(message.id)));
}

export function queuedConversationMessages(
  pages: readonly ConversationViewModel[],
  projection: ActivityProjection,
): MessageViewModel[] {
  const candidates = pages[0]?.queue ?? mergeConversationMessageCopies(...pages.map((page) => page.messages));
  return candidates.filter((message) => {
    if (message.sender !== 'user' || message.deletedAt || message.status !== 'queued') return false;
    const turn = projection.turns.find((value) => value.messageId === message.id && value.turnOrdinal === message.sequence);
    if (turn && (turn.state !== 'queued' || turn.assistantText.trim())) return false;
    if (pages.some((page) => page.assistantReplies.some((reply) =>
      reply.sourceMessageId === message.id && reply.conversationTurnOrdinal === message.sequence && reply.content.trim()))) return false;
    return !(projection.activeMessageId === message.id && projection.state !== 'queued');
  });
}

export function findLatestConversationUserMessage(
  messages: readonly MessageViewModel[],
): MessageViewModel | undefined {
  return messages.reduce<MessageViewModel | undefined>((latest, message) => {
    if (message.sender !== 'user') return latest;
    if (!latest || compareMessageOrder(latest, message) < 0) return message;
    return latest;
  }, undefined);
}

export function replaceNewestConversationPage(
  pages: readonly ConversationViewModel[],
  newest: ConversationViewModel,
): ConversationViewModel[] {
  if (!pages.length) return [newest];
  const existing = mergeConversationMessageCopies(...pages.map((page) => page.messages), pages[0].queue ?? []);
  const incomingIds = new Set([...newest.messages, ...(newest.queue ?? [])].map((message) => message.id));
  const resolved = mergeConversationMessageCopies(
    existing.filter((message) => incomingIds.has(message.id)),
    newest.messages,
    newest.queue ?? [],
  );
  const messageIds = new Set(newest.messages.map((message) => message.id));
  const queueIds = new Set(newest.queue?.map((message) => message.id));

  return [{
    ...newest,
    messages: resolved.filter((message) => messageIds.has(message.id)),
    ...(newest.queue === undefined ? {} : {
      queue: resolved.filter((message) => queueIds.has(message.id) && !message.deletedAt && !isMessageExecutionTerminal(message.status)),
    }),
    assistantReplies: mergeConversationAssistantReplies([...pages, newest]),
  }, ...pages.slice(1).map((page) => ({
    ...page,
    messages: mergeConversationMessageCopies(page.messages, resolved.filter((message) => message.deletedAt))
      .filter((message) => !message.deletedAt),
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
    : mergeConversationMessageCopies(newest.queue.filter((current) => current.id !== message.id), [resolved])
      .filter((current) => !current.deletedAt && !isMessageExecutionTerminal(current.status));
  return [
    {
      ...newest,
      messages: [...newest.messages.filter((current) => current.id !== message.id), resolved]
        .sort(compareMessageOrder),
      ...(queue === undefined ? {} : { queue }),
    },
    ...pages.slice(1),
  ];
}

export function projectMobileActivity(
  current: ActivityProjection,
  snapshot: ActivitySnapshotViewModel,
): ActivityProjection {
  // Replay metadata describes the Cloud high-water mark and can jump past a
  // page. Continuity for the local reducer must advance only through rows we
  // have actually received.
  const knownSequences = new Set([
    ...(current.pendingActivities ?? []).map((activity) => activity.sequence),
    ...snapshot.activities.map((activity) => activity.sequence),
  ]);
  let safeContiguousSequence = Math.max(
    0,
    current.lastContiguousSequence,
    current.lastContiguousActivitySequence ?? 0,
  );
  while (knownSequences.has(safeContiguousSequence + 1)) safeContiguousSequence += 1;
  return projectActivitySnapshot(current, {
    ...snapshot,
    lastContiguousSequence: safeContiguousSequence,
    lastContiguousActivitySequence: safeContiguousSequence,
  });
}

export function activityStateForMessage(status: MessageStatus): ActivitySnapshotViewModel['state'] {
  return status === 'in_progress' ? 'running' : status;
}

export function isMessageExecutionActive(status: MessageStatus): boolean {
  return status === 'queued' || status === 'in_progress';
}

export function isMessageExecutionTerminal(status: MessageStatus): boolean {
  return status === 'completed' || status === 'failed' || status === 'stopped';
}

export function isMobileActivityTerminalForMessage(
  snapshot: ActivitySnapshotViewModel | null | undefined,
  messageId: string | null | undefined,
): boolean {
  if (!snapshot || !messageId || ACTIVE_ACTIVITY_STATES.includes(snapshot.state)) return false;
  return snapshot.assistantReply?.sourceMessageId === messageId
    || snapshot.activities.at(-1)?.messageId === messageId;
}

export function shouldMergeMobileActivitySnapshot(
  snapshot: ActivitySnapshotViewModel | null | undefined,
  messageId: string | null | undefined,
): boolean {
  return Boolean(snapshot && (
    ACTIVE_ACTIVITY_STATES.includes(snapshot.state)
    || isMobileActivityTerminalForMessage(snapshot, messageId)
  ));
}

export function projectMobileActivityForMessage(
  current: ActivityProjection,
  snapshot: ActivitySnapshotViewModel,
  messageId: string | null | undefined,
): ActivityProjection {
  const projected = projectMobileActivity(current, snapshot);
  return shouldMergeMobileActivitySnapshot(snapshot, messageId)
    ? projected
    : { ...projected, state: current.state };
}

export async function refreshMobileConversationHistory(
  refreshNewest: () => Promise<unknown>,
  refreshHistory: () => Promise<unknown>,
  signal?: AbortSignal,
): Promise<void> {
  try {
    await refreshNewest();
  } catch {
    if (!signal?.aborted) await refreshHistory();
  }
}

export const MOBILE_REPLY_LIMIT_NOTICE = 'This response reached its length limit.';

export function hasPermanentMobileActivityGap(projection: ActivityProjection): boolean {
  return hasPermanentActivityGap(projection);
}

export const MOBILE_ACTIVITY_INITIAL_INTERVAL_MS = 3_000;
export const MOBILE_ACTIVITY_BACKOFF_AFTER_MS = 2 * 60 * 1000;
export const MOBILE_ACTIVITY_MAX_INTERVAL_MS = 15_000;

export function getMobileActivityPollingInterval(input: {
  focused: boolean;
  state: ActivitySnapshotViewModel['state'] | string;
  startedAt: number;
  now: number;
}): number | false {
  if (!input.focused || !ACTIVE_ACTIVITY_STATES.includes(input.state as ActivitySnapshotViewModel['state'])) {
    return false;
  }

  const elapsed = Math.max(0, input.now - input.startedAt);
  if (elapsed <= MOBILE_ACTIVITY_BACKOFF_AFTER_MS) return MOBILE_ACTIVITY_INITIAL_INTERVAL_MS;

  const backoffStep = Math.floor((elapsed - MOBILE_ACTIVITY_BACKOFF_AFTER_MS - 1) / MOBILE_ACTIVITY_BACKOFF_AFTER_MS);
  return Math.min(
    MOBILE_ACTIVITY_MAX_INTERVAL_MS,
    MOBILE_ACTIVITY_INITIAL_INTERVAL_MS * 2 ** (backoffStep + 1),
  );
}

export function isMobileActivityPollingAllowed(input: {
  focused: boolean;
  state: ActivitySnapshotViewModel['state'] | string;
  startedAt: number;
  now: number;
}): boolean {
  return getMobileActivityPollingInterval(input) !== false;
}

export function shouldContinueMobileActivityPolling(input: {
  focused: boolean;
  state?: ActivitySnapshotViewModel['state'] | string | null;
  knownExecutionActive: boolean;
}): boolean {
  return input.focused
    && (input.knownExecutionActive
      || (input.state !== null
        && input.state !== undefined
        && ACTIVE_ACTIVITY_STATES.includes(input.state as ActivitySnapshotViewModel['state'])));
}

export function isMobileActivityPollErrorRecoverable(error: unknown): boolean {
  if (error === null || error === undefined) return true;
  return isCloudError(error)
    && ['network', 'timeout', 'server', 'throttled'].includes(error.kind);
}

export interface MobileActivityReplayPageOptions {
  limit: number;
  cursor?: string;
  replay: true;
  signal?: AbortSignal;
}

export type MobileActivityReplayFetcher = (
  options: MobileActivityReplayPageOptions,
) => Promise<ActivitySnapshotViewModel>;

export const MOBILE_ACTIVITY_REPLAY_PAGE_LIMIT = 200;
export const MOBILE_ACTIVITY_REPLAY_MAX_PAGES = 64;

export class MobileActivityReplayBoundsError extends Error {
  constructor() {
    super('Activity replay exceeded the mobile page bound');
    this.name = 'MobileActivityReplayBoundsError';
  }
}

export async function loadMobileActivityReplay(
  fetchPage: MobileActivityReplayFetcher,
  signal?: AbortSignal,
  initialCursor?: string,
): Promise<ActivitySnapshotViewModel[]> {
  try {
    return await loadMobileActivityReplayFromCursor(fetchPage, signal, initialCursor);
  } catch (error) {
    // A cursor used for an incremental catch-up can expire between polls. A
    // single origin replay gives the caller a fresh signed high-water cursor.
    if (initialCursor && isCloudError(error) && error.kind === 'activity-cursor-expired') {
      return loadMobileActivityReplayFromCursor(fetchPage, signal);
    }
    throw error;
  }
}

async function loadMobileActivityReplayFromCursor(
  fetchPage: MobileActivityReplayFetcher,
  signal?: AbortSignal,
  initialCursor?: string,
): Promise<ActivitySnapshotViewModel[]> {
  const pages: ActivitySnapshotViewModel[] = [];
  const seenCursors = new Set<string>();
  let cursor: string | undefined = initialCursor;

  for (let pageIndex = 0; pageIndex < MOBILE_ACTIVITY_REPLAY_MAX_PAGES; pageIndex += 1) {
    if (cursor) {
      if (seenCursors.has(cursor)) throw new MobileActivityReplayBoundsError();
      seenCursors.add(cursor);
    }

    const page = await fetchPage({
      limit: MOBILE_ACTIVITY_REPLAY_PAGE_LIMIT,
      ...(cursor ? { cursor } : {}),
      replay: true,
      ...(signal ? { signal } : {}),
    });
    pages.push(page);
    if (!page.nextCursor) return pages;
    cursor = page.nextCursor;
  }

  throw new MobileActivityReplayBoundsError();
}

export function shouldRetryMobileActivityReplay(failureCount: number, error: unknown): boolean {
  return failureCount < 1
    && isCloudError(error)
    && error.kind === 'activity-cursor-expired';
}

export function hasMobileActivityReplayGap(
  pages: readonly ActivitySnapshotViewModel[],
  error?: unknown,
  fromOrigin = true,
): boolean {
  if (isCloudError(error) && error.kind === 'activity-cursor-gap') return true;
  return pages.some((page) => page.retentionGap === true || (fromOrigin && (page.oldestSequence ?? 0) > 1));
}

function compareReplyVersion(left: AssistantReplyViewModel, right: AssistantReplyViewModel): number {
  if (left.hasFullPrefix !== right.hasFullPrefix) return left.hasFullPrefix ? 1 : -1;
  const leftTime = Date.parse(left.updatedAt) || Date.parse(left.createdAt) || 0;
  const rightTime = Date.parse(right.updatedAt) || Date.parse(right.createdAt) || 0;
  const statusRank: Record<MessageStatus, number> = {
    queued: 0,
    in_progress: 1,
    awaiting_action: 2,
    completed: 3,
    failed: 3,
    stopped: 3,
  };
  if (leftTime !== rightTime) return leftTime - rightTime;
  if (statusRank[left.status] !== statusRank[right.status]) {
    return statusRank[left.status] - statusRank[right.status];
  }
  if (left.content.length !== right.content.length) return left.content.length - right.content.length;
  if (Boolean(left.isTruncated) !== Boolean(right.isTruncated)) return left.isTruncated ? 1 : -1;
  return left.id.localeCompare(right.id);
}

export function mergeConversationAssistantReplies(
  pages: readonly ConversationViewModel[],
  activityReplies?: AssistantReplyViewModel | readonly (AssistantReplyViewModel | null)[] | null,
): AssistantReplyViewModel[] {
  const replies = new Map<string, AssistantReplyViewModel>();
  for (const page of pages) {
    for (const reply of page.assistantReplies ?? []) {
      const existing = replies.get(reply.sourceMessageId);
      if (!existing || compareReplyVersion(existing, reply) <= 0) replies.set(reply.sourceMessageId, reply);
    }
  }
  const additionalReplies = Array.isArray(activityReplies)
    ? activityReplies.filter((reply): reply is AssistantReplyViewModel => reply !== null)
    : activityReplies ? [activityReplies as AssistantReplyViewModel] : [];
  for (const reply of additionalReplies) {
    const existing = replies.get(reply.sourceMessageId);
    if (!existing || compareReplyVersion(existing, reply) <= 0) {
      replies.set(reply.sourceMessageId, reply);
    }
  }
  return [...replies.values()].sort(
    (left, right) => left.conversationTurnOrdinal - right.conversationTurnOrdinal
      || left.sourceMessageId.localeCompare(right.sourceMessageId)
      || left.id.localeCompare(right.id),
  );
}

export type MobileInlineReply =
  | { kind: 'durable'; reply: AssistantReplyViewModel }
  | { kind: 'activity'; turn: AssistantTurnProjection };

export interface MobileReplySelection {
  inlineBySourceMessageId: Map<string, MobileInlineReply>;
  remainingReplies: AssistantReplyViewModel[];
  remainingTurns: AssistantTurnProjection[];
  suppressedAssistantMessageIds: Set<string>;
}

export function selectMobileConversationReplies(
  messages: readonly MessageViewModel[],
  turns: readonly AssistantTurnProjection[],
  replies: readonly AssistantReplyViewModel[],
): MobileReplySelection {
  const fullReplies = new Map(
    replies.filter((reply) => reply.hasFullPrefix).map((reply) => [reply.sourceMessageId, reply]),
  );
  const persistedAssistantMessageIds = new Map<string, Set<string>>();
  let sourceMessageId: string | null = null;
  for (const message of messages) {
    if (message.sender === 'user') {
      sourceMessageId = message.id;
      continue;
    }
    if (!sourceMessageId) continue;
    const ids = persistedAssistantMessageIds.get(sourceMessageId) ?? new Set<string>();
    ids.add(message.id);
    persistedAssistantMessageIds.set(sourceMessageId, ids);
  }

  const inlineBySourceMessageId = new Map<string, MobileInlineReply>();
  const renderedTurnIds = new Set<string>();
  const renderedReplyIds = new Set<string>();
  const suppressedAssistantMessageIds = new Set<string>();

  for (const message of messages) {
    if (message.sender !== 'user') continue;
    const turn = turns.find((candidate) => candidate.messageId === message.id)
      ?? turns.find((candidate) => candidate.turnOrdinal === message.sequence);
    const reply = fullReplies.get(message.id);
    if (reply) {
      inlineBySourceMessageId.set(message.id, { kind: 'durable', reply });
      renderedReplyIds.add(reply.id);
      if (turn) renderedTurnIds.add(turn.messageId);
      for (const assistantMessageId of persistedAssistantMessageIds.get(message.id) ?? []) {
        suppressedAssistantMessageIds.add(assistantMessageId);
      }
      continue;
    }
    if (persistedAssistantMessageIds.has(message.id)) {
      if (turn) renderedTurnIds.add(turn.messageId);
      continue;
    }
    if (!turn) continue;
    inlineBySourceMessageId.set(message.id, { kind: 'activity', turn });
    renderedTurnIds.add(turn.messageId);
  }

  const remainingTurns = turns.filter((turn) => {
    if (renderedTurnIds.has(turn.messageId)) return false;
    if (fullReplies.has(turn.messageId) || persistedAssistantMessageIds.has(turn.messageId)) return false;
    return true;
  });
  const remainingReplies = [...fullReplies.values()].filter((reply) => !renderedReplyIds.has(reply.id));

  return {
    inlineBySourceMessageId,
    remainingReplies,
    remainingTurns,
    suppressedAssistantMessageIds,
  };
}
