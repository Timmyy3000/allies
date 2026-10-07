import type { ActivitySnapshotViewModel, ActivityState, ActivityViewModel } from "./mappers/allies";

export const ACTIVE_ACTIVITY_STATES: readonly ActivityState[] = ["queued", "running", "awaiting_action"];

export interface AssistantTurnProjection {
  assistantText: string;
  messageId: string;
  state: ActivityState;
  turnOrdinal: number;
}

export interface ActivityProjection {
  activeMessageId?: string | null;
  seenSequences: number[];
  turns: AssistantTurnProjection[];
  state: ActivityState;
  lastContiguousSequence: number;
  lastContiguousActivitySequence?: number;
  pendingActivities?: ActivityViewModel[];
}

export const EMPTY_ACTIVITY_PROJECTION: ActivityProjection = {
  seenSequences: [],
  turns: [],
  state: "queued",
  lastContiguousSequence: 0,
  lastContiguousActivitySequence: 0,
};

export function projectActivitySnapshot(
  current: ActivityProjection,
  snapshot: ActivitySnapshotViewModel,
): ActivityProjection {
  const seen = new Set(current.seenSequences);
  const pending = new Map(
    (current.pendingActivities ?? []).map((activity) => [activity.sequence, activity]),
  );
  const turns = new Map(current.turns.map((turn) => [turn.turnOrdinal, turn]));

  for (const activity of [...snapshot.activities].sort(compareActivity)) {
    if (seen.has(activity.sequence) || seen.has(firstSequence(activity))) {
      const existing = turns.get(activity.conversationTurnOrdinal);
      if (existing) {
        turns.set(activity.conversationTurnOrdinal, {
          ...existing,
          state: mergeActivityState(existing.state, activity.state),
        });
      }
      continue;
    }
    const existing = pending.get(firstSequence(activity));
    pending.set(
      firstSequence(activity),
      existing?.id === activity.id
        ? activity
        : existing && compareActivity(existing, activity) <= 0
          ? existing
          : activity,
    );
  }

  let lastContiguousSequence = Math.max(
    0,
    current.lastContiguousSequence,
    current.lastContiguousActivitySequence ?? 0,
  );
  // Snapshot continuity is attempt-local; visible activity sequences are conversation-global.
  while (pending.has(lastContiguousSequence + 1)) {
    const nextSequence = lastContiguousSequence + 1;
    const activity = pending.get(nextSequence)!;
    pending.delete(nextSequence);
    // A compacted replay row stands in for every sequence it covers.
    for (let sequence = nextSequence; sequence <= activity.sequence; sequence += 1) seen.add(sequence);
    const existing = turns.get(activity.conversationTurnOrdinal);
    turns.set(activity.conversationTurnOrdinal, {
      assistantText:
        (existing?.assistantText ?? "")
        + (activity.kind === "assistant_delta" ? activity.text : ""),
      messageId: activity.messageId,
      state: mergeActivityState(existing?.state, activity.state),
      turnOrdinal: activity.conversationTurnOrdinal,
    });
    lastContiguousSequence = activity.sequence;
  }

  const pendingActivities = [...pending.values()]
    .filter((activity) => !seen.has(activity.sequence) && activity.sequence > lastContiguousSequence)
    .sort(compareActivity);

  return {
    seenSequences: [...seen].sort((left, right) => left - right),
    turns: [...turns.values()].sort(
      (left, right) => left.turnOrdinal - right.turnOrdinal || left.messageId.localeCompare(right.messageId),
    ),
    activeMessageId: snapshot.activeMessageId,
    state: snapshot.activeMessageId !== undefined && snapshot.activeMessageId !== current.activeMessageId
      ? snapshot.state
      : mergeActivityState(current.state, snapshot.state),
    lastContiguousSequence,
    lastContiguousActivitySequence: lastContiguousSequence,
    ...(pendingActivities.length > 0 ? { pendingActivities } : {}),
  };
}

export function isActivityTerminal(state: ActivityState): boolean {
  return !ACTIVE_ACTIVITY_STATES.includes(state);
}

export function hasPermanentActivityGap(projection: ActivityProjection): boolean {
  return isActivityTerminal(projection.state) && Boolean(projection.pendingActivities?.length);
}

function firstSequence(activity: ActivityViewModel): number {
  return activity.firstSequence ?? activity.sequence;
}

function compareActivity(left: ActivityViewModel, right: ActivityViewModel): number {
  return left.sequence - right.sequence || left.id.localeCompare(right.id);
}

function mergeActivityState(
  current: ActivityState | undefined,
  incoming: ActivityState,
): ActivityState {
  if (current && isActivityTerminal(current)) return current;
  if (isActivityTerminal(incoming)) return incoming;
  if (incoming === "awaiting_action") return incoming;
  if (current === "running" || incoming === "running") return "running";
  if (current === "awaiting_action") return current;
  return incoming;
}
