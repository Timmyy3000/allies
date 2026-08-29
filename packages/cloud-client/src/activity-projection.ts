import type { ActivitySnapshotViewModel, ActivityState, ActivityViewModel } from "./mappers/allies";

export const ACTIVE_ACTIVITY_STATES: readonly ActivityState[] = ["queued", "running"];

export interface AssistantTurnProjection {
  assistantText: string;
  messageId: string;
  state: ActivityState;
  turnOrdinal: number;
}

export interface ActivityProjection {
  seenSequences: number[];
  turns: AssistantTurnProjection[];
  state: ActivityState;
  lastContiguousSequence: number;
  pendingActivities?: ActivityViewModel[];
}

export const EMPTY_ACTIVITY_PROJECTION: ActivityProjection = {
  seenSequences: [],
  turns: [],
  state: "queued",
  lastContiguousSequence: 0,
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
    if (seen.has(activity.sequence)) {
      const existing = turns.get(activity.conversationTurnOrdinal);
      if (existing) {
        turns.set(activity.conversationTurnOrdinal, {
          ...existing,
          state: mergeActivityState(existing.state, activity.state),
        });
      }
      continue;
    }
    const existing = pending.get(activity.sequence);
    pending.set(
      activity.sequence,
      existing?.id === activity.id
        ? activity
        : existing && compareActivity(existing, activity) <= 0
          ? existing
          : activity,
    );
  }

  const contiguousLimit = Math.max(current.lastContiguousSequence, snapshot.lastContiguousSequence);
  let lastContiguousSequence = Math.max(0, current.lastContiguousSequence);
  while (lastContiguousSequence < contiguousLimit) {
    const nextSequence = lastContiguousSequence + 1;
    const activity = pending.get(nextSequence);
    if (!activity) break;
    pending.delete(nextSequence);
    seen.add(nextSequence);
    const existing = turns.get(activity.conversationTurnOrdinal);
    turns.set(activity.conversationTurnOrdinal, {
      assistantText:
        (existing?.assistantText ?? "")
        + (activity.kind === "assistant_delta" ? activity.text : ""),
      messageId: activity.messageId,
      state: mergeActivityState(existing?.state, activity.state),
      turnOrdinal: activity.conversationTurnOrdinal,
    });
    lastContiguousSequence = nextSequence;
  }

  const pendingActivities = [...pending.values()]
    .filter((activity) => !seen.has(activity.sequence) && activity.sequence > lastContiguousSequence)
    .sort(compareActivity);

  return {
    seenSequences: [...seen].sort((left, right) => left - right),
    turns: [...turns.values()].sort(
      (left, right) => left.turnOrdinal - right.turnOrdinal || left.messageId.localeCompare(right.messageId),
    ),
    state: mergeActivityState(current.state, snapshot.state),
    lastContiguousSequence,
    ...(pendingActivities.length > 0 ? { pendingActivities } : {}),
  };
}

export function isActivityTerminal(state: ActivityState): boolean {
  return !ACTIVE_ACTIVITY_STATES.includes(state);
}

export function hasPermanentActivityGap(projection: ActivityProjection): boolean {
  return isActivityTerminal(projection.state) && Boolean(projection.pendingActivities?.length);
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
  if (current === "running" || incoming === "running") return "running";
  return incoming;
}
