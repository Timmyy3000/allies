import type { ActivityState, ActivityViewModel } from "@allies/cloud-client";

export const DISPLAYABLE_ACTIVITY_KINDS = [
  "activity_started",
  "activity_completed",
  "awaiting_action",
] as const;

export type DisplayableActivityKind = (typeof DISPLAYABLE_ACTIVITY_KINDS)[number];

export interface ActivityPresentationEntry {
  id: string;
  sequence: number;
  messageId: string;
  conversationTurnOrdinal: number;
  kind: DisplayableActivityKind;
  text: string;
  state: ActivityState;
  createdAt: string;
  activityAttemptId?: string | null;
  activityId?: string | null;
  activityKind?: string | null;
  outcome?: "completed" | "failed" | "stopped" | "unavailable" | null;
  durationMs?: number | null;
  firstSequence?: number;
  terminalSequence?: number;
}

export interface ActivityPresentationGroup {
  key: string;
  messageId: string;
  conversationTurnOrdinal: number;
  entries: ActivityPresentationEntry[];
  firstSequence: number;
  lastSequence: number;
}

export interface ActivityPresentationState {
  conversationId: string | null;
  groupsByKey: Record<string, ActivityPresentationGroup>;
  orderedKeys: string[];
  retainedEntryCount: number;
  evictedBeforeSequence: number;
  terminals?: Record<string, { sequence: number; outcome: "failed" | "stopped" | "unavailable" }>;
}

export const EMPTY_ACTIVITY_PRESENTATION: ActivityPresentationState = {
  conversationId: null,
  groupsByKey: {},
  orderedKeys: [],
  retainedEntryCount: 0,
  evictedBeforeSequence: 0,
};

export function activityTurnKey(messageId: string, conversationTurnOrdinal: number): string {
  return `${messageId}:${conversationTurnOrdinal}`;
}

export function isDisplayableActivityKind(
  kind: ActivityViewModel["kind"],
): kind is DisplayableActivityKind {
  return (DISPLAYABLE_ACTIVITY_KINDS as readonly string[]).includes(kind);
}

