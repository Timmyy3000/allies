import type { ActivityViewModel } from "@allies/cloud-client";
import { describe, expect, it } from "vitest";

import {
  EMPTY_ACTIVITY_PRESENTATION,
  activityTurnKey,
  mergeActivityPresentation,
} from "./activity-presentation";

function activity(
  id: string,
  sequence: number,
  overrides: Partial<ActivityViewModel> = {},
): ActivityViewModel {
  return {
    id,
    messageId: "message-1",
    sequence,
    conversationTurnOrdinal: 1,
    kind: "activity_started",
    text: `Activity ${sequence}`,
    state: "running",
    createdAt: `2026-09-03T00:00:${String(sequence).padStart(2, "0")}Z`,
    ...overrides,
  };
}

describe("mergeActivityPresentation", () => {
  it("keeps only non-empty product activity kinds and trims presentation text", () => {
    const result = mergeActivityPresentation(EMPTY_ACTIVITY_PRESENTATION, {
      conversationId: "conversation-1",
      activities: [
        activity("displayable", 1, { text: "  Searching for citysubs  " }),
        activity("completed", 2, { kind: "activity_completed", state: "completed" }),
        activity("waiting", 3, { kind: "awaiting_action", state: "awaiting_action" }),
        activity("delta", 4, { kind: "assistant_delta", text: "assistant text" }),
        activity("blank", 5, { text: "   " }),
      ],
    });

    expect(result.retainedEntryCount).toBe(3);
    expect(result.groupsByKey[activityTurnKey("message-1", 1)]?.entries.map((entry) => entry.text)).toEqual([
      "Searching for citysubs",
      "Activity 2",
      "Activity 3",
    ]);
  });

  it("uses both message id and turn ordinal as the group key", () => {
    const result = mergeActivityPresentation(EMPTY_ACTIVITY_PRESENTATION, {
      conversationId: "conversation-1",
      activities: [
        activity("one", 1, { messageId: "message-a", conversationTurnOrdinal: 4 }),
        activity("two", 2, { messageId: "message-b", conversationTurnOrdinal: 4 }),
        activity("three", 3, { messageId: "message-a", conversationTurnOrdinal: 5 }),
      ],
    });

    expect(result.orderedKeys).toEqual([
      activityTurnKey("message-a", 4),
      activityTurnKey("message-b", 4),
      activityTurnKey("message-a", 5),
    ]);
    expect(result.groupsByKey[activityTurnKey("message-a", 4)]?.entries).toHaveLength(1);
  });

  it("deduplicates replayed and out-of-order entries deterministically", () => {
    const first = mergeActivityPresentation(EMPTY_ACTIVITY_PRESENTATION, {
      conversationId: "conversation-1",
      activities: [activity("z-entry", 2), activity("first", 1)],
    });
    const result = mergeActivityPresentation(first, {
      conversationId: "conversation-1",
      activities: [
        activity("replay", 1, { text: "Replay should not replace the first entry" }),
        activity("a-entry", 2, { text: "Lowest id wins" }),
        activity("third", 3),
      ],
    });

    expect(result.retainedEntryCount).toBe(3);
    expect(result.groupsByKey[activityTurnKey("message-1", 1)]?.entries.map((entry) => entry.id)).toEqual([
      "first",
      "a-entry",
      "third",
    ]);
  });

  it("resets when the conversation changes and evicts oldest entries globally", () => {
    const entries = Array.from({ length: 201 }, (_, index) => activity(`entry-${String(index + 1).padStart(3, "0")}`, index + 1));
    const result = mergeActivityPresentation(EMPTY_ACTIVITY_PRESENTATION, {
      conversationId: "conversation-1",
      activities: entries,
    });

    expect(result.retainedEntryCount).toBe(200);
    expect(result.evictedBeforeSequence).toBe(1);
    expect(result.groupsByKey[activityTurnKey("message-1", 1)]?.entries[0]?.sequence).toBe(2);

    const reset = mergeActivityPresentation(result, {
      conversationId: "conversation-2",
      activities: [activity("new", 1, { messageId: "new-message" })],
    });

    expect(reset.conversationId).toBe("conversation-2");
    expect(reset.retainedEntryCount).toBe(1);
    expect(reset.evictedBeforeSequence).toBe(0);
    expect(Object.keys(reset.groupsByKey)).toEqual([activityTurnKey("new-message", 1)]);
  });

  it("clamps an invalid requested limit to the safe display bounds", () => {
    const result = mergeActivityPresentation(EMPTY_ACTIVITY_PRESENTATION, {
      conversationId: "conversation-1",
      activities: [activity("one", 1), activity("two", 2)],
    }, 0);

    expect(result.retainedEntryCount).toBe(1);
    expect(result.evictedBeforeSequence).toBe(1);
  });
});
