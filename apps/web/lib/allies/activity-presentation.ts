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
  const bySequence = new Map<number, ActivityPresentationEntry>();

  for (const group of Object.values(base.groupsByKey)) {
    for (const entry of group.entries) bySequence.set(entry.sequence, entry);
  }
  for (const activity of input.activities) {
    const entry = toPresentationEntry(activity);
    if (!entry) continue;
    const existing = bySequence.get(entry.sequence);
    if (!existing || entry.id.localeCompare(existing.id) < 0) {
      bySequence.set(entry.sequence, entry);
    }
  }

  const sortedEntries = [...bySequence.values()].sort(compareEntries);
  const retainedEntries = sortedEntries.slice(-limit);
  const evictedBeforeSequence = sortedEntries.length > retainedEntries.length
    ? Math.max(
      base.evictedBeforeSequence,
      ...sortedEntries.slice(0, sortedEntries.length - retainedEntries.length).map((entry) => entry.sequence),
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
        firstSequence: entry.sequence,
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
  };
}

function compareEntries(left: ActivityPresentationEntry, right: ActivityPresentationEntry): number {
  return left.sequence - right.sequence || left.id.localeCompare(right.id);
}

function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 200;
  return Math.max(1, Math.min(200, Math.floor(value)));
}