export function mergeActivityPresentation(
  current: ActivityPresentationState,
  input: {
    conversationId: string;
    activities: readonly ActivityViewModel[];
  },
  requestedLimit = 200,
): ActivityPresentationState {
  const limit = clampLimit(requestedLimit);
  const base = current.conversationId === input.conversationId
    ? current
    : EMPTY_ACTIVITY_PRESENTATION;
  const entries = new Map<string, ActivityPresentationEntry>();
  const terminals = { ...base.terminals };

  for (const group of Object.values(base.groupsByKey)) {
    for (const entry of group.entries) entries.set(entryKey(entry), entry);
  }
  for (const activity of [...input.activities].sort((a, b) => a.sequence - b.sequence)) {
    if (activity.sequence <= base.evictedBeforeSequence) continue;
    if (activity.activityAttemptId && ["execution_completed", "execution_failed", "execution_stopped"].includes(activity.kind)) {
      const key = attemptKey(activity);
      if (!terminals[key] || activity.sequence < terminals[key].sequence) {
        terminals[key] = { sequence: activity.sequence, outcome: activity.kind === "execution_failed" ? "failed" : activity.kind === "execution_stopped" ? "stopped" : "unavailable" };
      }
      continue;
    }
    const entry = toPresentationEntry(activity);
    if (!entry) continue;
    const key = entryKey(entry);
    const existing = entries.get(key);
    if (!existing) {
      if (entry.outcome && entry.activityId && entry.activityAttemptId && base.evictedBeforeSequence > 0) continue;
      entries.set(key, entry);
    } else if (entry.activityId && entry.activityAttemptId) {
      const firstSequence = Math.min(existing.firstSequence ?? existing.sequence, entry.sequence);
      if (entry.outcome && (!existing.terminalSequence || entry.sequence < existing.terminalSequence)) {
        entries.set(key, { ...entry, id: existing.id, firstSequence });
      } else {
        entries.set(key, { ...existing, firstSequence });
      }
    } else if (entry.id.localeCompare(existing.id) < 0) {
      entries.set(key, entry);
    }
  }

  const sortedEntries = [...entries.values()].map((entry) => {
    const terminal = terminals[attemptKey(entry)];
    if (!entry.activityAttemptId || !entry.activityId || !terminal) return entry;
    if (entry.outcome && entry.terminalSequence && entry.terminalSequence <= terminal.sequence) return entry;
    return { ...entry, outcome: terminal.outcome, terminalSequence: terminal.sequence,
      text: terminal.outcome === "failed" ? "Activity interrupted by a failed response" : terminal.outcome === "stopped" ? "Activity stopped" : "Activity status unavailable" };
  }).sort(compareEntries);
  const retainedEntries = sortedEntries.slice(-limit);
  const evictedBeforeSequence = sortedEntries.length > retainedEntries.length
    ? Math.max(
      base.evictedBeforeSequence,
      ...sortedEntries.slice(0, sortedEntries.length - retainedEntries.length).map((entry) => entry.firstSequence ?? entry.sequence),
    )
    : base.evictedBeforeSequence;
  const groupsByKey: Record<string, ActivityPresentationGroup> = {};

  for (const entry of retainedEntries) {
    const key = activityTurnKey(entry.messageId, entry.conversationTurnOrdinal);
    const group = groupsByKey[key];
    if (group) {
      group.entries.push(entry);
      group.lastSequence = Math.max(group.lastSequence, entry.sequence);
    } else {
      groupsByKey[key] = {
        key,
        messageId: entry.messageId,
        conversationTurnOrdinal: entry.conversationTurnOrdinal,
        entries: [entry],
        firstSequence: entry.firstSequence ?? entry.sequence,
        lastSequence: entry.sequence,
      };
    }
  }

  const orderedKeys = Object.values(groupsByKey)
    .sort((left, right) => left.firstSequence - right.firstSequence || left.key.localeCompare(right.key))
    .map((group) => group.key);

  return {
    conversationId: input.conversationId,
    groupsByKey,
    orderedKeys,
    retainedEntryCount: retainedEntries.length,
    evictedBeforeSequence,
    terminals: Object.fromEntries(Object.entries(terminals).sort(([, a], [, b]) => b.sequence - a.sequence).slice(0, 200)),
  };
}

function toPresentationEntry(activity: ActivityViewModel): ActivityPresentationEntry | null {
  if (
    !activity.id
    || !activity.messageId
    || !Number.isInteger(activity.sequence)
    || activity.sequence <= 0
    || !Number.isInteger(activity.conversationTurnOrdinal)
    || activity.conversationTurnOrdinal <= 0
    || !activity.text.trim()
    || !isDisplayableActivityKind(activity.kind)
  ) return null;

  return {
    id: activity.id,
    sequence: activity.sequence,
    messageId: activity.messageId,
    conversationTurnOrdinal: activity.conversationTurnOrdinal,
    kind: activity.kind,
    text: activity.text.trim(),
    state: activity.state,
    createdAt: activity.createdAt,
    activityAttemptId: activity.activityAttemptId,
    activityId: activity.activityId,
    activityKind: activity.activityKind,
    outcome: activity.outcome,
    durationMs: activity.durationMs,
    firstSequence: activity.sequence,
    terminalSequence: activity.outcome ? activity.sequence : undefined,
  };
}

function compareEntries(left: ActivityPresentationEntry, right: ActivityPresentationEntry): number {
  return (left.firstSequence ?? left.sequence) - (right.firstSequence ?? right.sequence) || left.id.localeCompare(right.id);
}

function attemptKey(entry: { messageId: string; conversationTurnOrdinal: number; activityAttemptId?: string | null }): string {
  return `${activityTurnKey(entry.messageId, entry.conversationTurnOrdinal)}:${entry.activityAttemptId ?? "legacy"}`;
}

function entryKey(entry: ActivityPresentationEntry): string {
  return entry.activityId && entry.activityAttemptId ? `${attemptKey(entry)}:${entry.activityId}` : `sequence:${entry.sequence}`;
}

function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 200;
  return Math.max(1, Math.min(200, Math.floor(value)));
}
